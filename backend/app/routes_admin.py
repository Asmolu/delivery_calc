import json
import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from types import SimpleNamespace

from ..core.logger import get_logger
from ..core.database import get_db
from ..core.auth import verify_password
from ..core.rbac import get_user_org_role, org_role_rank, require_org_min
from ..core.db_migration import ensure_catalog_normalization, ensure_tariffs_schema
from ..models.db_models import (
    Category,
    Factory,
    Order,
    OrderEvent,
    OrderStatus,
    OrgRole,
    Organization,
    OrganizationInvite,
    OrganizationMember,
    Product,
    Tariff,
    TariffChangeLog,
    User,
)
from ..core.data_loader import (
    load_factories_from_google,
    load_factories_and_tariffs,
)
from ..core.geo_zones import list_zone_ids, normalize_zone_id
from ..service.transport_calc import (
    evaluate_scenario_transport,
    build_shipment_details_from_result,
    build_trip_items_details,
    _build_group_max_distance,
    _distance_matches_tariff,
    _trip_cost,
    _weight_ok,
    _tariff_label,
)

router = APIRouter()
log = get_logger("routes.admin")

MAX_ORDERS_TO_KEEP = 100


def _default_org(db: Session) -> Organization:
    """Single-tenant fallback: используем org по умолчанию (создаётся на startup)."""
    name = os.getenv("DEFAULT_ORG_NAME", "Default")
    org = db.query(Organization).filter(Organization.name == name).first()
    if org:
        return org
    # fallback: первая организация
    org = db.query(Organization).order_by(Organization.id.asc()).first()
    if not org:
        raise HTTPException(status_code=500, detail="Организация не инициализирована")
    return org


def _hash_invite_token(raw_token: str) -> str:
    salt = os.getenv("INVITE_TOKEN_SALT", "invite-salt-change-me")
    return hashlib.sha256((salt + "::" + (raw_token or "")).encode("utf-8")).hexdigest()


def _invite_url(raw_token: str) -> str:
    public_base = os.getenv("PUBLIC_APP_BASE_URL", "http://localhost:5173").rstrip("/")
    return f"{public_base}/invite/{raw_token}"


# === Users / Invites (org-scoped RBAC) =======================================

class InviteCreate(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    role: OrgRole = OrgRole.MANAGER
    expires_days: int = Field(7, ge=1, le=30)


class OrgMemberUpdate(BaseModel):
    # membership
    orgRole: OrgRole | None = None
    isActive: bool | None = None
    # user profile
    firstName: str | None = None
    lastName: str | None = None
    userIsActive: bool | None = None


@router.get("/admin/org")
async def admin_get_org(
    current_user: User = Depends(require_org_min(OrgRole.ADMIN)),
    db: Session = Depends(get_db),
):
    org = _default_org(db)
    members_count = db.query(OrganizationMember).filter(OrganizationMember.organization_id == org.id).count()
    invites_count = (
        db.query(OrganizationInvite)
        .filter(
            OrganizationInvite.organization_id == org.id,
            OrganizationInvite.revoked_at.is_(None),
            OrganizationInvite.accepted_at.is_(None),
        )
        .count()
    )
    return {
        "id": org.id,
        "name": org.name,
        "is_active": org.is_active,
        "membersCount": members_count,
        "invitesCount": invites_count,
    }


@router.get("/admin/org/members")
async def admin_list_org_members(
    current_user: User = Depends(require_org_min(OrgRole.ADMIN)),
    db: Session = Depends(get_db),
):
    org = _default_org(db)
    rows = (
        db.query(OrganizationMember)
        .filter(OrganizationMember.organization_id == org.id)
        .order_by(OrganizationMember.id.asc())
        .all()
    )
    out = []
    for m in rows:
        u = m.user
        out.append(
            {
                "id": m.id,
                "userId": m.user_id,
                "username": u.username if u else None,
                "email": u.email if u else None,
                "firstName": (getattr(u, "first_name", None) if u else None),
                "lastName": (getattr(u, "last_name", None) if u else None),
                "userIsActive": (bool(getattr(u, "is_active", True)) if u else False),
                "orgRole": (m.role.value if hasattr(m.role, "value") else m.role),
                "isActive": bool(m.is_active),
                "createdAt": (m.created_at.isoformat() if getattr(m, "created_at", None) else None),
            }
        )
    return out


@router.put("/admin/org/members/{member_id}")
async def admin_update_org_member(
    member_id: int,
    payload: OrgMemberUpdate,
    current_user: User = Depends(require_org_min(OrgRole.OWNER)),
    db: Session = Depends(get_db),
):
    """Owner-only: управление пользователями (роль/активность + имя/фамилия)."""
    org = _default_org(db)
    m = (
        db.query(OrganizationMember)
        .filter(OrganizationMember.id == member_id, OrganizationMember.organization_id == org.id)
        .first()
    )
    if not m:
        raise HTTPException(status_code=404, detail="Участник не найден")

    u = m.user
    if not u:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    # предотвратим потерю последнего OWNER
    if payload.orgRole and payload.orgRole != OrgRole.OWNER:
        owners = (
            db.query(OrganizationMember)
            .filter(
                OrganizationMember.organization_id == org.id,
                OrganizationMember.role == OrgRole.OWNER,
                OrganizationMember.is_active.is_(True),
                OrganizationMember.id != m.id,
            )
            .count()
        )
        if owners <= 0:
            raise HTTPException(status_code=400, detail="Нельзя убрать роль OWNER у единственного владельца")

    if payload.isActive is not None:
        # если отключаем единственного OWNER — тоже запрещаем
        if (payload.isActive is False) and (m.role == OrgRole.OWNER):
            owners = (
                db.query(OrganizationMember)
                .filter(
                    OrganizationMember.organization_id == org.id,
                    OrganizationMember.role == OrgRole.OWNER,
                    OrganizationMember.is_active.is_(True),
                    OrganizationMember.id != m.id,
                )
                .count()
            )
            if owners <= 0:
                raise HTTPException(status_code=400, detail="Нельзя отключить единственного владельца")
        m.is_active = bool(payload.isActive)

    if payload.orgRole is not None:
        m.role = payload.orgRole

    if payload.firstName is not None:
        u.first_name = (payload.firstName or "").strip() or None
    if payload.lastName is not None:
        u.last_name = (payload.lastName or "").strip() or None
    if payload.userIsActive is not None:
        u.is_active = bool(payload.userIsActive)

    db.add(m)
    db.add(u)
    db.commit()

    return {"status": "ok", "memberId": m.id}


@router.get("/admin/org/invites")
async def admin_list_org_invites(
    current_user: User = Depends(require_org_min(OrgRole.ADMIN)),
    db: Session = Depends(get_db),
):
    org = _default_org(db)
    rows = (
        db.query(OrganizationInvite)
        .filter(OrganizationInvite.organization_id == org.id)
        .order_by(OrganizationInvite.id.desc())
        .limit(200)
        .all()
    )
    out = []
    for inv in rows:
        out.append(
            {
                "id": inv.id,
                "email": inv.email,
                "role": (inv.role.value if hasattr(inv.role, "value") else inv.role),
                "expiresAt": (inv.expires_at.isoformat() if inv.expires_at else None),
                "revokedAt": (inv.revoked_at.isoformat() if inv.revoked_at else None),
                "acceptedAt": (inv.accepted_at.isoformat() if inv.accepted_at else None),
                "createdAt": (inv.created_at.isoformat() if inv.created_at else None),
                "createdBy": (inv.created_by.username if inv.created_by else None),
            }
        )
    return out


@router.post("/admin/org/invites")
async def admin_create_org_invite(
    payload: InviteCreate,
    current_user: User = Depends(require_org_min(OrgRole.ADMIN)),
    db: Session = Depends(get_db),
):
    org = _default_org(db)
    email = (payload.email or "").strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=400, detail="Некорректный email")

    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_invite_token(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(days=int(payload.expires_days or 7))

    inv = OrganizationInvite(
        organization_id=org.id,
        email=email,
        role=payload.role,
        token_hash=token_hash,
        created_by_user_id=current_user.id,
        expires_at=expires_at,
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return {
        "id": inv.id,
        "email": inv.email,
        "role": (inv.role.value if hasattr(inv.role, "value") else inv.role),
        "expiresAt": inv.expires_at.isoformat() if inv.expires_at else None,
        "inviteUrl": _invite_url(raw_token),
        # raw token intentionally returned so admin can copy link
        "token": raw_token,
    }


@router.post("/admin/org/invites/{invite_id}/revoke")
async def admin_revoke_org_invite(
    invite_id: int,
    current_user: User = Depends(require_org_min(OrgRole.ADMIN)),
    db: Session = Depends(get_db),
):
    org = _default_org(db)
    inv = (
        db.query(OrganizationInvite)
        .filter(OrganizationInvite.id == invite_id, OrganizationInvite.organization_id == org.id)
        .first()
    )
    if not inv:
        raise HTTPException(status_code=404, detail="Инвайт не найден")
    if inv.accepted_at:
        raise HTTPException(status_code=400, detail="Инвайт уже принят")
    if inv.revoked_at:
        return {"status": "ok", "revoked": False}
    inv.revoked_at = datetime.now(timezone.utc)
    db.add(inv)
    db.commit()
    return {"status": "ok", "revoked": True}


@router.post("/admin/reload")
async def admin_reload(
    current_user: User = Depends(require_org_min(OrgRole.LOGIST)),
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
    current_user: User = Depends(require_org_min(OrgRole.LOGIST)),
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
    current_user: User = Depends(require_org_min(OrgRole.LOGIST)),
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
    is_active: bool = True


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

    # Геозоны
    load_zone: str | None = None
    unload_zone: str | None = None

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

    # Контейнеровоз: привязка к базовой шаландe (или другому транспорту), от которого берётся цена
    base_transport_name: str | None = None
    base_transport_tag: str | None = None

    # Геозоны
    load_zone: str | None = None
    unload_zone: str | None = None

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

class AdminPasswordCheck(BaseModel):
    password: str = Field(..., min_length=1, max_length=255)


class ActiveToggle(BaseModel):
    is_active: bool = True


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


def _norm_str_local(x) -> str:
    return str(x or "").strip()


def _manual_selected_names(manual: dict, field_list: str, field_legacy: str) -> list[str]:
    """Извлекает выбранные имена машин из manual payload."""
    arr = manual.get(field_list, None)
    if isinstance(arr, list):
        out = [_norm_str_local(v) for v in arr if _norm_str_local(v)]
        return out
    legacy = _norm_str_local(manual.get(field_legacy, ""))
    if legacy:
        # legacy строка может быть "A + B + C"
        parts = [p.strip() for p in legacy.split("+")]
        out = [p for p in parts if p]
        return out
    return []


def _build_manual_scenario_from_order(db: Session, order: Order, manual: dict) -> dict:
    """Строит scenario dict для evaluate_scenario_transport на базе ручного выбора заводов."""
    items = manual.get("items") if isinstance(manual, dict) else None
    if not isinstance(items, list) or not items:
        raise HTTPException(status_code=400, detail="manual.items отсутствует или пуст")

    factories_map: dict[str, list[dict]] = {}
    total_material_cost = 0.0
    total_weight = 0.0

    for it in items:
        if not isinstance(it, dict):
            continue
        category = _norm_str_local(it.get("category"))
        subtype = _norm_str_local(it.get("subtype"))
        qty = int(it.get("quantity") or 0)
        factory_name = _norm_str_local(it.get("factoryName"))
        if not category or not subtype or qty <= 0 or not factory_name:
            continue

        # найти Product по (factory, category, subtype)
        prod = (
            db.query(Product)
            .join(Factory, Product.factory_id == Factory.id)
            .join(Category, Product.category_id == Category.id)
            .filter(Factory.name == factory_name, Category.name == category, Product.subtype == subtype)
            .first()
        )
        if not prod:
            # fallback на legacy поле category
            prod = (
                db.query(Product)
                .join(Factory, Product.factory_id == Factory.id)
                .filter(Factory.name == factory_name, Product.category == category, Product.subtype == subtype)
                .first()
            )
        if not prod:
            raise HTTPException(
                status_code=400,
                detail=f"Не найден товар в БД для {category}/{subtype} на заводе '{factory_name}'",
            )

        f = prod.factory
        if not f or f.lat is None or f.lon is None:
            raise HTTPException(status_code=400, detail=f"У завода '{factory_name}' нет координат")

        weight_per_item = float(prod.weight_per_item or 0.0)
        price_per_item = float(prod.price or 0.0)
        weight_total = weight_per_item * qty

        total_material_cost += price_per_item * qty
        total_weight += weight_total

        factories_map.setdefault(factory_name, []).append(
            {
                "factory": {
                    "name": f.name,
                    "lat": f.lat,
                    "lon": f.lon,
                    "contact": f.contact,
                    "price": price_per_item,
                },
                "category": category,
                "subtype": subtype,
                "quantity": qty,
                "price_per_item": price_per_item,
                "weight_per_item": weight_per_item,
                "lat": f.lat,
                "lon": f.lon,
                "weight_total": weight_total,
            }
        )

    if not factories_map:
        raise HTTPException(status_code=400, detail="Не удалось построить сценарий из manual.items")

    return {
        "scenario_id": 1,
        "factories": factories_map,
        "total_material_cost": total_material_cost,
        "total_weight": total_weight,
    }


def _filter_tariffs_for_manual_choice(tariffs: list[dict], manual: dict) -> list[dict]:
    """Ограничивает тарифы выбранными машинами (по названию) для delivery/unloading."""
    if not isinstance(tariffs, list) or not tariffs:
        return []

    delivery_names = set(_manual_selected_names(manual, "deliveryMachines", "deliveryMachineName"))
    unloading_names = set(_manual_selected_names(manual, "unloadingMachines", "unloadingMachineName"))

    out = []
    for t in tariffs:
        if not isinstance(t, dict):
            continue
        name = _norm_str_local(t.get("название") or t.get("name"))
        service_type = _norm_str_local(t.get("service_type") or "delivery").lower()

        if service_type == "delivery" and delivery_names:
            if name in delivery_names:
                out.append(t)
            continue
        if service_type == "unloading" and unloading_names:
            if name in unloading_names:
                out.append(t)
            continue
        out.append(t)
    return out


def _recalc_manual_order(db: Session, order: Order, manual: dict) -> dict:
    """Пересчитать заказ по ручному выбору и вернуть структуру для UI."""
    if not isinstance(order.request_payload, dict):
        raise HTTPException(status_code=400, detail="order.request_payload повреждён")

    req_payload = order.request_payload
    upload_lat = req_payload.get("upload_lat")
    upload_lon = req_payload.get("upload_lon")
    if upload_lat is None or upload_lon is None:
        raise HTTPException(status_code=400, detail="В заказе нет upload_lat/upload_lon для перерасчёта")

    # теги транспорта могут прийти из manual (приоритет), иначе из request_payload
    delivery_tag = _norm_str_local(manual.get("deliveryTransportTag") or req_payload.get("deliveryTransportTag") or "auto")
    unloading_tag = _norm_str_local(manual.get("unloadingTransportTag") or req_payload.get("unloadingTransportTag") or "auto")

    scenario = _build_manual_scenario_from_order(db, order, manual)
    _, tariffs = load_factories_and_tariffs(db)
    tariffs_filtered = _filter_tariffs_for_manual_choice(tariffs, manual)

    req = SimpleNamespace(
        upload_lat=float(upload_lat),
        upload_lon=float(upload_lon),
        transport_type=_norm_str_local(req_payload.get("transport_type") or "auto"),
        deliveryTransportTag=delivery_tag,
        unloadingTransportTag=unloading_tag,
        addManipulator=bool(req_payload.get("addManipulator") or req_payload.get("add_manipulator") or False),
    )

    result = evaluate_scenario_transport(scenario, req, tariffs_filtered)
    if not result:
        raise HTTPException(status_code=400, detail="Не удалось пересчитать сценарий по ручному выбору")

    details = build_shipment_details_from_result(result, req)
    trip_items = build_trip_items_details(result)
    return {
        "totalCost": round(float(result.get("total_cost") or 0.0), 2),
        "materialCost": round(float(result.get("material_sum") or 0.0), 2),
        "deliveryCost": round(float(result.get("delivery_cost") or 0.0), 2),
        "unloadingCost": round(float(result.get("unloading_cost") or 0.0), 2),
        "tripCount": int(result.get("trip_count") or 0),
        "transportName": result.get("transport_name") or "",
        "details": details,
        "tripItems": trip_items,
    }


def _refresh_tripitems_tariff_labels(trip_items: list, request_payload: dict, tariffs: list[dict]) -> list:
    """Для старых заказов: пересчитываем отображение тарифа/стоимости рейса по текущим тарифам."""
    if not isinstance(trip_items, list) or not trip_items:
        return trip_items
    if not isinstance(request_payload, dict):
        return trip_items
    if not isinstance(tariffs, list) or not tariffs:
        return trip_items

    upload_lat = request_payload.get("upload_lat")
    upload_lon = request_payload.get("upload_lon")
    dropoff_point = None
    try:
        ulat = float(upload_lat) if upload_lat is not None else None
        ulon = float(upload_lon) if upload_lon is not None else None
        if ulat is not None and ulon is not None:
            dropoff_point = (ulat, ulon)
    except Exception:
        dropoff_point = None

    group_max_distance = _build_group_max_distance(tariffs)

    refreshed = []
    for row in trip_items:
        if not isinstance(row, dict):
            refreshed.append(row)
            continue

        machine_name = _norm_str_local(row.get("машина"))
        distance_km = float(row.get("расстояние_км") or 0.0)
        load_ton = float(row.get("загрузка_т") or 0.0)

        if not machine_name or distance_km <= 0:
            refreshed.append(row)
            continue

        candidates = []
        for t in tariffs:
            if not isinstance(t, dict):
                continue
            if _norm_str_local(t.get("service_type") or "delivery").lower() != "delivery":
                continue
            name = _norm_str_local(t.get("название") or t.get("name"))
            if name != machine_name:
                continue
            if not _distance_matches_tariff(t, distance_km, group_max_distance, None, dropoff_point):
                continue
            if not _weight_ok(t, load_ton):
                continue
            # capacity check (best effort)
            cap = float(t.get("грузоподъёмность") or 0.0)
            if cap and load_ton > cap + 1e-9:
                continue
            candidates.append(t)

        if not candidates:
            refreshed.append(row)
            continue

        best = min(candidates, key=lambda x: _trip_cost(x, distance_km))
        new_label = _tariff_label(best, distance_km=distance_km)
        new_cost = round(float(_trip_cost(best, distance_km)), 2)

        updated = {**row, "тариф": new_label, "стоимость_доставки": new_cost}
        refreshed.append(updated)

    return refreshed


@router.get("/admin/categories")
async def admin_list_categories(
    current_user: User = Depends(require_org_min(OrgRole.LOGIST)),
    db: Session = Depends(get_db),
):
    cats = db.query(Category).order_by(Category.name.asc()).all()
    return [{"id": c.id, "name": c.name} for c in cats]


@router.post("/admin/categories")
async def admin_create_category(
    payload: CategoryUpsert,
    current_user: User = Depends(require_org_min(OrgRole.LOGIST)),
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
    current_user: User = Depends(require_org_min(OrgRole.LOGIST)),
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
    current_user: User = Depends(require_org_min(OrgRole.LOGIST)),
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
        is_active=bool(payload.is_active),
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return {"id": product.id}


@router.put("/admin/products/{product_id}")
async def admin_update_product(
    product_id: int,
    payload: ProductUpsert,
    current_user: User = Depends(require_org_min(OrgRole.LOGIST)),
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
    product.is_active = bool(payload.is_active)

    db.commit()
    db.refresh(product)
    return {"id": product.id}


@router.get("/admin/factories")
async def admin_list_factories_catalog(
    current_user: User = Depends(require_org_min(OrgRole.LOGIST)),
    db: Session = Depends(get_db),
):
    """Список заводов и их товаров (включая неактивные) для админки."""
    ensure_catalog_normalization(db)
    factories = db.query(Factory).order_by(Factory.name.asc()).all()
    out = []
    for f in factories:
        products = (
            db.query(Product)
            .filter(Product.factory_id == f.id)
            .order_by(Product.subtype.asc())
            .all()
        )
        out.append(
            {
                "id": f.id,
                "name": f.name,
                "lat": f.lat,
                "lon": f.lon,
                "contact": f.contact,
                "is_active": bool(getattr(f, "is_active", True)),
                "products": [
                    {
                        "id": p.id,
                        "category": (p.category_rel.name if getattr(p, "category_rel", None) else None) or p.category,
                        "category_id": p.category_id,
                        "subtype": p.subtype,
                        "weight_per_item": p.weight_per_item,
                        "price": p.price,
                        "is_active": bool(getattr(p, "is_active", True)),
                    }
                    for p in products
                ],
            }
        )
    return out


@router.put("/admin/factories/{factory_id}/active")
async def admin_set_factory_active(
    factory_id: int,
    payload: ActiveToggle,
    current_user: User = Depends(require_org_min(OrgRole.LOGIST)),
    db: Session = Depends(get_db),
):
    ensure_catalog_normalization(db)
    f = db.query(Factory).filter(Factory.id == factory_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Завод не найден")

    next_active = bool(payload.is_active)
    f.is_active = next_active
    db.add(f)

    # Каскад: выключение завода выключает все его товары
    if not next_active:
        db.query(Product).filter(Product.factory_id == factory_id).update({"is_active": False})

    db.commit()
    return {"id": f.id, "is_active": bool(f.is_active)}


@router.put("/admin/products/{product_id}/active")
async def admin_set_product_active(
    product_id: int,
    payload: ActiveToggle,
    current_user: User = Depends(require_org_min(OrgRole.LOGIST)),
    db: Session = Depends(get_db),
):
    ensure_catalog_normalization(db)
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Товар не найден")

    p.is_active = bool(payload.is_active)
    db.add(p)
    db.commit()
    return {"id": p.id, "is_active": bool(p.is_active)}


# === Тарифы/машины (admin-only) ==============================================

def _tariff_to_dict(t: Tariff) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "capacity": t.capacity,
        "tag": t.tag,
        "base_transport_name": getattr(t, "base_transport_name", None),
        "base_transport_tag": getattr(t, "base_transport_tag", None),
        "weight_condition": t.weight_condition,
        "weight_threshold": t.weight_threshold,
        "min_distance": t.min_distance,
        "max_distance": t.max_distance,
        "base": t.base,
        "per_km": t.per_km,
        "load_zone": getattr(t, "load_zone", None),
        "unload_zone": getattr(t, "unload_zone", None),
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
        "base_transport_name": getattr(t, "base_transport_name", None),
        "base_transport_tag": getattr(t, "base_transport_tag", None),
        "weight_condition": t.weight_condition,
        "weight_threshold": t.weight_threshold,
        "min_distance": t.min_distance,
        "max_distance": t.max_distance,
        "base": t.base,
        "per_km": t.per_km,
        "load_zone": getattr(t, "load_zone", None),
        "unload_zone": getattr(t, "unload_zone", None),
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
    current_user: User = Depends(require_org_min(OrgRole.LOGIST)),
    db: Session = Depends(get_db),
):
    ensure_tariffs_schema(db)
    tariffs = db.query(Tariff).order_by(Tariff.name.asc(), Tariff.min_distance.asc(), Tariff.max_distance.asc()).all()
    return [_tariff_to_dict(t) for t in tariffs]


@router.post("/admin/tariffs")
async def admin_create_tariff(
    payload: TariffUpsert,
    current_user: User = Depends(require_org_min(OrgRole.LOGIST)),
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

    load_zone = normalize_zone_id(payload.load_zone)
    unload_zone = normalize_zone_id(payload.unload_zone)
    if payload.load_zone and load_zone is None:
        raise HTTPException(status_code=400, detail=f"Недопустимая load_zone. Доступно: {', '.join(list_zone_ids())}")
    if payload.unload_zone and unload_zone is None:
        raise HTTPException(status_code=400, detail=f"Недопустимая unload_zone. Доступно: {', '.join(list_zone_ids())}")

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
        load_zone=load_zone,
        unload_zone=unload_zone,
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
    current_user: User = Depends(require_org_min(OrgRole.LOGIST)),
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

    load_zone = normalize_zone_id(payload.load_zone)
    unload_zone = normalize_zone_id(payload.unload_zone)
    if payload.load_zone and load_zone is None:
        raise HTTPException(status_code=400, detail=f"Недопустимая load_zone. Доступно: {', '.join(list_zone_ids())}")
    if payload.unload_zone and unload_zone is None:
        raise HTTPException(status_code=400, detail=f"Недопустимая unload_zone. Доступно: {', '.join(list_zone_ids())}")

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
    t.load_zone = load_zone
    t.unload_zone = unload_zone
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
    password: str,
    current_user: User = Depends(require_org_min(OrgRole.ADMIN)),
    db: Session = Depends(get_db),
):
    # подтверждение паролем (как "подпись" опасной операции)
    if not verify_password(password or "", current_user.hashed_password):
        raise HTTPException(status_code=403, detail="Invalid admin password")

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
    current_user: User = Depends(require_org_min(OrgRole.ADMIN)),
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
    current_user: User = Depends(require_org_min(OrgRole.LOGIST)),
    db: Session = Depends(get_db),
):
    """Пакетное сохранение "карточки транспорта":
    - общие поля (name/capacity/tag/геозоны/теги разгрузки/активность/описание/заметки)
    - 1-2 весовых условия, каждое со своими диапазонами доставки и (опционально) ценой разгрузки
    """
    ensure_tariffs_schema(db)

    name = payload.name.strip()
    tag = payload.tag.strip().lower()
    base_name = (payload.base_transport_name or "").strip() or None
    base_tag = (payload.base_transport_tag or "").strip().lower() or None

    if tag == "container_carrier":
        if not base_name or not base_tag:
            raise HTTPException(status_code=400, detail="Для контейнеровоза нужно указать базовый транспорт (base_transport_name/base_transport_tag)")
        # бизнес-правило: контейнеровоз разгружается только краном
        # (unload_tags задаём на карточке доставки, не на услуге разгрузки)
        if payload.unload_tags:
            tags_norm = [str(x).strip().lower() for x in (payload.unload_tags or []) if str(x).strip()]
        else:
            tags_norm = []
        if tags_norm != ["crane"]:
            raise HTTPException(status_code=400, detail="Для контейнеровоза unload_tags должны быть ровно ['crane']")

    allowed_unload = {"crane", "manipulator", "self"}
    unload_tags = [str(x).strip().lower() for x in (payload.unload_tags or []) if str(x).strip()]
    unload_tags = [x for x in unload_tags if x in allowed_unload]
    unload_capability = (unload_tags[0] if unload_tags else "none")
    load_zone = normalize_zone_id(payload.load_zone)
    unload_zone = normalize_zone_id(payload.unload_zone)
    if payload.load_zone and load_zone is None:
        raise HTTPException(status_code=400, detail=f"Недопустимая load_zone. Доступно: {', '.join(list_zone_ids())}")
    if payload.unload_zone and unload_zone is None:
        raise HTTPException(status_code=400, detail=f"Недопустимая unload_zone. Доступно: {', '.join(list_zone_ids())}")

    blocks = payload.weight_blocks or []
    if tag == "container_carrier":
        # Контейнеровоз использует тарифную сетку шаланды и свою формулу,
        # поэтому отдельные delivery_ranges/per_km здесь не редактируются.
        # Храним одну "заглушку" для совместимости с текущей моделью tariffs.
        blocks = [
            WeightBlockUpsert(
                weight_condition="any",
                weight_threshold=None,
                per_km=0.0,
                delivery_ranges=[DeliveryRangeUpsert(min_distance=0.0, max_distance=0.0, base=1.0)],
                unloading_price=None,
            )
        ]
        payload.enable_delivery = True  # type: ignore[attr-defined]
        payload.enable_unloading = False  # type: ignore[attr-defined]
    elif not blocks:
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
                    base_transport_name=base_name,
                    base_transport_tag=base_tag,
                    weight_condition=cond,
                    weight_threshold=thr,
                    weight_if=_legacy_weight_if(cond, thr),
                    min_distance=float(dr.min_distance),
                    max_distance=float(dr.max_distance),
                    base=float(dr.base),
                    per_km=float(b.per_km or 0.0),
                    load_zone=load_zone,
                    unload_zone=unload_zone,
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
                base_transport_name=base_name,
                base_transport_tag=base_tag,
                weight_condition=cond,
                weight_threshold=thr,
                weight_if=_legacy_weight_if(cond, thr),
                min_distance=0.0,
                max_distance=0.0,
                base=float(b.unloading_price),
                per_km=0.0,
                load_zone=load_zone,
                unload_zone=unload_zone,
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
    password: str,
    current_user: User = Depends(require_org_min(OrgRole.ADMIN)),
    db: Session = Depends(get_db),
):
    # подтверждение паролем (как "подпись" опасной операции)
    if not verify_password(password or "", current_user.hashed_password):
        raise HTTPException(status_code=403, detail="Invalid admin password")

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
    current_user: User = Depends(require_org_min(OrgRole.MANAGER)),
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
    current_user: User = Depends(require_org_min(OrgRole.MANAGER)),
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

    # best-effort: для старых снимков “tripItems” обновляем отображение тарифа/стоимости по текущим тарифам
    _, current_tariffs = load_factories_and_tariffs(db)
    selected_snapshot = o.selected_variant_snapshot
    if isinstance(selected_snapshot, dict) and isinstance(selected_snapshot.get("tripItems"), list):
        selected_snapshot = {
            **selected_snapshot,
            "tripItems": _refresh_tripitems_tariff_labels(
                selected_snapshot.get("tripItems") or [],
                o.request_payload or {},
                current_tariffs or [],
            ),
        }

    org_role = get_user_org_role(db, current_user)
    can_view_events = org_role_rank(org_role) >= org_role_rank(OrgRole.ADMIN)

    resp = {
        "id": o.id,
        "status": o.status.value if hasattr(o.status, "value") else o.status,
        "createdAt": o.created_at.isoformat() if o.created_at else None,
        "updatedAt": o.updated_at.isoformat() if o.updated_at else None,
        "warningText": o.warning_text,
        "needsLogisticsCheck": bool(o.needs_logistics_check),
        "selectedVariant": o.selected_variant,
        "request": o.request_payload,
        "variants": o.variants_snapshot,
        "selectedVariantSnapshot": selected_snapshot,
        "manualTransportName": o.manual_transport_name,
        "manualNotes": o.manual_notes,
        "manualPayload": o.manual_payload,
        "createdBy": (o.created_by.username if o.created_by else None),
        **_derive_order_meta(events),
    }

    # "События" — только admin+
    if can_view_events:
        resp["events"] = [
            {
                "id": e.id,
                "type": e.event_type,
                "createdAt": e.created_at.isoformat() if e.created_at else None,
                "user": (e.user.username if e.user else None),
                "payload": e.payload,
            }
            for e in events
        ]

    return resp


@router.post("/admin/orders/confirm")
async def admin_confirm_order_from_quote(
    payload: OrderCreateFromQuote,
    current_user: User = Depends(require_org_min(OrgRole.LOGIST)),
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
    current_user: User = Depends(require_org_min(OrgRole.LOGIST)),
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
    current_user: User = Depends(require_org_min(OrgRole.LOGIST)),
    db: Session = Depends(get_db),
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Заказ не найден")

    order.status = OrderStatus.CONFIRMED_MANUAL
    order.manual_transport_name = decision.transportName.strip()
    order.manual_notes = (decision.notes or "").strip() or None
    payload = decision.payload or {}
    # если клиент прислал structured manual — пересчитаем и положим в payload.recalc
    try:
        manual = payload.get("manual") if isinstance(payload, dict) else None
        if isinstance(manual, dict):
            recalc = _recalc_manual_order(db, order, manual)
            payload = {**payload, "recalc": recalc}
    except HTTPException:
        # пробрасываем понятную ошибку наверх (чтобы логист увидел)
        raise
    except Exception as e:
        # не валим подтверждение, но сохраняем причину в payload
        payload = {**payload, "recalc_error": str(e)}

    order.manual_payload = payload
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


@router.post("/admin/orders/{order_id}/manual_recalc")
async def admin_manual_recalc_order(
    order_id: int,
    current_user: User = Depends(require_org_min(OrgRole.LOGIST)),
    db: Session = Depends(get_db),
):
    """Пересчитать уже сохранённое ручное решение по данным order.manual_payload.manual."""
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Заказ не найден")

    payload = order.manual_payload or {}
    manual = payload.get("manual") if isinstance(payload, dict) else None
    if not isinstance(manual, dict):
        raise HTTPException(status_code=400, detail="В заказе нет manual для перерасчёта")

    recalc = _recalc_manual_order(db, order, manual)
    order.manual_payload = {**payload, "recalc": recalc}
    db.add(order)
    db.add(
        OrderEvent(
            order_id=order.id,
            event_type="manual_recalc",
            payload={"recalc": recalc},
            user_id=current_user.id,
        )
    )
    db.commit()
    db.refresh(order)
    return {"id": order.id, "recalc": recalc}


@router.post("/admin/orders/{order_id}/approve")
async def admin_approve_order(
    order_id: int,
    decision: OrderDecision,
    current_user: User = Depends(require_org_min(OrgRole.LOGIST)),
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
    current_user: User = Depends(require_org_min(OrgRole.LOGIST)),
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


@router.post("/admin/orders/{order_id}/delete")
async def admin_delete_order(
    order_id: int,
    payload: AdminPasswordCheck,
    current_user: User = Depends(require_org_min(OrgRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """Удаление заказа (требует admin JWT + ввод пароля админа как "подпись")."""
    if not verify_password(payload.password, current_user.hashed_password):
        raise HTTPException(status_code=403, detail="Invalid admin password")

    o = db.query(Order).filter(Order.id == order_id).first()
    if not o:
        raise HTTPException(status_code=404, detail="Заказ не найден")

    # Важно: у OrderEvent нет ON DELETE CASCADE, поэтому удаляем события вручную.
    db.query(OrderEvent).filter(OrderEvent.order_id == order_id).delete(synchronize_session=False)
    db.query(Order).filter(Order.id == order_id).delete(synchronize_session=False)
    db.commit()
    return {"status": "ok", "deletedId": order_id}
