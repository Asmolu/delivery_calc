"""Transport planning and tariff selection utilities."""

from typing import Any, Dict, List, Optional, Tuple
from itertools import product
import math
import os
from backend.core.logger import get_logger
from backend.service.factories_service import _norm_str, _to_float
from backend.service.osrm_client import OSRMUnavailableError, get_osrm_distance_km
from backend.core.geo_zones import normalize_zone_id, point_in_zone

logger = get_logger(__name__)

# Бизнес-правило: контейнеровоз участвует только при достаточной загрузке (тонны).
CONTAINER_CARRIER_MIN_LOAD_TON = 44.0
MAX_PLANS = int(os.getenv("MAX_PLANS", "50"))
MAX_VEHICLE_COMBOS_PER_PLAN = int(os.getenv("MAX_VEHICLE_COMBOS_PER_PLAN", "8"))
MAX_VARIANTS = int(os.getenv("MAX_VARIANTS", "200"))
MAX_UNLOAD_CANDIDATES_PER_DELIVERY = int(os.getenv("MAX_UNLOAD_CANDIDATES_PER_DELIVERY", "7"))
TOP_N_VARIANTS = int(os.getenv("TOP_N_VARIANTS", "150"))
K_PER_DELIVERY_TAG = int(os.getenv("K_PER_DELIVERY_TAG", "3"))
K_PER_TARIFF_GROUP = int(os.getenv("K_PER_TARIFF_GROUP", "1"))

# === БАЗОВЫЕ УТИЛИТЫ =========================================================

def _parse_weight_rule(tariff: Dict[str, Any]) -> Tuple[str, Optional[float]]:
    """Возвращает (condition, threshold).

    condition: any | le | gt
    threshold: float | None

    Поддерживает новый формат (weight_condition/weight_threshold) и legacy weight_if (≤20, >20, any).
    """
    cond = _norm_str(tariff.get("weight_condition") or "any")
    thr = tariff.get("weight_threshold", None)
    try:
        thr_val = float(thr) if thr is not None else None
    except Exception:
        thr_val = None

    if cond in ("any", "le", "gt"):
        return cond, thr_val

    # legacy fallback: weight_if like "≤20" / ">20" / "any"
    w = str(tariff.get("weight_if") or "any").strip().replace(" ", "")
    if not w or w.lower() in ("any", "все", "любая", "-"):
        return "any", None
    if w.startswith(("≤", "<=")):
        try:
            return "le", float(w.replace("≤", "").replace("<=", "") or 0) or None
        except Exception:
            return "le", None
    if w.startswith(">"):
        try:
            return "gt", float(w.replace(">", "") or 0) or None
        except Exception:
            return "gt", None
    return "any", None


def _weight_ok(tariff: Dict[str, Any], load_ton: float) -> bool:
    cond, thr = _parse_weight_rule(tariff)
    if cond == "any":
        return True
    if thr is None or thr <= 0:
        return True
    if cond == "le":
        return load_ton <= thr + 1e-9
    if cond == "gt":
        return load_ton > thr + 1e-9
    return True

def _weight_priority_key(tariff: Dict[str, Any]) -> Tuple[int, float, float]:
    """Возвращает ключ приоритета для весовых условий.

    Чем выше ключ, тем более специфичен тариф при совпадении веса.
    Формат ключа: (rank, min_weight, max_weight).
    """
    cond, thr = _parse_weight_rule(tariff)
    if cond == "any" or thr is None or thr <= 0:
        return (0, 0.0, float("inf"))
    if cond == "le":
        return (1, 0.0, float(thr))
    if cond == "gt":
        return (2, float(thr), float("inf"))
    return (0, 0.0, float("inf"))


def _select_best_weighted_tariff(
    candidates: List[Dict[str, Any]],
    load_ton: float,
    distance_km: float,
) -> Optional[Dict[str, Any]]:
    """Выбирает тариф по весовому приоритету среди уже отфильтрованных кандидатов."""
    matching = [t for t in candidates if _weight_ok(t, load_ton)]
    if not matching:
        return None

    weighted: List[Tuple[Tuple[int, float, float], Dict[str, Any]]] = [
        (_weight_priority_key(t), t) for t in matching
    ]
    best_key = max(k for k, _ in weighted)
    best_candidates = [t for k, t in weighted if k == best_key]
    return min(
        best_candidates,
        key=lambda x: (
            _trip_cost(x, distance_km),
            _to_float(x.get("id") or 0.0),
            _norm_str(x.get("name") or x.get("название") or ""),
        ),
    )

def _transport_signature(trips: List[Dict[str, Any]]) -> Tuple[Tuple[str, str], ...]:
    signature = [
        (
            str(tr.get("tag") or "").strip().lower(),
            str(tr.get("tariff_name") or "").strip().lower(),
        )
        for tr in trips or []
    ]
    return tuple(sorted(signature))
def _primary_delivery_tag(trips: List[Dict[str, Any]]) -> str:
    for trip in trips or []:
        tag = _norm_str(trip.get("tag"))
        if tag and tag not in ("manipulator", "crane"):
            return tag
    if trips:
        return _norm_str(trips[0].get("tag")) or "unknown"
    return "unknown"


def _primary_tariff_name(trips: List[Dict[str, Any]], primary_tag: str) -> str:
    for trip in trips or []:
        if _norm_str(trip.get("tag")) == primary_tag:
            return _norm_str(trip.get("tariff_name") or "")
    if trips:
        return _norm_str(trips[0].get("tariff_name") or "")
    return ""


def _plan_sort_key(plan: Dict[str, Any], idx: int) -> Tuple[float, int, Tuple[Tuple[str, str], ...], int]:
    return (
        float(plan.get("transport_cost") or 0.0),
        len(plan.get("trips") or []),
        _transport_signature(plan.get("trips") or []),
        idx,
    )


def _diversity_trim_plans(
    plan_options: List[Dict[str, Any]],
    max_total: int,
    k_per_tag: int,
    *,
    k_per_tariff_group: int = K_PER_TARIFF_GROUP,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    if not plan_options:
        return [], {"trimmed_per_tag": 0, "trimmed_final_cap": 0, "kept_by_tag": {}}

    if k_per_tag <= 0:
        k_per_tag = 1

    indexed = list(enumerate(plan_options))
    grouped: Dict[str, List[Tuple[int, Dict[str, Any]]]] = {}
    tag_tariff_groups: Dict[Tuple[str, str], List[Tuple[int, Dict[str, Any]]]] = {}
    for idx, plan in indexed:
        trips = plan.get("trips") or []
        primary_tag = _primary_delivery_tag(trips)
        grouped.setdefault(primary_tag, []).append((idx, plan))
        tariff_name = _primary_tariff_name(trips, primary_tag)
        tag_tariff_groups.setdefault((primary_tag, tariff_name), []).append((idx, plan))

    trimmed_per_tag = 0
    kept_by_tag: Dict[str, int] = {}
    kept_plans: List[Tuple[int, Dict[str, Any]]] = []

    for tag, group in grouped.items():
        group_sorted = sorted(group, key=lambda item: _plan_sort_key(item[1], item[0]))
        kept_local: List[Tuple[int, Dict[str, Any]]] = []
        if k_per_tariff_group > 0:
            for (t_tag, t_name), t_group in tag_tariff_groups.items():
                if t_tag != tag:
                    continue
                sorted_t_group = sorted(t_group, key=lambda item: _plan_sort_key(item[1], item[0]))
                kept_local.extend(sorted_t_group[:k_per_tariff_group])

        seen = set()
        deduped_local: List[Tuple[int, Dict[str, Any]]] = []
        for item in kept_local:
            if item[0] in seen:
                continue
            seen.add(item[0])
            deduped_local.append(item)

        remaining = [item for item in group_sorted if item[0] not in seen]
        k_limit = k_per_tag if k_per_tag > 0 else len(group_sorted)
        if len(deduped_local) < k_limit:
            deduped_local.extend(remaining[: k_limit - len(deduped_local)])
        trimmed_per_tag += max(len(group_sorted) - min(len(group_sorted), k_limit), 0)
        kept_by_tag[tag] = len(deduped_local)
        kept_plans.extend(deduped_local)

    merged_sorted = sorted(kept_plans, key=lambda item: _plan_sort_key(item[1], item[0]))
    trimmed_final_cap = 0
    if max_total > 0 and len(merged_sorted) > max_total:
        tags = list(grouped.keys())
        min_cap = max_total if max_total >= len(tags) else len(tags)
        base_kept: List[Tuple[int, Dict[str, Any]]] = []
        for tag in tags:
            tag_items = [item for item in merged_sorted if _primary_delivery_tag(item[1].get("trips") or []) == tag]
            if tag_items:
                base_kept.append(tag_items[0])
        base_ids = {item[0] for item in base_kept}
        remaining = [item for item in merged_sorted if item[0] not in base_ids]
        fill = remaining[: max(min_cap - len(base_kept), 0)]
        final_items = base_kept + fill
        trimmed_final_cap = len(merged_sorted) - len(final_items)
        merged_sorted = sorted(final_items, key=lambda item: _plan_sort_key(item[1], item[0]))

    return [plan for _, plan in merged_sorted], {
        "trimmed_per_tag": trimmed_per_tag,
        "trimmed_final_cap": trimmed_final_cap,
        "kept_by_tag": kept_by_tag,
    }



def _pick_best_mani(
    left: Optional[Dict[str, Any]],
    right: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not left:
        return right
    if not right:
        return left
    if (left.get("capacity_ton") or 0.0, left.get("load_ton") or 0.0) >= (
        right.get("capacity_ton") or 0.0,
        right.get("load_ton") or 0.0,
    ):
        return left
    return right


def _plan_best_mani(trips: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    mani = None
    for tr in trips or []:
        if _norm_str(tr.get("tag")) != "manipulator":
            continue
        candidate = {
            "tariff_name": tr.get("tariff_name") or "",
            "capacity_ton": float(tr.get("capacity_ton") or 0.0),
            "load_ton": float(tr.get("load_ton") or 0.0),
        }
        mani = _pick_best_mani(mani, candidate)
    return mani

def _zones_ok(
    tariff: Dict[str, Any],
    pickup_points: Optional[List[Tuple[float, float]]],
    dropoff_point: Optional[Tuple[float, float]],
) -> bool:
    raw_load_zone = tariff.get("load_zone")
    raw_unload_zone = tariff.get("unload_zone")
    load_zone = normalize_zone_id(raw_load_zone)
    unload_zone = normalize_zone_id(raw_unload_zone)

    if raw_load_zone and load_zone is None:
        return False
    if raw_unload_zone and unload_zone is None:
        return False

    if load_zone:
        if not pickup_points:
            return False
        for lat, lon in pickup_points:
            if not point_in_zone(load_zone, lat, lon):
                return False

    if unload_zone:
        if not dropoff_point:
            return False
        dlat, dlon = dropoff_point
        if not point_in_zone(unload_zone, dlat, dlon):
            return False

    return True


def _tariff_group_key(t: Dict[str, Any]) -> Tuple[str, str, str, Optional[float]]:
    """Группируем тарифные строки одной “машины” под весовое условие."""
    name = _norm_str(t.get("название") or t.get("name") or "")
    tag = _norm_str(t.get("tag") or "")
    cond, thr = _parse_weight_rule(t)
    return name, tag, cond, thr


def _build_group_max_distance(tariffs: List[Dict[str, Any]]) -> Dict[Tuple[str, str, str, Optional[float]], float]:
    """Максимальный max_distance по группе (name/tag/weight rule)."""
    out: Dict[Tuple[str, str, str, Optional[float]], float] = {}
    for t in tariffs:
        key = _tariff_group_key(t)
        md = _to_float(t.get("max_distance"))
        out[key] = max(out.get(key, 0.0), md)
    return out


def _distance_matches_tariff(
    tariff: Dict[str, Any],
    distance_km: float,
    group_max_distance: Dict[Tuple[str, str, str, Optional[float]], float],
    pickup_points: Optional[List[Tuple[float, float]]],
    dropoff_point: Optional[Tuple[float, float]],
) -> bool:
    """Проверяет, применим ли тариф к расстоянию с учётом “последнего диапазона” и геозон."""
    if not bool(tariff.get("is_active", True)):
        return False

    if not _zones_ok(tariff, pickup_points, dropoff_point):
        return False

    min_d = _to_float(tariff.get("min_distance"))
    max_d = _to_float(tariff.get("max_distance"))

    # нет верхней границы — считаем, что подходит всегда
    if max_d <= 0:
        return distance_km >= min_d - 1e-9

    if min_d <= distance_km <= max_d + 1e-9:
        return True

    # расстояние больше max: допускаем только для “последнего диапазона” этой машины под весовое условие
    if distance_km > max_d + 1e-9 and _to_float(tariff.get("per_km")) > 0:
        key = _tariff_group_key(tariff)
        group_max = _to_float(group_max_distance.get(key, 0.0))
        return group_max > 0 and abs(group_max - max_d) <= 1e-6

    return False


def _trip_cost(tariff: Dict[str, Any], distance_km: float) -> float:
    """Стоимость рейса по тарифу с учётом per_km после max_distance (для последнего диапазона)."""
    base = _to_float(tariff.get("base"))
    per_km = _to_float(tariff.get("per_km"))
    max_d = _to_float(tariff.get("max_distance"))

    if per_km and max_d > 0 and distance_km > max_d:
        extra_km = max(distance_km - max_d, 0.0)
        return base + per_km * extra_km
    return base


def _tariff_label(tariff: Dict[str, Any], distance_km: Optional[float] = None) -> str:
    """Читабельная подпись выбранного тарифа.

    Важно: подпись должна объяснять, какой именно диапазон/цена применились
    к текущей дистанции (это нужно для UI "Тариф" в детализации).
    """

    min_d = _to_float(tariff.get("min_distance"))
    max_d = _to_float(tariff.get("max_distance"))
    base = _to_float(tariff.get("base"))
    per_km = _to_float(tariff.get("per_km"))

    # диапазон
    if max_d > 0:
        range_descr = f"{min_d:g}-{max_d:g}км"
    elif min_d > 0:
        range_descr = f">={min_d:g}км"
    else:
        range_descr = "0км+"

    # цена
    base_rub = int(round(base))
    if distance_km is not None and per_km > 0 and max_d > 0 and distance_km > max_d + 1e-9:
        per_km_rub = int(round(per_km))
        price_descr = f"{base_rub}р + {per_km_rub}р/км после {max_d:g}км"
    else:
        price_descr = f"{base_rub}р"

    return f"{range_descr} {price_descr}"

def _select_tariff_by_name_tag(
    tariffs: List[Dict[str, Any]],
    *,
    name: str,
    tag: str,
    service_type: str,
    distance_km: float,
    load_ton: float,
    group_max_distance: Dict[Tuple[str, str, str, Optional[float]], float],
    pickup_points: Optional[List[Tuple[float, float]]],
    dropoff_point: Optional[Tuple[float, float]],
    ignore_capacity: bool = False,
    ignore_weight_rules: bool = False,
) -> Optional[Dict[str, Any]]:
    """Выбрать строку тарифа по точному (name, tag) с учётом дистанции/веса.

    Для контейнеровоза нужно брать стоимость "как у шаланды" даже при load > capacity шаланды,
    поэтому есть флаг ignore_capacity (тогда грузоподъёмность не ограничивает выбор строки).
    """
    nm = _norm_str(name)
    tg = _norm_str(tag)
    st = _norm_str(service_type or "delivery")
    candidates: List[Dict[str, Any]] = []
    for t in tariffs:
        if _norm_str(t.get("tag")) != tg:
            continue
        if st and _norm_str(t.get("service_type") or "delivery") != st:
            continue
        tname = _norm_str(t.get("название") or t.get("name") or "")
        if tname != nm:
            continue
        if not _distance_matches_tariff(t, distance_km, group_max_distance, pickup_points, dropoff_point):
            continue
        if not ignore_capacity:
            capacity = _to_float(t.get("грузоподъёмность"))
            if capacity and load_ton > capacity:
                continue
        candidates.append(t)
    if not candidates:
        return None
    if ignore_weight_rules:
        return min(candidates, key=lambda x: _trip_cost(x, distance_km))
    return _select_best_weighted_tariff(candidates, load_ton, distance_km)


def _select_tariff_for_load(
    tariffs: List[Dict[str, Any]],
    tag: str,
    distance_km: float,
    load_ton: float,
    group_max_distance: Dict[Tuple[str, str, str, Optional[float]], float],
    pickup_points: Optional[List[Tuple[float, float]]],
    dropoff_point: Optional[Tuple[float, float]],
    name_contains: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Возвращает лучшую строку тарифа под указанный тег/нагрузку."""
    candidates = []
    for t in tariffs:
        # Важно: эта функция используется для ДОСТАВКИ, поэтому игнорируем разгрузочные строки.
        if _norm_str(t.get("service_type") or "delivery") != "delivery":
            continue
        if _norm_str(t.get("tag")) != _norm_str(tag):
            continue
        if not _distance_matches_tariff(t, distance_km, group_max_distance, pickup_points, dropoff_point):
            continue

        if name_contains:
            name = _norm_str(t.get("название") or t.get("name") or "")
            if name_contains.lower() not in name:
                continue


        capacity = _to_float(t.get("грузоподъёмность"))
        if capacity and load_ton > capacity:
            continue
        candidates.append(t)

    if not candidates:
        return None

    return _select_best_weighted_tariff(candidates, load_ton, distance_km)


def _container_trip_cost(
    container_tariff: Dict[str, Any],
    qty_rows: List[Dict[str, Any]],
    real_weight: float,
    *,
    tariffs: List[Dict[str, Any]],
    distance_km: float,
    group_max_distance: Dict[Tuple[str, str, str, Optional[float]], float],
    pickup_points: Optional[List[Tuple[float, float]]],
    dropoff_point: Optional[Tuple[float, float]],
) -> Tuple[Optional[float], Optional[str]]:
    """Стоимость рейса контейнеровоза: shalanda_trip_cost * Σ(qty/maxPiecesInShalanda).

    Возвращает (cost, label). Если не удалось посчитать — (None, None).
    """
    base_name = _norm_str(container_tariff.get("base_transport_name") or "")
    base_tag = _norm_str(container_tariff.get("base_transport_tag") or "")
    if not base_name or not base_tag:
        return None, None

    base_tariff = _select_tariff_by_name_tag(
        tariffs,
        name=base_name,
        tag=base_tag,
        service_type="delivery",
        distance_km=distance_km,
        load_ton=max(real_weight, 0.0),
        group_max_distance=group_max_distance,
        pickup_points=pickup_points,
        dropoff_point=dropoff_point,
        ignore_capacity=True,
        ignore_weight_rules=False,
    )
    if not base_tariff:
        return None, None

    shalanda_cost = _trip_cost(base_tariff, distance_km)
    base_capacity = _to_float(base_tariff.get("грузоподъёмность") or base_tariff.get("capacity") or 0.0)
    if base_capacity <= 0:
        return None, None

    eq = 0.0
    for r in qty_rows or []:
        qty = _to_float(r.get("qty"))
        wpi = _to_float(r.get("weight_per_item"))
        if qty <= 0 or wpi <= 0:
            return None, None
        max_pieces = int(math.floor(base_capacity / wpi + 1e-9))
        if max_pieces <= 0:
            return None, None
        eq += qty / max_pieces

    cost = shalanda_cost * eq
    label = f"контейнеровоз: {round(cost):g}р (шаланда {round(shalanda_cost):g}р × {eq:.3g})"
    return cost, label


def _linear_plan(
    total_weight: float,
    distance_km: float,
    tariffs: List[Dict[str, Any]],
    allowed_tags: List[str],
    require_manipulator: bool,
    items: List[Dict[str, Any]],
    group_max_distance: Dict[Tuple[str, str, str, Optional[float]], float],
    pickup_points: Optional[List[Tuple[float, float]]],
    dropoff_point: Optional[Tuple[float, float]],
) -> Optional[Dict[str, Any]]:
    """Жадно заполняем самыми выгодными машинами, сравнивая тарифы по цене/тонне."""
    candidates: List[Dict[str, Any]] = []

    for t in tariffs:
        # Важно: план доставки должен выбирать только delivery-тарифы.
        # Иначе разгрузочные строки (service_type=unloading) могут ошибочно использоваться как доставка.
        if _norm_str(t.get("service_type") or "delivery") != "delivery":
            continue
        tag = _norm_str(t.get("tag"))
        if tag not in allowed_tags:
            continue
        if not _distance_matches_tariff(t, distance_km, group_max_distance, pickup_points, dropoff_point):
            continue

        capacity = _to_float(t.get("грузоподъёмность")) or 0
        if capacity <= 0:
            continue

        cost = _trip_cost(t, distance_km)
        cpt = cost / capacity if capacity else float("inf")
        candidates.append({
            "tag": tag,
            "tariff": t,
            "capacity": capacity,
            "cost": cost,
            "cpt": cpt,
        })

    if not candidates:
        return None


    weight_left = total_weight
    trips: List[Dict[str, Any]] = []

    # готовим остатки по позициям, чтобы понимать, что едет в каждой машине
    remaining_items: List[Dict[str, Any]] = []
    for it in items:
        qty = _to_float(it.get("quantity") or it.get("count") or 0)
        if qty <= 0:
            continue
        remaining_items.append(
            {
                "category": it.get("category"),
                "subtype": it.get("subtype"),
                "weight_per_item": _to_float(it.get("weight_per_item")),
                "remaining_qty": qty,
            }
        )

    def _allocate_items_for_trip(load_limit: float) -> Tuple[List[str], float, List[Dict[str, Any]]]:
        """Возвращает список товаров, помещённых в рейс, их мета и фактический вес.

        ВАЖНО (бизнес-правило): в одной машине нельзя смешивать разные категории.
        Поэтому один вызов аллоцирует товары только из ОДНОЙ категории.
        """

        return _allocate_items_from_state(remaining_items, load_limit, mutate=True)

    def _preview_allocate_items_for_trip(load_limit: float) -> Tuple[List[str], float, List[Dict[str, Any]]]:
        """Как _allocate_items_for_trip, но без мутации remaining_items."""
        state: List[Dict[str, Any]] = [
            {
                "category": it.get("category"),
                "subtype": it.get("subtype"),
                "weight_per_item": _to_float(it.get("weight_per_item")),
                "remaining_qty": _to_float(it.get("remaining_qty")),
            }
            for it in (remaining_items or [])
        ]
        return _allocate_items_from_state(state, load_limit, mutate=False)

    def _allocate_items_from_state(
        state: List[Dict[str, Any]],
        load_limit: float,
        *,
        mutate: bool,
    ) -> Tuple[List[str], float, List[Dict[str, Any]]]:
        assigned: List[str] = []
        qty_rows: List[Dict[str, Any]] = []
        load_used = 0.0
        if load_limit <= 0:
            return assigned, load_used, qty_rows

        cat_candidates = []
        for it in state:
            qty_left = _to_float(it.get("remaining_qty", 0))
            if qty_left <= 0:
                continue
            wpi = _to_float(it.get("weight_per_item"))
            cat = it.get("category")
            if not cat:
                continue
            cat_candidates.append((cat, qty_left * (wpi if wpi > 0 else 1.0)))
        if not cat_candidates:
            return assigned, load_used, qty_rows

        target_category = max(cat_candidates, key=lambda x: x[1])[0]

        category_items: List[Dict[str, Any]] = []
        for item in state:

            if (item.get("category") or "") != target_category:
                continue
            if _to_float(item.get("remaining_qty", 0)) <= 0:
                continue
            category_items.append(item)

        def _best_mix_for_weight(
            items_in_cat: List[Dict[str, Any]],
            limit_ton: float,
        ) -> List[int]:
            scale = 100
            limit_int = int(math.floor(limit_ton * scale + 1e-9))
            if limit_int <= 0 or not items_in_cat:
                return [0] * len(items_in_cat)

            dp: Dict[int, List[int]] = {0: [0] * len(items_in_cat)}
            for idx, it in enumerate(items_in_cat):
                weight_per_item = _to_float(it.get("weight_per_item"))
                if weight_per_item <= 0:
                    continue
                w_int = int(round(weight_per_item * scale))
                if w_int <= 0:
                    continue
                qty_left = int(_to_float(it.get("remaining_qty", 0)))
                max_take = min(qty_left, limit_int // w_int)
                if max_take <= 0:
                    continue
                current = dp.copy()
                for weight_int, alloc in dp.items():
                    for take_qty in range(1, max_take + 1):
                        new_weight = weight_int + take_qty * w_int
                        if new_weight > limit_int:
                            break
                        if new_weight not in current:
                            new_alloc = alloc.copy()
                            new_alloc[idx] += take_qty
                            current[new_weight] = new_alloc
                dp = current

            best_weight = max(dp.keys(), default=0)
            return dp.get(best_weight, [0] * len(items_in_cat))

        alloc_counts = _best_mix_for_weight(category_items, load_limit)
        for item, take_qty in zip(category_items, alloc_counts):
            if take_qty <= 0:
                continue
            weight_per_item = _to_float(item.get("weight_per_item"))
            load_used += take_qty * weight_per_item
            if mutate:
                item["remaining_qty"] = _to_float(item.get("remaining_qty", 0)) - take_qty
            qty_rows.append(
                {
                    "category": item.get("category"),
                    "subtype": item.get("subtype"),
                    "qty": int(take_qty),
                    "weight_per_item": float(weight_per_item),
                }
            )
            assigned.append(f"{item.get('category')} {item.get('subtype')}: {int(take_qty)} шт")

        for item in category_items:
            if load_limit - load_used < 0.01:
                break
            weight_per_item = _to_float(item.get("weight_per_item"))
            if weight_per_item > 0:
                continue
            qty_left = int(_to_float(item.get("remaining_qty", 0)))
            if qty_left <= 0:
                continue
            if mutate:
                item["remaining_qty"] = _to_float(item.get("remaining_qty", 0)) - qty_left
            qty_rows.append(
                {
                    "category": item.get("category"),
                    "subtype": item.get("subtype"),
                    "qty": int(qty_left),
                    "weight_per_item": 0.0,
                }
            )
            assigned.append(f"{item.get('category')} {item.get('subtype')}: {int(qty_left)} шт")

        return assigned, load_used, qty_rows


    def _assign_trip(tag: str, info: Dict[str, Any], load: float, tariff: Dict[str, Any], base_cost: float) -> bool:
        nonlocal weight_left

        # Бизнес-правило: контейнеровоз не может ехать с недогрузом.
        # Проверяем через превью-аллокацию, чтобы не мутировать состояние.
        if tag == "container_carrier":
            _, real_w_preview, qty_rows_preview = _preview_allocate_items_for_trip(load)
            if real_w_preview < CONTAINER_CARRIER_MIN_LOAD_TON - 1e-6:
                return False
            # если аллокация невозможна — тоже отказываем
            if real_w_preview <= 0:
                return False

        items_loaded, real_weight, qty_rows = _allocate_items_for_trip(load)
        if real_weight <= 0 and weight_left > 0:
            return False

        trip_cost = base_cost
        tariff_label = _tariff_label(tariff, distance_km=distance_km)
        if tag == "container_carrier":
            # повторно валидируем на реальном весе (на всякий случай)
            if real_weight < CONTAINER_CARRIER_MIN_LOAD_TON - 1e-6:
                return False
            ccost, clabel = _container_trip_cost(
                tariff,
                qty_rows,
                real_weight,
                tariffs=tariffs,
                distance_km=distance_km,
                group_max_distance=group_max_distance,
                pickup_points=pickup_points,
                dropoff_point=dropoff_point,
            )
            if ccost is None:
                return False
            trip_cost = float(ccost)
            tariff_label = clabel or tariff_label
        
        trips.append(
            {
                "tag": tag,
                "tariff_name": tariff.get("название") or tariff.get("name") or tag,
                "tariff_label": tariff_label,
                "trip_cost": trip_cost,
                "load_ton": round(real_weight, 2),
                # полезно для выбора “манипулятора на объекте” для разгрузки
                "capacity_ton": float(info.get("capacity") or 0.0),
                "distance_km": distance_km,
                "items": items_loaded or [f"Смешанная загрузка ({round(load,2)}т)"],
            }
        )
        weight_left = max(weight_left - real_weight, 0.0)
        return True

    # Гарантируем обязательный манипулятор, если он нужен
    if require_manipulator:
        mani = min(
            (c for c in candidates if c["tag"] == "manipulator"),
            key=lambda x: x["cpt"],
            default=None,
        )
        if not mani:
            return None
        load_plan = min(weight_left, mani["capacity"])
        cost = _trip_cost(mani["tariff"], distance_km)
        _assign_trip("manipulator", mani, load_plan, mani["tariff"], cost)

    safety_guard = 0
    while weight_left > 0.01:
        safety_guard += 1
        if safety_guard > 50:
            return None

        best_choice = None
        for info in candidates:
            tag = info["tag"]
            load = min(weight_left, info["capacity"])
            if load <= 0:
                continue

            if not _weight_ok(info["tariff"], load):
                continue

            cost = _trip_cost(info["tariff"], distance_km)
            eff_cpt = cost / load if load > 0 else float("inf")
            if tag == "container_carrier":
                # для контейнеровоза стоимость зависит от конкретной загрузки (в штуках),
                # поэтому считаем по превью аллокации
                _, real_w_preview, qty_rows_preview = _preview_allocate_items_for_trip(load)
                if real_w_preview <= 0:
                    continue
                # Бизнес-правило: контейнеровоз только при достаточной загрузке
                if real_w_preview < CONTAINER_CARRIER_MIN_LOAD_TON - 1e-6:
                    continue
                ccost, _ = _container_trip_cost(
                    info["tariff"],
                    qty_rows_preview,
                    real_w_preview,
                    tariffs=tariffs,
                    distance_km=distance_km,
                    group_max_distance=group_max_distance,
                    pickup_points=pickup_points,
                    dropoff_point=dropoff_point,
                )
                if ccost is None:
                    continue
                cost = float(ccost)
                eff_cpt = cost / real_w_preview if real_w_preview > 0 else float("inf")
            if best_choice is None or eff_cpt < best_choice["eff_cpt"]:
                best_choice = {
                    "tag": tag,
                    "info": info,
                    "load": load,
                    "tariff": info["tariff"],
                    "cost": cost,
                    "eff_cpt": eff_cpt,
                }
        if best_choice and weight_left > 0.0:
            max_capacity = max((float(c.get("capacity") or 0.0) for c in candidates), default=0.0)
            if max_capacity > 0 and weight_left <= max_capacity + 1e-9:
                cheapest = None
                for info in candidates:
                    tag = info["tag"]
                    load = min(weight_left, float(info.get("capacity") or 0.0))
                    if load <= 0:
                        continue
                    if not _weight_ok(info["tariff"], load):
                        continue
                    cost = _trip_cost(info["tariff"], distance_km)
                    if tag == "container_carrier":
                        _, real_w_preview, qty_rows_preview = _preview_allocate_items_for_trip(load)
                        if real_w_preview <= 0:
                            continue
                        if real_w_preview < CONTAINER_CARRIER_MIN_LOAD_TON - 1e-6:
                            continue
                        ccost, _ = _container_trip_cost(
                            info["tariff"],
                            qty_rows_preview,
                            real_w_preview,
                            tariffs=tariffs,
                            distance_km=distance_km,
                            group_max_distance=group_max_distance,
                            pickup_points=pickup_points,
                            dropoff_point=dropoff_point,
                        )
                        if ccost is None:
                            continue
                        cost = float(ccost)
                    if cheapest is None or cost < cheapest["cost"] - 1e-6:
                        cheapest = {
                            "tag": tag,
                            "info": info,
                            "load": load,
                            "tariff": info["tariff"],
                            "cost": cost,
                            "eff_cpt": cost / load if load > 0 else float("inf"),
                        }
                if cheapest and cheapest["cost"] < best_choice["cost"] - 1e-6:
                    best_choice = cheapest
        # если ничего не изменилось — выходим, чтобы избежать бесконечного цикла
        if not best_choice:
            return None

        success = _assign_trip(
            best_choice["tag"],
            best_choice["info"],
            best_choice["load"],
            best_choice["tariff"],
            best_choice["cost"],
        )

        if not success:
            # если не удалось погрузить ни одного товара, убираем этот тип транспорта из списка
            candidates = [c for c in candidates if c.get("tag") != best_choice["tag"]]
            if not candidates:
                return None
            continue
    reprice_tag_list = reprice_tag_list if reprice_tag_list is not None else allowed_tags

    for trip in trips:
        load = float(trip.get("load_ton") or 0.0)
        if load <= 0:
            continue
        best_alt = None
        for tag in reprice_tag_list:
            if tag == "container_carrier":
                continue
            tariff = _select_tariff_for_load(
                tariffs,
                tag,
                distance_km,
                load,
                group_max_distance,
                pickup_points,
                dropoff_point,
            )
            if not tariff:
                continue
            if not _weight_ok(tariff, load):
                continue
            cost = _trip_cost(tariff, distance_km)
            capacity = float(_to_float(tariff.get("грузоподъёмность")) or 0.0)
            if best_alt is None or cost < best_alt["cost"] - 1e-6:
                best_alt = {
                    "tag": tag,
                    "tariff": tariff,
                    "cost": cost,
                    "capacity": capacity,
                }
        if best_alt and best_alt["cost"] < float(trip.get("trip_cost") or 0.0) - 1e-6:
            trip["tag"] = best_alt["tag"]
            trip["tariff_name"] = best_alt["tariff"].get("название") or best_alt["tariff"].get("name") or best_alt["tag"]
            trip["tariff_label"] = _tariff_label(best_alt["tariff"], distance_km=distance_km)
            trip["trip_cost"] = float(best_alt["cost"])
            trip["capacity_ton"] = float(best_alt["capacity"] or 0.0)

    total_cost = sum(t["trip_cost"] for t in trips)
    return {
        "type": "linear",
        "transport_cost": total_cost,
        "trips": trips,
    }

def _build_delivery_plan_options(
    *,
    total_weight: float,
    distance_km: float,
    tariffs: List[Dict[str, Any]],
    allowed_tags: List[str],
    require_manipulator: bool,
    items: List[Dict[str, Any]],
    group_max_distance: Dict[Tuple[str, str, str, Optional[float]], float],
    pickup_points: Optional[List[Tuple[float, float]]],
    dropoff_point: Optional[Tuple[float, float]],
    reprice_tag_list: Optional[List[str]] = None,
    max_vehicle_combos_per_plan: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    delivery_tags = [t for t in allowed_tags if t in ("long_haul", "container_carrier", "flatbed", "manipulator")]
    plan_options: List[Dict[str, Any]] = []
    filter_reasons = {
        "container_min_load": 0,
        "no_plan": 0,
        "tariff_group_plans": 0,
        "trimmed_per_tag": 0,
        "trimmed_final_cap": 0,
        "kept_by_tag": {},
    }

    tag_sets: List[List[str]] = []
    for tag in delivery_tags:
        if tag == "container_carrier" and total_weight < CONTAINER_CARRIER_MIN_LOAD_TON - 1e-6:
            filter_reasons["container_min_load"] += 1
            continue
        tag_set = [tag]
        if require_manipulator and tag != "manipulator" and "manipulator" not in tag_set:
            tag_set.append("manipulator")
        tag_sets.append(tag_set)

    if len(delivery_tags) > 1:
        tag_sets.append(list(allowed_tags))

    def _append_plan(tag_set: List[str], tariffs_subset: Optional[List[Dict[str, Any]]] = None) -> None:
        plan = _linear_plan(
            total_weight,
            distance_km,
            tariffs_subset or tariffs,
            tag_set,
            require_manipulator,
            items,
            group_max_distance,
            pickup_points,
            dropoff_point,
            reprice_tag_list=allowed_tags,
        )
        if not plan:
            filter_reasons["no_plan"] += 1
            return
        plan_options.append(plan)

    for tag_set in tag_sets:
        _append_plan(tag_set)

    # Дополнительные варианты по конкретным тарифным группам (tag + name).
    delivery_tariffs = [
        t
        for t in tariffs
        if _norm_str(t.get("service_type") or "delivery") == "delivery"
        and _norm_str(t.get("tag")) in delivery_tags
    ]
    tariff_groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for t in delivery_tariffs:
        name = _norm_str(t.get("название") or t.get("name") or "")
        key = (_norm_str(t.get("tag")), name)
        tariff_groups.setdefault(key, []).append(t)

    for (tag, _name), group_tariffs in tariff_groups.items():
        tag_set = [tag]
        if require_manipulator and tag != "manipulator" and "manipulator" not in tag_set:
            tag_set.append("manipulator")
        tariffs_subset = group_tariffs
        if require_manipulator and "manipulator" in tag_set and tag != "manipulator":
            tariffs_subset = group_tariffs + [
                t for t in delivery_tariffs if _norm_str(t.get("tag")) == "manipulator"
            ]
        if tag == "container_carrier":
            base_refs = {
                (
                    _norm_str(t.get("base_transport_tag")),
                    _norm_str(t.get("base_transport_name")),
                )
                for t in group_tariffs
                if t.get("base_transport_tag") and t.get("base_transport_name")
            }
            if base_refs:
                base_tariffs = [
                    t
                    for t in tariffs
                    if _norm_str(t.get("tag")) in {ref[0] for ref in base_refs}
                    and _norm_str(t.get("название") or t.get("name") or "") in {ref[1] for ref in base_refs}
                ]
                tariffs_subset = tariffs_subset + base_tariffs
        _append_plan(tag_set, tariffs_subset)
        filter_reasons["tariff_group_plans"] += 1

    unique_plans: Dict[Tuple[Tuple[str, str], ...], Dict[str, Any]] = {}
    for plan in plan_options:
        signature = _transport_signature(plan.get("trips") or [])
        if signature not in unique_plans:
            unique_plans[signature] = plan
    plan_options = list(unique_plans.values())

    plan_options = sorted(plan_options, key=lambda x: float(x.get("transport_cost") or 0.0))
    trimmed, trim_info = _diversity_trim_plans(
        plan_options,
        max_vehicle_combos_per_plan,
        K_PER_DELIVERY_TAG,
    )
    filter_reasons["trimmed_per_tag"] = trim_info.get("trimmed_per_tag", 0)
    filter_reasons["trimmed_final_cap"] = trim_info.get("trimmed_final_cap", 0)
    filter_reasons["kept_by_tag"] = trim_info.get("kept_by_tag", {})
    plan_options = trimmed

    return plan_options, filter_reasons

# DEPRECATED: ранее был отдельный расчёт DAF по special_threshold/max_per_trip.
# На новом этапе мы не используем “особый тариф” и “максимум на рейс”, поэтому
# оставляем только базовый (linear) подбор транспорта.

def generate_plans(
    scenario: Dict[str, Any],
    req,
    *,
    calc_tariffs: List[Dict[str, Any]],
    group_max_distance: Dict[Tuple[str, str, str, Optional[float]], float],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Генерация базовых планов по заводам (без выбора транспорта)."""
    factories_map = scenario.get("factories") or {}
    dropoff_point: Optional[Tuple[float, float]] = None
    try:
        if req.upload_lat is not None and req.upload_lon is not None:
            dropoff_point = (float(req.upload_lat), float(req.upload_lon))
    except Exception:
        dropoff_point = None

    pickup_points_all: List[Tuple[float, float]] = []
    for items in factories_map.values():
        if not items:
            continue
        f_obj = items[0].get("factory") or {}
        lat = f_obj.get("lat")
        lon = f_obj.get("lon")
        if lat is None or lon is None:
            continue
        try:
            pickup_points_all.append((float(lat), float(lon)))
        except Exception:
            continue

    plans: List[Dict[str, Any]] = []
    factory_distances: Dict[str, float] = {}
    total_material = 0.0

    for factory_name, items in factories_map.items():
        if not items:
            continue
        f_obj = items[0].get("factory") or {}
        lat = f_obj.get("lat")
        lon = f_obj.get("lon")
        if lat is None or lon is None:
            logger.warning("⚠️ У завода %s отсутствуют координаты.", factory_name)
            continue

        try:
            distance_km = get_osrm_distance_km(lon, lat, req.upload_lon, req.upload_lat)
        except OSRMUnavailableError as exc:
            logger.error("OSRM недоступен для %s: %s", factory_name, exc)
            return [], {}

        factory_distances[factory_name] = distance_km

        total_weight = sum(_to_float(x.get("weight_total")) for x in items)
        material_cost = sum(
            _to_float(x.get("price_per_item") or x.get("price"))
            * _to_float(x.get("quantity") or x.get("count"))
            for x in items
        )
        total_material += material_cost

        plans.append(
            {
                "plan_id": factory_name,
                "legs": [
                    {
                        "factory_id": factory_name,
                        "items": items,
                        "pickup_point": (float(lat), float(lon)),
                        "drop_point": dropoff_point,
                        "weight": total_weight,
                    }
                ],
                "total_weight": total_weight,
                "material_cost": material_cost,
                "distance_km": distance_km,
                "pickup_points": [(float(lat), float(lon))],
            }
        )

    diagnostics = {
        "plans_generated": len(plans),
        "total_material": total_material,
        "factory_distances": factory_distances,
        "pickup_points_all": pickup_points_all,
    }
    return plans, diagnostics


def generate_delivery_candidates(
    req,
    *,
    plan: Dict[str, Any],
    calc_tariffs: List[Dict[str, Any]],
    allowed_tags: List[str],
    require_mani: bool,
    group_max_distance: Dict[Tuple[str, str, str, Optional[float]], float],
    max_vehicle_combos_per_plan: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Генерация вариантов доставки для плана."""
    return _build_delivery_plan_options(
        total_weight=float(plan.get("total_weight") or 0.0),
        distance_km=float(plan.get("distance_km") or 0.0),
        tariffs=calc_tariffs,
        allowed_tags=allowed_tags,
        require_manipulator=require_mani,
        items=plan.get("legs", [])[0].get("items", []) if plan.get("legs") else [],
        group_max_distance=group_max_distance,
        pickup_points=plan.get("pickup_points"),
        dropoff_point=(
            (float(req.upload_lat), float(req.upload_lon))
            if getattr(req, "upload_lat", None) is not None and getattr(req, "upload_lon", None) is not None
            else None
        ),
        max_vehicle_combos_per_plan=max_vehicle_combos_per_plan,
    )


def _filter_unloading_tariffs(
    tariffs: List[Dict[str, Any]],
    *,
    scenario_total_weight: float,
    group_max_distance: Dict[Tuple[str, str, str, Optional[float]], float],
    pickup_points_all: List[Tuple[float, float]],
    dropoff_point: Optional[Tuple[float, float]],
    allowed_set: set,
    forbidden_set: set,
    tag_choice: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    reasons = {
        "forbidden": 0,
        "zone_distance": 0,
        "weight": 0,
        "tag_mismatch": 0,
    }
    candidates: List[Dict[str, Any]] = []
    for tt in tariffs:
        if tag_choice and tag_choice not in ("auto", "none") and _norm_str(tt.get("tag")) != tag_choice:
            reasons["tag_mismatch"] += 1
            continue
        if allowed_set and _norm_str(tt.get("tag")).lower() not in allowed_set:
            reasons["forbidden"] += 1
            continue
        if forbidden_set and _norm_str(tt.get("tag")).lower() in forbidden_set:
            reasons["forbidden"] += 1
            continue
        if not _distance_matches_tariff(
            tt,
            0.0,
            group_max_distance,
            pickup_points_all,
            dropoff_point,
        ):
            reasons["zone_distance"] += 1
            continue
        if not _weight_ok(tt, scenario_total_weight):
            reasons["weight"] += 1
            continue
        candidates.append(tt)
    return candidates, reasons


def generate_unload_candidates(
    req,
    *,
    plan: Dict[str, Any],
    delivery_plan: Dict[str, Any],
    calc_tariffs: List[Dict[str, Any]],
    unloading_tariffs: List[Dict[str, Any]],
    group_max_distance: Dict[Tuple[str, str, str, Optional[float]], float],
    scenario_total_weight: float,
    pickup_points_all: List[Tuple[float, float]],
    dropoff_point: Optional[Tuple[float, float]],
    allowed_unloading: set,
    forbidden_unloading: set,
    max_unload_candidates: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Генерация вариантов разгрузки для конкретной доставки."""
    tag_choice = _norm_str(getattr(req, "unloading_transport_tag", None) or getattr(req, "unloadingTransportTag", None) or "auto")
    allowed_set = set(allowed_unloading or set())
    forbidden_set = set(forbidden_unloading or set())

    container_used_flag = any(_norm_str(t.get("tag")) == "container_carrier" for t in delivery_plan.get("trips", []) or [])
    delivery_mani = _plan_best_mani(delivery_plan.get("trips") or [])

    if _norm_str(tag_choice) == "none" or "none" in allowed_set:
        return [{"unloading": None, "cost": 0.0}], {"explicit_none": 1}

    if not unloading_tariffs:
        if container_used_flag:
            return [
                {
                    "unloading": {
                        "service_type": "unloading",
                        "tag": "crane",
                        "tariff_name": "Кран",
                        "tariff_label": "кран (тариф разгрузки не найден)",
                        "cost": 0.0,
                    },
                    "cost": 0.0,
                }
            ], {"no_tariffs_container": 1}
        return [{"unloading": None, "cost": 0.0}], {"no_tariffs": 1}

    if container_used_flag:
        tag_choice = "crane"
        forbidden_set.discard("crane")
        if allowed_set:
            allowed_set = {"crane"}

    candidates, reasons = _filter_unloading_tariffs(
        unloading_tariffs,
        scenario_total_weight=scenario_total_weight,
        group_max_distance=group_max_distance,
        pickup_points_all=pickup_points_all,
        dropoff_point=dropoff_point,
        allowed_set=allowed_set,
        forbidden_set=forbidden_set,
        tag_choice=tag_choice,
    )

    extra_candidates: List[Dict[str, Any]] = []
    if delivery_mani and _norm_str(tag_choice) in ("auto", "manipulator"):
        mani_name = delivery_mani.get("tariff_name") or ""
        best_unload = _select_tariff_by_name_tag(
            calc_tariffs or [],
            name=str(mani_name),
            tag="manipulator",
            service_type="unloading",
            distance_km=0.0,
            load_ton=scenario_total_weight,
            group_max_distance=group_max_distance,
            pickup_points=pickup_points_all,
            dropoff_point=dropoff_point,
            ignore_capacity=True,
        )
        if best_unload:
            extra_candidates.append(best_unload)

    merged = candidates + extra_candidates
    if not merged:
        if container_used_flag:
            return [
                {
                    "unloading": {
                        "service_type": "unloading",
                        "tag": "crane",
                        "tariff_name": "Кран",
                        "tariff_label": "кран (тариф разгрузки не найден)",
                        "cost": 0.0,
                    },
                    "cost": 0.0,
                }
            ], {**reasons, "fallback_container": 1}
        return [{"unloading": None, "cost": 0.0}], {**reasons, "fallback_none": 1}

    grouped: Dict[Tuple[str, str, str, Optional[float]], Dict[str, Any]] = {}
    for cand in merged:
        key = _tariff_group_key(cand)
        best = grouped.get(key)
        if not best:
            grouped[key] = cand
            continue
        if _trip_cost(cand, 0.0) < _trip_cost(best, 0.0):
            grouped[key] = cand

    unload_candidates = []
    for cand in grouped.values():
        cost = _to_float(cand.get("base"))
        unload_candidates.append(
            {
                "unloading": {
                    "service_type": "unloading",
                    "tag": _norm_str(cand.get("tag")),
                    "tariff_name": cand.get("название") or cand.get("name") or _norm_str(cand.get("tag")),
                    "tariff_label": _tariff_label(cand, distance_km=0.0),
                    "cost": cost,
                },
                "cost": cost,
            }
        )

    unload_candidates.sort(key=lambda x: float(x.get("cost") or 0.0))
    if max_unload_candidates > 0 and len(unload_candidates) > max_unload_candidates:
        trimmed = len(unload_candidates) - max_unload_candidates
        unload_candidates = unload_candidates[:max_unload_candidates]
        reasons["trimmed_unload_candidates"] = trimmed

    return unload_candidates, reasons


# === ОСНОВНОЙ РАСЧЁТ ========================================================

def evaluate_scenario_transport_variants(
    scenario: Dict[str, Any],
    req,
    calc_tariffs: Optional[List[Dict[str, Any]]],
    *,
    max_vehicle_combos_per_plan: int = MAX_VEHICLE_COMBOS_PER_PLAN,
    max_variants: int = MAX_VARIANTS,
) -> List[Dict[str, Any]]:
    """Подобрать все возможные транспортные комбинации для выбранного сценария."""

    if not calc_tariffs:
        logger.warning("⚠️ calc_tariffs пуст или None, расчёт невозможен.")
        return []

    group_max_distance = _build_group_max_distance(calc_tariffs)

    factories_map = scenario.get("factories") or {}
    if not factories_map:
        logger.warning("⚠️ В сценарии нет ни одного завода: %s", scenario)
        return []

    dropoff_point: Optional[Tuple[float, float]] = None
    try:
        if req.upload_lat is not None and req.upload_lon is not None:
            dropoff_point = (float(req.upload_lat), float(req.upload_lon))
    except Exception:
        dropoff_point = None


    transport_type = _norm_str(getattr(req, "transport_type", "auto"))
    add_manipulator = bool(getattr(req, "add_manipulator", False) or getattr(req, "addManipulator", False))

    delivery_transport_tag = _norm_str(getattr(req, "delivery_transport_tag", None) or getattr(req, "deliveryTransportTag", None) or "auto")
    forbidden_global = set(
        _norm_str(x).lower()
        for x in (getattr(req, "forbidden_types", None) or [])
        if _norm_str(x)
    )
    allowed_delivery = set(
        _norm_str(x).lower()
        for x in (getattr(req, "allowed_delivery_tags", None) or getattr(req, "allowedDeliveryTags", None) or [])
        if _norm_str(x)
    )
    allowed_unloading = set(
        _norm_str(x).lower()
        for x in (getattr(req, "allowed_unloading_tags", None) or getattr(req, "allowedUnloadingTags", None) or [])
        if _norm_str(x)
    )
    forbidden_delivery = set(
        _norm_str(x).lower()
        for x in (getattr(req, "forbidden_delivery_tags", None) or getattr(req, "forbiddenDeliveryTags", None) or [])
        if _norm_str(x)
    ) | forbidden_global
    forbidden_unloading = set(
        _norm_str(x).lower()
        for x in (getattr(req, "forbidden_unloading_tags", None) or getattr(req, "forbiddenUnloadingTags", None) or [])
        if _norm_str(x)
    ) | forbidden_global

    delivery_tags = ["long_haul", "container_carrier", "flatbed"]
    all_tags = delivery_tags + ["manipulator", "crane"]

    if allowed_delivery:
        allowed_tags = [t for t in all_tags if _norm_str(t).lower() in allowed_delivery]
        require_mani = add_manipulator and ("manipulator" in [x.lower() for x in (allowed_tags or [])])
        if not allowed_tags:
            allowed_tags = delivery_tags + (["manipulator"] if add_manipulator else [])
            require_mani = add_manipulator
    elif delivery_transport_tag and delivery_transport_tag != "auto":
        forbidden_delivery.discard(_norm_str(delivery_transport_tag).lower())
        allowed_tags = [delivery_transport_tag] if delivery_transport_tag in all_tags else delivery_tags
        require_mani = False
    else:
        # legacy route
        if transport_type == "manipulator":
            allowed_tags = ["manipulator"]
            require_mani = add_manipulator
        elif transport_type == "long_haul":
            # В auto-режиме манипулятор доступен как транспорт доставки (умный довоз).
            allowed_tags = delivery_tags + ["manipulator"] + (["manipulator"] if add_manipulator else [])
            require_mani = add_manipulator
        else:
            # В auto-режиме манипулятор доступен как транспорт доставки (умный довоз).
            allowed_tags = delivery_tags + ["manipulator"] + (["manipulator"] if add_manipulator else [])
            require_mani = add_manipulator

    # применяем запреты для доставки
    if forbidden_delivery:
        allowed_tags = [t for t in (allowed_tags or []) if _norm_str(t).lower() not in forbidden_delivery]

    plans, plan_diag = generate_plans(
        scenario,
        req,
        calc_tariffs=calc_tariffs,
        group_max_distance=group_max_distance,
    )
    if not plans:
        return []

    total_material = float(plan_diag.get("total_material") or 0.0)
    factory_distances = plan_diag.get("factory_distances") or {}
    pickup_points_all: List[Tuple[float, float]] = plan_diag.get("pickup_points_all") or []

    safe_vehicle_combos = max_vehicle_combos_per_plan
    if safe_vehicle_combos == 1:
        logger.warning("⚠️ max_vehicle_combos_per_plan=1 запрещён, увеличиваем до 2.")
        safe_vehicle_combos = 2

    plans_by_factory: List[Dict[str, Any]] = []
    vehicle_combo_reasons = {
        "container_min_load": 0,
        "no_plan": 0,
        "trimmed_per_tag": 0,
        "trimmed_final_cap": 0,
        "kept_by_tag": {},
        "tariff_group_plans": 0,
        "max_variants": 0,
    }
    delivery_candidates_total = 0
    delivery_candidates_feasible = 0

    for plan in plans:

        linear_allowed = [t for t in allowed_tags if t in ("manipulator", "long_haul", "container_carrier", "flatbed", "crane")]
        if (
            not allowed_delivery
            and _norm_str(delivery_transport_tag) == "auto"
            and "long_haul" in linear_allowed
            and "manipulator" not in linear_allowed
            and ("manipulator" not in {_norm_str(x).lower() for x in (forbidden_delivery or set())})
        ):
            linear_allowed = linear_allowed + ["manipulator"]

        delivery_candidates, reasons = generate_delivery_candidates(
            req,
            plan=plan,
            calc_tariffs=calc_tariffs,
            allowed_tags=linear_allowed,
            require_mani=require_mani,
            group_max_distance=group_max_distance,
            max_vehicle_combos_per_plan=safe_vehicle_combos,
        )
        for reason, count in reasons.items():
            if isinstance(count, dict):
                current = vehicle_combo_reasons.get(reason, {})
                if not isinstance(current, dict):
                    current = {}
                for key, value in count.items():
                    current[key] = current.get(key, 0) + value
                vehicle_combo_reasons[reason] = current
            else:
                vehicle_combo_reasons[reason] = vehicle_combo_reasons.get(reason, 0) + count

        delivery_candidates_total += len(delivery_candidates)
        delivery_candidates_feasible += len(delivery_candidates)

        if not delivery_candidates:
            logger.warning("⚠️ Не удалось построить план для завода %s", plan.get("plan_id"))
            return []

        plans_by_factory.append(
            {
                "factory_name": plan.get("plan_id"),
                "distance_km": plan.get("distance_km"),
                "material_cost": plan.get("material_cost"),
                "plan_options": delivery_candidates,
            }
        )

    if not plans_by_factory:
        return []

    # --- Подготовка разгрузки ---
    unloading_tariffs = [t for t in (calc_tariffs or []) if _norm_str(t.get("service_type")) == "unloading"]
    scenario_total_weight = sum(
        _to_float(it.get("weight_total") or (it.get("weight_per_item") or 0) * (it.get("quantity") or it.get("count") or 0))
        for its in factories_map.values()
        for it in (its or [])
    )

    def _has_other_delivery_targets(factory_plans: List[Dict[str, Any]]) -> bool:
        for plan in factory_plans or []:
            for trip in plan.get("trips", []) or []:
                if _norm_str(trip.get("tag")) != "manipulator":
                    return True
        return False

    plan_options_counts = {p["factory_name"]: len(p["plan_options"]) for p in plans_by_factory}
    num_vehicle_combos_generated = math.prod(plan_options_counts.values()) if plan_options_counts else 0

    import heapq

    variants_heap: List[Tuple[Tuple[float, int, str, int], Dict[str, Any]]] = []
    variant_counter = 0
    variants_evaluated_pre_score = 0
    variants_evaluated_exact = 0
    unload_candidates_feasible = 0
    unload_filter_reasons: Dict[str, int] = {}
    if num_vehicle_combos_generated:
        for combo in product(*[p["plan_options"] for p in plans_by_factory]):
            if max_variants > 0 and variants_evaluated_exact >= max_variants:
                vehicle_combo_reasons["max_variants"] += 1
                break
            factory_plans: List[Dict[str, Any]] = []
            total_delivery = 0.0
            delivery_mani = None
            for plan_info, plan in zip(plans_by_factory, combo):
                trips = plan.get("trips") or []
                total_delivery += float(plan.get("transport_cost") or 0.0)
                delivery_mani = _pick_best_mani(delivery_mani, _plan_best_mani(trips))
                factory_plans.append(
                    {
                        "factory_name": plan_info["factory_name"],
                        "distance_km": plan_info["distance_km"],
                        "transport_cost": float(plan.get("transport_cost") or 0.0),
                        "trips": trips,
                        "material_cost": plan_info["material_cost"],
                    }
                )
            variants_evaluated_pre_score += 1

            combined_plan = {"trips": [t for f in factory_plans for t in f.get("trips", [])]}
            unload_candidates, unload_reasons = generate_unload_candidates(
                req,
                plan=combined_plan,
                delivery_plan=combined_plan,
                calc_tariffs=calc_tariffs,
                unloading_tariffs=unloading_tariffs,
                group_max_distance=group_max_distance,
                scenario_total_weight=scenario_total_weight,
                pickup_points_all=pickup_points_all,
                dropoff_point=dropoff_point,
                allowed_unloading=allowed_unloading,
                forbidden_unloading=forbidden_unloading,
                max_unload_candidates=max(MAX_UNLOAD_CANDIDATES_PER_DELIVERY, 2),
            )
            for reason, count in unload_reasons.items():
                unload_filter_reasons[reason] = unload_filter_reasons.get(reason, 0) + count
            unload_candidates_feasible += len(unload_candidates)

            trip_count = sum(len(f["trips"]) for f in factory_plans)
            transport_names = sorted(
                {
                    t.get("tariff_name") or t.get("tag")
                    for f in factory_plans
                    for t in f["trips"]
                }
            )
            factories_output = [
                {
                    "factory_name": plan.get("factory_name"),
                    "distance_km": plan.get("distance_km"),
                    "trips": plan.get("trips", []),
                }
                for plan in factory_plans
            ]

            for unload_candidate in unload_candidates:
                unloading_info = unload_candidate.get("unloading")
                unloading_cost_total = float(unload_candidate.get("cost") or 0.0)
                if (
                    delivery_mani
                    and unloading_info
                    and _norm_str(unloading_info.get("tag")) == "manipulator"
                    and not _has_other_delivery_targets(factory_plans)
                ):
                    unloading_cost_total = 0.0
                    unloading_info = None

                total_cost = total_material + total_delivery + float(unloading_cost_total or 0.0)
                variant_counter += 1
                sort_key = (
                    float(total_cost),
                    int(trip_count),
                    ", ".join(transport_names),
                    variant_counter,
                )
                debug_info = {
                    "plans_generated": plan_diag.get("plans_generated"),
                    "delivery_candidates_total": delivery_candidates_total,
                    "delivery_candidates_feasible": delivery_candidates_feasible,
                    "unload_candidates_feasible": unload_candidates_feasible,
                    "variants_evaluated_pre_score": variants_evaluated_pre_score,
                    "variants_evaluated_exact": variants_evaluated_exact + 1,
                    "variants_returned": 0,
                    "num_vehicle_combos_generated": num_vehicle_combos_generated,
                    "num_vehicle_combos_feasible": min(num_vehicle_combos_generated, max_variants or num_vehicle_combos_generated),
                    "factory_plan_counts": plan_options_counts,
                    "vehicle_combo_filter_reasons": vehicle_combo_reasons,
                    "unload_filter_reasons": unload_filter_reasons,
                }
                variant = {
                    "scenario": scenario,
                    "material_sum": total_material,
                    "delivery_cost": total_delivery,
                    "unloading_cost": unloading_cost_total,
                    "unloading": unloading_info,
                    "total_cost": float(total_cost),
                    "trip_count": trip_count,
                    "transport_name": ", ".join(transport_names),
                    "factory_distances": factory_distances,
                    "factory_plans": factory_plans,
                    "factories": factories_output,
                    "debug": debug_info,
                }
                variants_evaluated_exact += 1

                if TOP_N_VARIANTS <= 0:
                    continue
                heap_item = ((-sort_key[0], -sort_key[1], sort_key[2], sort_key[3]), variant)
                if len(variants_heap) < TOP_N_VARIANTS:
                    heapq.heappush(variants_heap, heap_item)
                else:
                    if heap_item[0] > variants_heap[0][0]:
                        heapq.heapreplace(variants_heap, heap_item)

    variants = [item[1] for item in variants_heap]
    variants.sort(key=lambda x: (float(x.get("total_cost") or 0.0), int(x.get("trip_count") or 0), x.get("transport_name") or ""))
    for variant in variants:
        if isinstance(variant.get("debug"), dict):
            variant["debug"]["variants_returned"] = len(variants)

    logger.info(
        "📊 combos=%s variants=%s plans=%s filters=%s unload_filters=%s",
        num_vehicle_combos_generated,
        len(variants),
        plan_options_counts,
        vehicle_combo_reasons,
        unload_filter_reasons,
    )
    return variants


def evaluate_scenario_transport(
    scenario: Dict[str, Any],
    req,
    calc_tariffs: Optional[List[Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    """Подобрать оптимальный транспортный план для выбранного сценария."""
    variants = evaluate_scenario_transport_variants(
        scenario,
        req,
        calc_tariffs,
        max_vehicle_combos_per_plan=MAX_VEHICLE_COMBOS_PER_PLAN,
        max_variants=MAX_VARIANTS,
    )
    if not variants:
        return None
    return variants[0]

def build_shipment_details_from_result(best_result, req):
    """Формирует детальный список по каждому рейсу и товарам."""
    rows = []
    scenario_factories = (best_result.get("scenario") or {}).get("factories") or {}

    for f_plan in best_result.get("factory_plans", best_result.get("factories", [])):
        factory_name = f_plan.get("factory_name")
        distance = round(f_plan.get("distance_km", 0), 2)
        material_cost = round(f_plan.get("material_cost", 0), 2)
        delivery_cost = round(f_plan.get("transport_cost", 0), 2)

        # Описание товаров, которые забираем с этого завода
        products = []
        contact = ""
        for item in scenario_factories.get(factory_name, []):
            qty = item.get("quantity") or item.get("count") or 0
            title = f"{item.get('category')} {item.get('subtype')}"
            products.append(f"{title} × {qty}")

            # Берём первый доступный контакт завода
            if not contact:
                fact = item.get("factory") or {}
                contact = fact.get("contact") or ""

        # Сгруппированное описание машин и рейсов
        machine_map = {}
        for trip in f_plan.get("trips", []):
            name = trip.get("tariff_name") or trip.get("tag") or "Транспорт"
            machine_map.setdefault(name, 0)
            machine_map[name] += 1

        machine_desc = "; ".join(
            f"{name} — {count} рейс(ов)" for name, count in machine_map.items()
        ) or "—"

        unloading = best_result.get("unloading") or {}
        unloading_name = unloading.get("tariff_name") or unloading.get("tag") or ""
        unloading_label = unloading.get("tariff_label") or ""
        unloading_cost = unloading.get("cost", None)
        if unloading_name:
            if unloading_cost:
                unloading_desc = f"{unloading_name}: {round(float(unloading_cost))}₽"
            elif unloading_label:
                unloading_desc = f"{unloading_name}: {unloading_label}"
            else:
                unloading_desc = str(unloading_name)
        else:
            unloading_desc = "—"

        rows.append(
            {
                "завод": factory_name,
                "контакт": contact,
                "товар": "; ".join(products) or "—",
                "машина": machine_desc,
                "разгрузка": unloading_desc,
                "расстояние_км": distance,
                "стоимость_материала": material_cost,
                "стоимость_доставки": delivery_cost,
                "итого": round(material_cost + delivery_cost, 2),
            }
        )

    return rows

def build_trip_items_details(best_result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Возвращает детализацию погрузки по каждой машине."""

    unloading = best_result.get("unloading") or {}
    unloading_name = unloading.get("tariff_name") or unloading.get("tag") or ""
    unloading_cost = unloading.get("cost", None)
    if unloading_name:
        if unloading_cost:
            unloading_desc = f"{unloading_name}: {round(float(unloading_cost))}₽"
        else:
            unloading_desc = str(unloading_name)
    else:
        unloading_desc = "—"

    trip_rows = []
    for f_plan in best_result.get("factory_plans", best_result.get("factories", [])):
        factory_name = f_plan.get("factory_name")
        for trip in f_plan.get("trips", []):
            trip_rows.append(
                {
                    "завод": factory_name,
                    "машина": trip.get("tariff_name") or trip.get("tag"),
                    "тариф": trip.get("tariff_label") or trip.get("tariff_name"),
                    "разгрузка": unloading_desc,
                    "расстояние_км": round(trip.get("distance_km", 0), 2),
                    "загрузка_т": round(trip.get("load_ton", 0), 2),
                    "товары": "; ".join(trip.get("items") or []),
                    "стоимость_доставки": round(trip.get("trip_cost", 0), 2),
                }
            )

    return trip_rows
