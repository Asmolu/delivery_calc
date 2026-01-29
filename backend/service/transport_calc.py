"""Transport planning and tariff selection utilities."""

from typing import Any, Dict, List, Optional, Tuple
import math
from backend.core.logger import get_logger
from backend.service.factories_service import _norm_str, _to_float
from backend.service.osrm_client import OSRMUnavailableError, get_osrm_distance_km
from backend.core.geo_zones import normalize_zone_id, point_in_zone

logger = get_logger(__name__)

# Бизнес-правило: контейнеровоз участвует только при достаточной загрузке (тонны).
CONTAINER_CARRIER_MIN_LOAD_TON = 44.0


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
        if not ignore_weight_rules and not _weight_ok(t, load_ton):
            continue
        if not ignore_capacity:
            capacity = _to_float(t.get("грузоподъёмность"))
            if capacity and load_ton > capacity:
                continue
        candidates.append(t)
    if not candidates:
        return None
    return min(candidates, key=lambda x: _trip_cost(x, distance_km))


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

        if not _weight_ok(t, load_ton):
            continue

        capacity = _to_float(t.get("грузоподъёмность"))
        if capacity and load_ton > capacity:
            continue
        candidates.append(t)

    if not candidates:
        return None

    # выбираем минимальную стоимость рейса
    return min(candidates, key=lambda x: _trip_cost(x, distance_km))


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

    def _container_trip_cost(
        container_tariff: Dict[str, Any],
        qty_rows: List[Dict[str, Any]],
        real_weight: float,
    ) -> Tuple[Optional[float], Optional[str]]:
        """Стоимость рейса контейнеровоза: shalanda_trip_cost * Σ(qty/maxPiecesInShalanda).

        Возвращает (cost, label). Если не удалось посчитать — (None, None).
        """
        base_name = _norm_str(container_tariff.get("base_transport_name") or "")
        base_tag = _norm_str(container_tariff.get("base_transport_tag") or "")
        if not base_name or not base_tag:
            return None, None

        # выбираем "как у шаланды" строку по дистанции/весу (без проверки capacity)
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
            ignore_weight_rules=True,
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
            ccost, clabel = _container_trip_cost(tariff, qty_rows, real_weight)
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
                ccost, _ = _container_trip_cost(info["tariff"], qty_rows_preview, real_w_preview)
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

    total_cost = sum(t["trip_cost"] for t in trips)
    return {
        "type": "linear",
        "transport_cost": total_cost,
        "trips": trips,
    }

# DEPRECATED: ранее был отдельный расчёт DAF по special_threshold/max_per_trip.
# На новом этапе мы не используем “особый тариф” и “максимум на рейс”, поэтому
# оставляем только базовый (linear) подбор транспорта.


# === ОСНОВНОЙ РАСЧЁТ ========================================================

def evaluate_scenario_transport(
    scenario: Dict[str, Any],
    req,
    calc_tariffs: Optional[List[Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    """Подобрать оптимальный транспортный план для выбранного сценария."""

    if not calc_tariffs:
        logger.warning("⚠️ calc_tariffs пуст или None, расчёт невозможен.")
        return None

    # Считаем “последний диапазон” для каждой машины под весовое условие
    group_max_distance = _build_group_max_distance(calc_tariffs)

    factories_map = scenario.get("factories") or {}
    if not factories_map:
        logger.warning("⚠️ В сценарии нет ни одного завода: %s", scenario)
        return None

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

    transport_type = _norm_str(getattr(req, "transport_type", "auto"))
    add_manipulator = bool(getattr(req, "add_manipulator", False) or getattr(req, "addManipulator", False))

    delivery_transport_tag = _norm_str(getattr(req, "delivery_transport_tag", None) or getattr(req, "deliveryTransportTag", None) or "auto")
    unloading_transport_tag = _norm_str(getattr(req, "unloading_transport_tag", None) or getattr(req, "unloadingTransportTag", None) or "auto")

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

    # Если задан whitelist по тегам — он приоритетнее одиночного delivery_transport_tag/legacy transport_type.
    # Пустой список = без ограничений.
    if allowed_delivery:
        forbidden_delivery -= allowed_delivery  # whitelist не должен сам себя блокировать
        allowed_tags = [t for t in all_tags if _norm_str(t).lower() in allowed_delivery]
        require_mani = add_manipulator and ("manipulator" in [x.lower() for x in (allowed_tags or [])])
        # Если по ошибке пришли несуществующие теги — трактуем как "без ограничений"
        if not allowed_tags:
            allowed_tags = delivery_tags + (["manipulator"] if add_manipulator else [])
            require_mani = add_manipulator
    # Доставка: если явно выбран тег — используем его, иначе fallback на старое transport_type
    elif delivery_transport_tag and delivery_transport_tag != "auto":
        # если пользователь явно выбрал тег, он не должен сам себя "запрещать"
        forbidden_delivery.discard(_norm_str(delivery_transport_tag).lower())
        allowed_tags = [delivery_transport_tag] if delivery_transport_tag in all_tags else delivery_tags
        require_mani = False  # отдельный манипулятор теперь добавляется только через add_manipulator
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

    total_material = 0.0
    factory_distances: Dict[str, float] = {}

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

    # DP по состояниям (container_used, delivery_mani_key)
    # Это важно, потому что разгрузка зависит от того, приезжал ли манипулятор.
    dp: Dict[Tuple[bool, Optional[str]], Dict[str, Any]] = {
        (False, None): {"delivery_cost": 0.0, "factory_plans": [], "delivery_mani": None},
    }

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
            return None

        factory_distances[factory_name] = distance_km

        total_weight = sum(_to_float(x.get("weight_total")) for x in items)
        material_cost = sum(
            _to_float(x.get("price_per_item") or x.get("price"))
            * _to_float(x.get("quantity") or x.get("count"))
            for x in items
        )
        total_material += material_cost

        # варианты планов
        plans: List[Dict[str, Any]] = []
        linear_allowed = [t for t in allowed_tags if t in ("manipulator", "long_haul", "container_carrier", "flatbed", "crane")]
        # Бизнес-правило: контейнеровоз участвует только если тоннаж по этому заводу >= порога.
        # Это более строгое правило, чем проверка на уровне отдельного рейса.
        if total_weight < CONTAINER_CARRIER_MIN_LOAD_TON - 1e-6:
            linear_allowed = [t for t in linear_allowed if t != "container_carrier"]

        # UX-правило (умный довоз):
        # В auto-режиме (без whitelist и без явного выбора тега доставки) допускаем манипулятор как ДОСТАВКУ
        # для небольших "хвостов", чтобы не отправлять длинномер с 1-2 тоннами.
        # Это не ломает ограничения: если манипулятор запрещён — мы его не добавляем.
        if (
            not allowed_delivery
            and _norm_str(delivery_transport_tag) == "auto"
            and "long_haul" in linear_allowed
            and "manipulator" not in linear_allowed
            and ("manipulator" not in { _norm_str(x).lower() for x in (forbidden_delivery or set()) })
        ):
            linear_allowed = linear_allowed + ["manipulator"]
        if linear_allowed:
            linear_plan = _linear_plan(
                total_weight,
                distance_km,
                calc_tariffs,
                linear_allowed,
                require_mani,
                items,
                group_max_distance,
                [(float(lat), float(lon))],
                dropoff_point,
            )
            if linear_plan:
                plans.append(linear_plan)
            if "manipulator" in linear_allowed and len(linear_allowed) > 1:
                manipulator_plan = _linear_plan(
                    total_weight,
                    distance_km,
                    calc_tariffs,
                    ["manipulator"],
                    require_mani,
                    items,
                    group_max_distance,
                    [(float(lat), float(lon))],
                    dropoff_point,
                )
                if manipulator_plan:
                    plans.append(manipulator_plan)
        # Альтернативный план для того же завода: без контейнеровоза.
        # Нужен, чтобы сравнить “контейнеровоз + кран” vs “шаланда + манипулятор (разгрузка манипулятором)”.
        if "container_carrier" in linear_allowed:
            alt_allowed = [t for t in linear_allowed if t != "container_carrier"]
            alt_plan = _linear_plan(
                total_weight,
                distance_km,
                calc_tariffs,
                alt_allowed,
                require_mani,
                items,
                group_max_distance,
                [(float(lat), float(lon))],
                dropoff_point,
            )
            if alt_plan:
                plans.append(alt_plan)

        if not plans:
            logger.warning("⚠️ Не удалось построить план для завода %s", factory_name)
            continue

        # DP transition
        next_dp: Dict[Tuple[bool, Optional[str]], Dict[str, Any]] = {}
        for (prev_container, prev_mani_key), prev_state in dp.items():
            prev_cost = float(prev_state.get("delivery_cost") or 0.0)
            prev_plans = list(prev_state.get("factory_plans") or [])
            prev_mani = prev_state.get("delivery_mani")
            if not math.isfinite(prev_cost):
                continue

            for p in plans:
                trips = p.get("trips") or []
                uses_container = any((_norm_str(t.get("tag")) == "container_carrier") for t in trips)
                new_container = bool(prev_container or uses_container)
                plan_mani = _plan_best_mani(trips)
                new_mani = _pick_best_mani(prev_mani, plan_mani)
                new_mani_key = (new_mani.get("tariff_name") if new_mani else None)
                new_cost = prev_cost + float(p.get("transport_cost") or 0.0)
                key = (new_container, new_mani_key)
                existing = next_dp.get(key)
                if existing is None or new_cost < float(existing.get("delivery_cost") or 0.0):
                    next_dp[key] = {
                        "delivery_cost": new_cost,
                        "delivery_mani": new_mani,
                        "factory_plans": prev_plans
                        + [
                            {
                                "factory_name": factory_name,
                                "distance_km": distance_km,
                                "transport_cost": float(p.get("transport_cost") or 0.0),
                                "trips": trips,
                                "material_cost": material_cost,
                            }
                        ],
                    }
        dp = next_dp

    if not dp:
        return None

    # --- Выбираем лучший state, учитывая разгрузку ---
    unloading_tariffs = [t for t in (calc_tariffs or []) if _norm_str(t.get("service_type")) == "unloading"]
    scenario_total_weight = sum(
        _to_float(it.get("weight_total") or (it.get("weight_per_item") or 0) * (it.get("quantity") or it.get("count") or 0))
        for its in factories_map.values()
        for it in (its or [])
    )

    def _best_unloading_for_tag(
        tag: str,
        *,
        allowed_set: set,
        forbidden_set: set,
        prefer_smallest_capacity: bool = False,
    ) -> Optional[Dict[str, Any]]:
        tag_norm = _norm_str(tag)
        candidates = []
        for tt in unloading_tariffs:
            if tag_norm and tag_norm != "auto" and _norm_str(tt.get("tag")) != tag_norm:
                continue
            if allowed_set and _norm_str(tt.get("tag")).lower() not in allowed_set:
                continue
            if forbidden_set and _norm_str(tt.get("tag")).lower() in forbidden_set:
                continue
            if not _distance_matches_tariff(
                tt,
                0.0,
                group_max_distance,
                pickup_points_all,
                dropoff_point,
            ):
                continue
            if not _weight_ok(tt, scenario_total_weight):
                continue
            candidates.append(tt)
        if not candidates:
            return None
        if prefer_smallest_capacity:
            def _cap(x: Dict[str, Any]) -> float:
                c = _to_float(x.get("грузоподъёмность") or x.get("capacity") or 0.0)
                return c if c > 0 else float("inf")
            return min(candidates, key=lambda x: (_cap(x), _to_float(x.get("base"))))
        return min(candidates, key=lambda x: _to_float(x.get("base")))

    def _compute_unloading(
        container_used_flag: bool,
        delivery_factory_plans: List[Dict[str, Any]],
        delivery_mani: Optional[Dict[str, Any]],
    ) -> Tuple[float, Optional[Dict[str, Any]]]:
        """Возвращает (unloading_cost, unloading_info) для данного состояния доставки."""
        # если нет разгрузочных тарифов — просто 0/None (UI всё равно покажет "—")
        if not unloading_tariffs:
            if container_used_flag:
                # контейнеровоз требует крана хотя бы как факт правила
                return 0.0, {
                    "service_type": "unloading",
                    "tag": "crane",
                    "tariff_name": "Кран",
                    "tariff_label": "кран (тариф разгрузки не найден)",
                    "cost": 0.0,
                }
            return 0.0, None

        # локальные копии ограничений
        tag_choice = unloading_transport_tag
        allowed_set = set(allowed_unloading or set())
        forbidden_set = set(forbidden_unloading or set())

        # контейнеровоз -> кран
        if container_used_flag:
            tag_choice = "crane"
            forbidden_set.discard("crane")
            if allowed_set:
                allowed_set = {"crane"}

        best_unload = None
        chosen_delivery_mani = delivery_mani

        if (not container_used_flag) and chosen_delivery_mani and _norm_str(tag_choice) in ("auto", "manipulator"):
            # Пытаемся подобрать разгрузочный тариф именно под этот манипулятор по имени.
            mani_name = chosen_delivery_mani.get("tariff_name") or ""
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

        # 2) Если манипулятора в доставке нет — выбираем манипулятор для разгрузки отдельно:
        # самый маленький по грузоподъёмности (и самый дешёвый при равенстве).
        if not best_unload and not container_used_flag and _norm_str(tag_choice) == "auto" and not chosen_delivery_mani:
            best_unload = _best_unloading_for_tag(
                "manipulator",
                allowed_set=allowed_set,
                forbidden_set=forbidden_set,
                prefer_smallest_capacity=True,
            ) or _best_unloading_for_tag("auto", allowed_set=allowed_set, forbidden_set=forbidden_set)

        # 3) Иначе — следуем выбранному тегу (с fallback на манипулятор, если не кран).
        if not best_unload:
            best_unload = _best_unloading_for_tag(tag_choice, allowed_set=allowed_set, forbidden_set=forbidden_set) or (
                _best_unloading_for_tag("manipulator", allowed_set=allowed_set, forbidden_set=forbidden_set, prefer_smallest_capacity=True)
                if (not container_used_flag and _norm_str(tag_choice) != "crane")
                else None
            )

        if not best_unload:
            if container_used_flag:
                return 0.0, {
                    "service_type": "unloading",
                    "tag": "crane",
                    "tariff_name": "Кран",
                    "tariff_label": "кран (тариф разгрузки не найден)",
                    "cost": 0.0,
                }
            return 0.0, None

        cost = _to_float(best_unload.get("base"))
        info = {
            "service_type": "unloading",
            "tag": _norm_str(best_unload.get("tag")),
            "tariff_name": best_unload.get("название") or best_unload.get("name") or _norm_str(best_unload.get("tag")),
            "tariff_label": _tariff_label(best_unload, distance_km=0.0),
            "cost": cost,
        }
        return cost, info

    # score all states
    candidates: List[Tuple[float, Tuple[bool, Optional[str]], float, Optional[Dict[str, Any]]]] = []
    for (used_container, mani_key), st in dp.items():
        if not st.get("factory_plans"):
            continue
        unload_cost, unload_info = _compute_unloading(
            used_container,
            st["factory_plans"],
            st.get("delivery_mani"),
        )
        total = total_material + float(st["delivery_cost"] or 0.0) + float(unload_cost or 0.0)
        candidates.append((total, (used_container, mani_key), unload_cost, unload_info))
    candidates.sort(key=lambda x: x[0])
    if not candidates:
        return None

    total_cost, best_key, unloading_cost_total, unloading_info = candidates[0]
    factory_plans = dp[best_key]["factory_plans"]
    total_delivery = float(dp[best_key]["delivery_cost"] or 0.0)

    # Важно: delivery_cost = только доставка (сумма рейсов).
    # unloading_cost = отдельная услуга разгрузки (один раз на заказ).
    total_cost = float(total_cost)
    trip_count = sum(len(f["trips"]) for f in factory_plans)
    # "transport_name" должен быть стабильным коротким названием (без дистанции),
    # поэтому используем tariff_name, а не tariff_label.
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

    return {
        "scenario": scenario,
        "material_sum": total_material,
        "delivery_cost": total_delivery,
        "unloading_cost": unloading_cost_total,
        "unloading": unloading_info,
        "total_cost": total_cost,
        "trip_count": trip_count,
        "transport_name": ", ".join(transport_names),
        "factory_distances": factory_distances,
        "factory_plans": factory_plans,
        "factories": factories_output,
    }

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
