import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..core.logger import get_logger
from ..core.database import get_db
from ..core.auth import require_admin
from ..core.db_migration import ensure_catalog_normalization, ensure_tariffs_schema
from ..models.db_models import Category, Factory, Order, OrderEvent, OrderStatus, Product, Tariff, TariffChangeLog, User
from ..core.data_loader import (
    load_factories_from_google,
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
    🔄 Перезагрузка factories (товары/заводы) из Google Sheets в БД.

    ВАЖНО: тарифы (машины) больше не читаются из Google Sheets.
    """
    try:
        ensure_catalog_normalization(db)
        ensure_tariffs_schema(db)
        log.info("Запуск обновления factories из Google Sheets...")
        factories = load_factories_from_google(db)
        tariffs_count = db.query(Tariff).count()

        return JSONResponse(
            content={
                "factories_count": len(factories),
                "tariffs_count": tariffs_count,
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
        ensure_tariffs_schema(db)
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
    # Исторический эндпоинт — теперь тарифы редактируются в админке сайта.
    raise HTTPException(status_code=410, detail="Тарифы больше не загружаются из Google Sheets. Используйте /admin/tariffs.")


# === Будущее редактирование каталога (валидация на уровне API) ===============

class CategoryUpsert(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class ProductUpsert(BaseModel):
    factory_id: int
    category_id: int
    subtype: str = Field(..., min_length=1, max_length=255)
    weight_per_item: float = 0.0
    # DEPRECATED: больше не используем в расчёте (оставлено для обратной совместимости)
    special_threshold: float = 0.0
    # DEPRECATED: больше не используем в расчёте (оставлено для обратной совместимости)
    max_per_trip: float = 0.0
    price: float = 0.0


class TariffUpsert(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    capacity: float = Field(..., ge=0.0)
    tag: str = Field(..., pattern="^(container_carrier|long_haul|flatbed|manipulator|crane)$")

    # Весовое условие (новый формат)
    weight_condition: str = Field("any", pattern="^(any|le|gt)$")
    weight_threshold: float | None = Field(None, ge=0.0)

    # Диапазон дистанции
    min_distance: float = Field(0.0, ge=0.0)
    max_distance: float = Field(0.0, ge=0.0)

    # Цена в диапазоне + цена за км после max_distance (если это “последний” диапазон)
    base: float = Field(..., ge=0.0)
    per_km: float = Field(0.0, ge=0.0)

    # Ограничение по радиусу
    radius_limit_km: float | None = Field(None, ge=0.0)
    radius_center_lat: float | None = None
    radius_center_lon: float | None = None

    # Разделение на доставку/разгрузку
    service_type: str = Field("delivery", pattern="^(delivery|unloading)$")

    # Самозагрузка
    self_loading: bool = False

    # Возможность разгрузки (multi)
    unload_tags: list[str] = Field(default_factory=list)
    # legacy single-field (если кто-то ещё шлёт старый payload)
    unload_capability: str = Field("none", pattern="^(none|crane|manipulator)$")

    is_active: bool = True
    description: str | None = None
    notes: str | None = None


class DeliveryRangeUpsert(BaseModel):
    min_distance: float = Field(0.0, ge=0.0)
    max_distance: float = Field(0.0, ge=0.0)
    base: float = Field(..., ge=0.0)


class WeightBlockUpsert(BaseModel):
    weight_condition: str = Field("any", pattern="^(any|le|gt)$")
    weight_threshold: float | None = Field(None, ge=0.0)
    per_km: float = Field(0.0, ge=0.0)  # общий per_km для всех диапазонов доставки
    delivery_ranges: list[DeliveryRangeUpsert] = Field(default_factory=list)
    unloading_price: float | None = Field(None, ge=0.0)  # фикс цена разгрузки (если включено)


class TransportCardUpsert(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    capacity: float = Field(..., ge=0.0)
    tag: str = Field(..., pattern="^(container_carrier|long_haul|flatbed|manipulator|crane)$")

    # радиус
    radius_limit_km: float | None = Field(None, ge=0.0)
    radius_center_lat: float | None = None
    radius_center_lon: float | None = None

    unload_tags: list[str] = Field(default_factory=list)  # multi
    is_active: bool = True
    description: str | None = None
    notes: str | None = None

    enable_delivery: bool = True
    enable_unloading: bool = False

    weight_blocks: list[WeightBlockUpsert] = Field(default_factory=list)


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


# === Тарифы/машины (admin-only) ==============================================

def _tariff_to_dict(t: Tariff) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "capacity": t.capacity,
        "tag": t.tag,
        "weight_condition": t.weight_condition,
        "weight_threshold": t.weight_threshold,
        "min_distance": t.min_distance,
        "max_distance": t.max_distance,
        "base": t.base,
        "per_km": t.per_km,
        "radius_limit_km": t.radius_limit_km,
        "radius_center_lat": getattr(t, "radius_center_lat", None),
        "radius_center_lon": getattr(t, "radius_center_lon", None),
        "service_type": t.service_type,
        "self_loading": bool(t.self_loading),
        "unload_capability": t.unload_capability,
        "unload_tags": getattr(t, "unload_tags", None),
        "is_active": bool(t.is_active),
        "description": t.description,
        "notes": t.notes,
        "createdAt": t.created_at.isoformat() if getattr(t, "created_at", None) else None,
        "updatedAt": t.updated_at.isoformat() if getattr(t, "updated_at", None) else None,
        "createdBy": (t.created_by.username if getattr(t, "created_by", None) else None),
        "updatedBy": (t.updated_by.username if getattr(t, "updated_by", None) else None),
        # legacy, чтобы старый фронт не ломался
        "название": t.name,
        "грузоподъёмность": t.capacity,
        "weight_if": t.weight_if,
        "описание": t.description or "",
        "заметки": t.notes or "",
    }


def _tariff_snapshot(t: Tariff) -> dict:
    """Снимок тарифа для аудит-логов (без legacy дублей)."""
    return {
        "id": t.id,
        "name": t.name,
        "capacity": t.capacity,
        "tag": t.tag,
        "weight_condition": t.weight_condition,
        "weight_threshold": t.weight_threshold,
        "min_distance": t.min_distance,
        "max_distance": t.max_distance,
        "base": t.base,
        "per_km": t.per_km,
        "radius_limit_km": t.radius_limit_km,
        "radius_center_lat": getattr(t, "radius_center_lat", None),
        "radius_center_lon": getattr(t, "radius_center_lon", None),
        "service_type": t.service_type,
        "self_loading": bool(t.self_loading),
        "unload_capability": t.unload_capability,
        "unload_tags": getattr(t, "unload_tags", None),
        "is_active": bool(t.is_active),
        "description": t.description,
        "notes": t.notes,
    }


@router.get("/admin/tariffs")
async def admin_list_tariffs(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    ensure_tariffs_schema(db)
    tariffs = db.query(Tariff).order_by(Tariff.name.asc(), Tariff.min_distance.asc(), Tariff.max_distance.asc()).all()
    return [_tariff_to_dict(t) for t in tariffs]


@router.post("/admin/tariffs")
async def admin_create_tariff(
    payload: TariffUpsert,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    ensure_tariffs_schema(db)

    if payload.weight_condition != "any" and payload.weight_threshold is None:
        raise HTTPException(status_code=400, detail="weight_threshold обязателен, если weight_condition != any")

    allowed_unload = {"crane", "manipulator", "self"}
    unload_tags = [str(x).strip().lower() for x in (payload.unload_tags or []) if str(x).strip()]
    unload_tags = [x for x in unload_tags if x in allowed_unload]
    # legacy fallback
    if not unload_tags and payload.unload_capability in allowed_unload:
        unload_tags = [payload.unload_capability]

    t = Tariff(
        name=payload.name.strip(),
        capacity=float(payload.capacity),
        tag=payload.tag.strip().lower(),
        weight_condition=payload.weight_condition,
        weight_threshold=payload.weight_threshold,
        # legacy weight_if — заполняем для совместимости и читаемости
        weight_if="any" if payload.weight_condition == "any" else (f"≤{payload.weight_threshold}" if payload.weight_condition == "le" else f">{payload.weight_threshold}"),
        min_distance=float(payload.min_distance),
        max_distance=float(payload.max_distance),
        base=float(payload.base),
        per_km=float(payload.per_km),
        radius_limit_km=payload.radius_limit_km,
        radius_center_lat=payload.radius_center_lat,
        radius_center_lon=payload.radius_center_lon,
        service_type=payload.service_type,
        self_loading=bool(payload.self_loading),
        unload_capability=(unload_tags[0] if unload_tags else "none"),
        unload_tags=(unload_tags or None),
        is_active=bool(payload.is_active),
        description=(payload.description or "").strip() or None,
        notes=(payload.notes or "").strip() or None,
        created_by_user_id=current_user.id,
        updated_by_user_id=current_user.id,
    )
    db.add(t)
    db.commit()
    db.refresh(t)

    db.add(
        TariffChangeLog(
            tariff_id=t.id,
            tariff_name=t.name,
            action="create",
            before=None,
            after=_tariff_snapshot(t),
            user_id=current_user.id,
        )
    )
    db.commit()
    return _tariff_to_dict(t)


@router.put("/admin/tariffs/{tariff_id}")
async def admin_update_tariff(
    tariff_id: int,
    payload: TariffUpsert,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    allowed_unload = {"crane", "manipulator", "self"}
    unload_tags = [str(x).strip().lower() for x in (payload.unload_tags or []) if str(x).strip()]
    unload_tags = [x for x in unload_tags if x in allowed_unload]
    if not unload_tags and payload.unload_capability in allowed_unload:
        unload_tags = [payload.unload_capability]

    ensure_tariffs_schema(db)
    t = db.query(Tariff).filter(Tariff.id == tariff_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Тариф не найден")

    before = _tariff_snapshot(t)

    if payload.weight_condition != "any" and payload.weight_threshold is None:
        raise HTTPException(status_code=400, detail="weight_threshold обязателен, если weight_condition != any")

    t.name = payload.name.strip()
    t.capacity = float(payload.capacity)
    t.tag = payload.tag.strip().lower()
    t.weight_condition = payload.weight_condition
    t.weight_threshold = payload.weight_threshold
    t.weight_if = "any" if payload.weight_condition == "any" else (f"≤{payload.weight_threshold}" if payload.weight_condition == "le" else f">{payload.weight_threshold}")
    t.min_distance = float(payload.min_distance)
    t.max_distance = float(payload.max_distance)
    t.base = float(payload.base)
    t.per_km = float(payload.per_km)
    t.radius_limit_km = payload.radius_limit_km
    t.radius_center_lat = payload.radius_center_lat
    t.radius_center_lon = payload.radius_center_lon
    t.service_type = payload.service_type
    t.self_loading = bool(payload.self_loading)
    t.unload_capability = (unload_tags[0] if unload_tags else "none")
    t.unload_tags = (unload_tags or None)
    t.is_active = bool(payload.is_active)
    t.description = (payload.description or "").strip() or None
    t.notes = (payload.notes or "").strip() or None
    t.updated_by_user_id = current_user.id

    db.commit()
    db.refresh(t)

    db.add(
        TariffChangeLog(
            tariff_id=t.id,
            tariff_name=t.name,
            action="update",
            before=before,
            after=_tariff_snapshot(t),
            user_id=current_user.id,
        )
    )
    db.commit()
    return _tariff_to_dict(t)


@router.delete("/admin/tariffs/{tariff_id}")
async def admin_delete_tariff(
    tariff_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    ensure_tariffs_schema(db)
    t = db.query(Tariff).filter(Tariff.id == tariff_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Тариф не найден")

    before = _tariff_snapshot(t)
    db.add(
        TariffChangeLog(
            tariff_id=t.id,
            tariff_name=t.name,
            action="delete",
            before=before,
            after=None,
            user_id=current_user.id,
        )
    )
    db.commit()
    db.delete(t)
    db.commit()
    return {"status": "ok"}


@router.get("/admin/tariffs/audit")
async def admin_tariffs_audit(
    limit: int = 200,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    ensure_tariffs_schema(db)
    limit = max(1, min(int(limit or 200), 500))
    rows = (
        db.query(TariffChangeLog)
        .order_by(TariffChangeLog.created_at.desc(), TariffChangeLog.id.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "action": r.action,
            "tariffId": r.tariff_id,
            "tariffName": r.tariff_name,
            "user": ({"id": r.user.id, "username": r.user.username} if r.user else None),
            "createdAt": (r.created_at.isoformat() if r.created_at else None),
            "before": r.before,
            "after": r.after,
        }
        for r in rows
    ]


@router.post("/admin/transports/upsert")
async def admin_upsert_transport_card(
    payload: TransportCardUpsert,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Пакетное сохранение "карточки транспорта":
    - общие поля (name/capacity/tag/радиус/теги разгрузки/активность/описание/заметки)
    - 1-2 весовых условия, каждое со своими диапазонами доставки и (опционально) ценой разгрузки
    """
    ensure_tariffs_schema(db)

    name = payload.name.strip()
    tag = payload.tag.strip().lower()

    if payload.radius_limit_km and (payload.radius_limit_km or 0) > 0:
        if payload.radius_center_lat is None or payload.radius_center_lon is None:
            raise HTTPException(status_code=400, detail="Для radius_limit_km нужно указать radius_center_lat/lon")

    allowed_unload = {"crane", "manipulator", "self"}
    unload_tags = [str(x).strip().lower() for x in (payload.unload_tags or []) if str(x).strip()]
    unload_tags = [x for x in unload_tags if x in allowed_unload]
    unload_capability = (unload_tags[0] if unload_tags else "none")

    blocks = payload.weight_blocks or []
    if not blocks:
        # по умолчанию одно "any" условие
        blocks = [WeightBlockUpsert()]

    # validate blocks
    if payload.enable_delivery:
        for b in blocks:
            if b.weight_condition != "any" and b.weight_threshold is None:
                raise HTTPException(status_code=400, detail="weight_threshold обязателен для le/gt")
            if not (b.delivery_ranges or []):
                raise HTTPException(status_code=400, detail="Нужно добавить хотя бы один диапазон доставки")

    # before snapshot for audit
    existing = db.query(Tariff).filter(Tariff.name == name, Tariff.tag == tag).all()
    before = [_tariff_snapshot(t) for t in existing]

    # delete existing rows
    if existing:
        for t in existing:
            db.delete(t)
        db.commit()

    created_rows: list[Tariff] = []

    def _legacy_weight_if(cond: str, thr: float | None) -> str:
        if cond == "any":
            return "any"
        if cond == "le":
            return f"≤{thr}"
        if cond == "gt":
            return f">{thr}"
        return "any"

    for b in blocks:
        cond = (b.weight_condition or "any").strip().lower()
        thr = b.weight_threshold

        # delivery rows
        if payload.enable_delivery:
            for dr in (b.delivery_ranges or []):
                t = Tariff(
                    name=name,
                    capacity=float(payload.capacity),
                    tag=tag,
                    weight_condition=cond,
                    weight_threshold=thr,
                    weight_if=_legacy_weight_if(cond, thr),
                    min_distance=float(dr.min_distance),
                    max_distance=float(dr.max_distance),
                    base=float(dr.base),
                    per_km=float(b.per_km or 0.0),
                    radius_limit_km=payload.radius_limit_km,
                    radius_center_lat=payload.radius_center_lat,
                    radius_center_lon=payload.radius_center_lon,
                    service_type="delivery",
                    self_loading=False,
                    unload_capability=unload_capability,
                    unload_tags=(unload_tags or None),
                    is_active=bool(payload.is_active),
                    description=(payload.description or "").strip() or None,
                    notes=(payload.notes or "").strip() or None,
                    created_by_user_id=current_user.id,
                    updated_by_user_id=current_user.id,
                )
                db.add(t)
                created_rows.append(t)

        # unloading row (fixed)
        if payload.enable_unloading and b.unloading_price and (b.unloading_price or 0) > 0:
            t = Tariff(
                name=name,
                capacity=float(payload.capacity),
                tag=tag,
                weight_condition=cond,
                weight_threshold=thr,
                weight_if=_legacy_weight_if(cond, thr),
                min_distance=0.0,
                max_distance=0.0,
                base=float(b.unloading_price),
                per_km=0.0,
                radius_limit_km=payload.radius_limit_km,
                radius_center_lat=payload.radius_center_lat,
                radius_center_lon=payload.radius_center_lon,
                service_type="unloading",
                self_loading=False,
                unload_capability=unload_capability,
                unload_tags=(unload_tags or None),
                is_active=bool(payload.is_active),
                description=(payload.description or "").strip() or None,
                notes=(payload.notes or "").strip() or None,
                created_by_user_id=current_user.id,
                updated_by_user_id=current_user.id,
            )
            db.add(t)
            created_rows.append(t)

    db.commit()

    after_rows = db.query(Tariff).filter(Tariff.name == name, Tariff.tag == tag).all()
    after = [_tariff_snapshot(t) for t in after_rows]

    db.add(
        TariffChangeLog(
            tariff_id=None,
            tariff_name=name,
            action="bulk_upsert",
            before=before,
            after=after,
            user_id=current_user.id,
        )
    )
    db.commit()

    return [_tariff_to_dict(t) for t in after_rows]


@router.delete("/admin/transports")
async def admin_delete_transport(
    name: str,
    tag: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    ensure_tariffs_schema(db)
    nm = (name or "").strip()
    tg = (tag or "").strip().lower()
    if not nm or not tg:
        raise HTTPException(status_code=400, detail="name и tag обязательны")

    rows = db.query(Tariff).filter(Tariff.name == nm, Tariff.tag == tg).all()
    if not rows:
        return {"status": "ok", "deleted": 0}

    before = [_tariff_snapshot(t) for t in rows]
    deleted = 0
    for t in rows:
        db.delete(t)
        deleted += 1
    db.commit()

    db.add(
        TariffChangeLog(
            tariff_id=None,
            tariff_name=nm,
            action="bulk_delete",
            before=before,
            after=None,
            user_id=current_user.id,
        )
    )
    db.commit()
    return {"status": "ok", "deleted": deleted}


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
