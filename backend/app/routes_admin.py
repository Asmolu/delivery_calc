import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..core.logger import get_logger
from ..core.database import get_db
from ..core.auth import require_admin
from ..core.db_migration import ensure_catalog_normalization
from ..models.db_models import Category, Factory, Order, OrderEvent, OrderStatus, Product, User
from ..core.data_loader import (
    load_factories_from_google,
    load_tariffs_from_google,
)

router = APIRouter()
log = get_logger("routes.admin")

MAX_ORDERS_TO_KEEP = 100


@router.post("/admin/reload")
async def admin_reload(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    🔄 Перезагрузка и factories, и tariffs из Google Sheets в БД.
    """
    try:
        ensure_catalog_normalization(db)
        log.info("Запуск полного обновления данных из Google Sheets...")
        factories = load_factories_from_google(db)
        tariffs_result = load_tariffs_from_google(db)

        return JSONResponse(
            content={
                "factories_count": len(factories),
                "tariffs": tariffs_result,
            }
        )
    except Exception as e:
        import traceback

        traceback.print_exc()
        log.error("Ошибка при обновлении данных: %s", e)
        return JSONResponse(
            status_code=500,
            content={"detail": f"Ошибка при обновлении данных: {e}"},
        )


@router.post("/admin/reload/factories")
async def admin_reload_factories(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    try:
        ensure_catalog_normalization(db)
        log.info("Обновление factories из Google Sheets...")
        factories = load_factories_from_google(db)
        return JSONResponse(
            content={"status": "ok", "factories_count": len(factories)}
        )
    except Exception as e:
        import traceback

        traceback.print_exc()
        log.error("Ошибка при обновлении factories: %s", e)
        return JSONResponse(
            status_code=500,
            content={"detail": f"Ошибка при обновлении factories: {e}"},
        )


@router.post("/admin/reload/tariffs")
async def admin_reload_tariffs(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    try:
        ensure_catalog_normalization(db)
        log.info("Обновление tariffs из Google Sheets...")
        result = load_tariffs_from_google(db)
        return JSONResponse(content=result)
    except Exception as e:
        import traceback

        traceback.print_exc()
        log.error("Ошибка при обновлении tariffs: %s", e)
        return JSONResponse(
            status_code=500,
            content={"detail": f"Ошибка при обновлении тарифов: {e}"},
        )


# === Будущее редактирование каталога (валидация на уровне API) ===============

class CategoryUpsert(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class ProductUpsert(BaseModel):
    factory_id: int
    category_id: int
    subtype: str = Field(..., min_length=1, max_length=255)
    weight_per_item: float = 0.0
    special_threshold: float = 0.0
    max_per_trip: float = 0.0
    price: float = 0.0


class OrderCreateFromQuote(BaseModel):
    request: dict
    variants: list[dict] = Field(default_factory=list)
    selectedVariant: int = Field(..., ge=0)
    warningText: str | None = None
    needsLogisticsCheck: bool = False


class ManualDecision(BaseModel):
    transportName: str = Field(..., min_length=1, max_length=255)
    notes: str | None = None
    # любые дополнительные поля, которые логист заполнит (стоимости, рейсы, и т.д.)
    payload: dict = Field(default_factory=dict)


class OrderDecision(BaseModel):
    notes: str | None = None
    payload: dict = Field(default_factory=dict)


def _derive_order_meta(events: list[OrderEvent]) -> dict:
    """Вычисляем полезные "человеческие" поля из истории событий заказа."""
    accepted_event = None
    decision_event = None
    last_event = events[-1] if events else None

    for e in events:
        if e.event_type in ("confirmed_auto", "confirmed_manual") and accepted_event is None:
            accepted_event = e
        if e.event_type in ("approved", "declined"):
            decision_event = e  # последняя из approved/declined

    return {
        "acceptedBy": (accepted_event.user.username if accepted_event and accepted_event.user else None),
        "acceptedAt": (accepted_event.created_at.isoformat() if accepted_event and accepted_event.created_at else None),
        "decision": (decision_event.event_type if decision_event else None),
        "decisionBy": (decision_event.user.username if decision_event and decision_event.user else None),
        "decisionAt": (decision_event.created_at.isoformat() if decision_event and decision_event.created_at else None),
        "lastEventType": (last_event.event_type if last_event else None),
        "lastEventBy": (last_event.user.username if last_event and last_event.user else None),
        "lastEventAt": (last_event.created_at.isoformat() if last_event and last_event.created_at else None),
    }


def _enforce_orders_limit(db: Session, limit: int = MAX_ORDERS_TO_KEEP) -> None:
    """Храним не больше N последних заказов.

    Важно: у OrderEvent нет ON DELETE CASCADE, поэтому удаляем события вручную,
    затем сами заказы.
    """
    extra_ids = [
        oid
        for (oid,) in (
            db.query(Order.id)
            .order_by(Order.created_at.desc())
            .offset(limit)
            .all()
        )
    ]
    if not extra_ids:
        return

    # сначала события, потом заказы (иначе FK запретит удаление)
    db.query(OrderEvent).filter(OrderEvent.order_id.in_(extra_ids)).delete(synchronize_session=False)
    db.query(Order).filter(Order.id.in_(extra_ids)).delete(synchronize_session=False)


@router.get("/admin/categories")
async def admin_list_categories(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    cats = db.query(Category).order_by(Category.name.asc()).all()
    return [{"id": c.id, "name": c.name} for c in cats]


@router.post("/admin/categories")
async def admin_create_category(
    payload: CategoryUpsert,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    name = payload.name.strip()
    if db.query(Category).filter(Category.name == name).first():
        raise HTTPException(status_code=409, detail="Категория с таким именем уже существует")

    cat = Category(name=name)
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return {"id": cat.id, "name": cat.name}


@router.put("/admin/categories/{category_id}")
async def admin_update_category(
    category_id: int,
    payload: CategoryUpsert,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    cat = db.query(Category).filter(Category.id == category_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Категория не найдена")

    name = payload.name.strip()
    exists = db.query(Category).filter(Category.name == name, Category.id != category_id).first()
    if exists:
        raise HTTPException(status_code=409, detail="Категория с таким именем уже существует")

    cat.name = name
    db.commit()
    db.refresh(cat)
    return {"id": cat.id, "name": cat.name}


@router.post("/admin/products")
async def admin_create_product(
    payload: ProductUpsert,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    factory = db.query(Factory).filter(Factory.id == payload.factory_id).first()
    if not factory:
        raise HTTPException(status_code=400, detail="factory_id: завод не найден")

    category = db.query(Category).filter(Category.id == payload.category_id).first()
    if not category:
        raise HTTPException(status_code=400, detail="category_id: категория не найдена")

    subtype = payload.subtype.strip()
    if db.query(Product).filter(
        Product.factory_id == payload.factory_id,
        Product.category_id == payload.category_id,
        Product.subtype == subtype,
    ).first():
        raise HTTPException(status_code=409, detail="Такой товар уже существует (factory_id + category_id + subtype)")

    product = Product(
        factory_id=payload.factory_id,
        category_id=payload.category_id,
        category=category.name,  # для совместимости
        subtype=subtype,
        weight_per_item=max(payload.weight_per_item, 0.0),
        special_threshold=max(payload.special_threshold, 0.0),
        max_per_trip=max(payload.max_per_trip, 0.0),
        price=max(payload.price, 0.0),
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return {"id": product.id}


@router.put("/admin/products/{product_id}")
async def admin_update_product(
    product_id: int,
    payload: ProductUpsert,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Товар не найден")

    factory = db.query(Factory).filter(Factory.id == payload.factory_id).first()
    if not factory:
        raise HTTPException(status_code=400, detail="factory_id: завод не найден")

    category = db.query(Category).filter(Category.id == payload.category_id).first()
    if not category:
        raise HTTPException(status_code=400, detail="category_id: категория не найдена")

    subtype = payload.subtype.strip()
    exists = db.query(Product).filter(
        Product.id != product_id,
        Product.factory_id == payload.factory_id,
        Product.category_id == payload.category_id,
        Product.subtype == subtype,
    ).first()
    if exists:
        raise HTTPException(status_code=409, detail="Такой товар уже существует (factory_id + category_id + subtype)")

    product.factory_id = payload.factory_id
    product.category_id = payload.category_id
    product.category = category.name  # для совместимости
    product.subtype = subtype
    product.weight_per_item = max(payload.weight_per_item, 0.0)
    product.special_threshold = max(payload.special_threshold, 0.0)
    product.max_per_trip = max(payload.max_per_trip, 0.0)
    product.price = max(payload.price, 0.0)

    db.commit()
    db.refresh(product)
    return {"id": product.id}


# === Заказы (admin-only) =====================================================

@router.get("/admin/orders")
async def admin_list_orders(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    orders = db.query(Order).order_by(Order.created_at.desc()).limit(200).all()
    return [
        {
            "id": o.id,
            "status": o.status.value if hasattr(o.status, "value") else o.status,
            "createdAt": o.created_at.isoformat() if o.created_at else None,
            "updatedAt": o.updated_at.isoformat() if o.updated_at else None,
            "warningText": o.warning_text,
            "needsLogisticsCheck": bool(o.needs_logistics_check),
            "selectedVariant": o.selected_variant,
            "manualTransportName": o.manual_transport_name,
            "createdBy": (o.created_by.username if o.created_by else None),
            # decision/accepted/last action are derived from events (best effort; ok to be None)
            **_derive_order_meta(
                db.query(OrderEvent)
                .filter(OrderEvent.order_id == o.id)
                .order_by(OrderEvent.created_at.asc())
                .all()
            ),
        }
        for o in orders
    ]


@router.get("/admin/orders/{order_id}")
async def admin_get_order(
    order_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    o = db.query(Order).filter(Order.id == order_id).first()
    if not o:
        raise HTTPException(status_code=404, detail="Заказ не найден")

    events = (
        db.query(OrderEvent)
        .filter(OrderEvent.order_id == order_id)
        .order_by(OrderEvent.created_at.asc())
        .all()
    )

    return {
        "id": o.id,
        "status": o.status.value if hasattr(o.status, "value") else o.status,
        "createdAt": o.created_at.isoformat() if o.created_at else None,
        "updatedAt": o.updated_at.isoformat() if o.updated_at else None,
        "warningText": o.warning_text,
        "needsLogisticsCheck": bool(o.needs_logistics_check),
        "selectedVariant": o.selected_variant,
        "request": o.request_payload,
        "variants": o.variants_snapshot,
        "selectedVariantSnapshot": o.selected_variant_snapshot,
        "manualTransportName": o.manual_transport_name,
        "manualNotes": o.manual_notes,
        "manualPayload": o.manual_payload,
        "createdBy": (o.created_by.username if o.created_by else None),
        **_derive_order_meta(events),
        "events": [
            {
                "id": e.id,
                "type": e.event_type,
                "createdAt": e.created_at.isoformat() if e.created_at else None,
                "user": (e.user.username if e.user else None),
                "payload": e.payload,
            }
            for e in events
        ],
    }


@router.post("/admin/orders/confirm")
async def admin_confirm_order_from_quote(
    payload: OrderCreateFromQuote,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    idx = payload.selectedVariant
    if idx < 0 or idx >= len(payload.variants):
        raise HTTPException(status_code=400, detail="selectedVariant вне диапазона variants")

    order = Order(
        status=OrderStatus.CONFIRMED_AUTO,
        request_payload=payload.request,
        variants_snapshot=payload.variants,
        selected_variant=idx,
        selected_variant_snapshot=payload.variants[idx],
        needs_logistics_check=bool(payload.needsLogisticsCheck),
        warning_text=payload.warningText,
        created_by_user_id=current_user.id,
    )
    db.add(order)
    db.flush()

    db.add(
        OrderEvent(
            order_id=order.id,
            event_type="confirmed_auto",
            payload={"selectedVariant": idx},
            user_id=current_user.id,
        )
    )

    _enforce_orders_limit(db, MAX_ORDERS_TO_KEEP)
    db.commit()
    db.refresh(order)
    return {"id": order.id, "status": order.status.value}


@router.post("/admin/orders/reject")
async def admin_reject_order_for_manual(
    payload: OrderCreateFromQuote,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    # В rejected состоянии selectedVariant может быть любым (для ориентира)
    idx = payload.selectedVariant
    selected_snapshot = payload.variants[idx] if (0 <= idx < len(payload.variants)) else None

    order = Order(
        status=OrderStatus.REJECTED_FOR_MANUAL,
        request_payload=payload.request,
        variants_snapshot=payload.variants,
        selected_variant=idx,
        selected_variant_snapshot=selected_snapshot,
        needs_logistics_check=bool(payload.needsLogisticsCheck),
        warning_text=payload.warningText,
        created_by_user_id=current_user.id,
    )
    db.add(order)
    db.flush()

    db.add(
        OrderEvent(
            order_id=order.id,
            event_type="rejected_for_manual",
            payload={"selectedVariant": idx},
            user_id=current_user.id,
        )
    )

    _enforce_orders_limit(db, MAX_ORDERS_TO_KEEP)
    db.commit()
    db.refresh(order)
    return {"id": order.id, "status": order.status.value}


@router.post("/admin/orders/{order_id}/manual_confirm")
async def admin_manual_confirm_order(
    order_id: int,
    decision: ManualDecision,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Заказ не найден")

    order.status = OrderStatus.CONFIRMED_MANUAL
    order.manual_transport_name = decision.transportName.strip()
    order.manual_notes = (decision.notes or "").strip() or None
    order.manual_payload = decision.payload or {}
    db.add(order)

    db.add(
        OrderEvent(
            order_id=order.id,
            event_type="confirmed_manual",
            payload={"transportName": order.manual_transport_name, "payload": order.manual_payload},
            user_id=current_user.id,
        )
    )
    db.commit()
    db.refresh(order)
    return {"id": order.id, "status": order.status.value}


@router.post("/admin/orders/{order_id}/approve")
async def admin_approve_order(
    order_id: int,
    decision: OrderDecision,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Заказ не найден")

    db.add(
        OrderEvent(
            order_id=order.id,
            event_type="approved",
            payload={"notes": (decision.notes or "").strip() or None, **(decision.payload or {})},
            user_id=current_user.id,
        )
    )
    db.commit()
    return {"id": order.id, "decision": "approved"}


@router.post("/admin/orders/{order_id}/decline")
async def admin_decline_order(
    order_id: int,
    decision: OrderDecision,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Заказ не найден")

    db.add(
        OrderEvent(
            order_id=order.id,
            event_type="declined",
            payload={"notes": (decision.notes or "").strip() or None, **(decision.payload or {})},
            user_id=current_user.id,
        )
    )
    db.commit()
    return {"id": order.id, "decision": "declined"}
