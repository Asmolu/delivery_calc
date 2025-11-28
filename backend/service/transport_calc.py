import logging
from typing import Any, Dict, List, Optional, Tuple
from backend.service.factories_service import _norm_str, _to_float
from backend.service.osrm_client import get_osrm_distance_km
logger = logging.getLogger(__name__)


# === БАЗОВЫЕ УТИЛИТЫ =========================================================

def _distance_in_range(tariff: Dict[str, Any], distance_km: float) -> bool:
    """Проверяет, попадает ли расстояние в диапазон тарифа."""
    min_d = _to_float(tariff.get("min_distance"))
    max_d = _to_float(tariff.get("max_distance"))


    if max_d and max_d != min_d:
        return min_d <= distance_km <= max_d
    if max_d == min_d and max_d > 0:
        return distance_km >= max_d
    return True


def _trip_cost(tariff: Dict[str, Any], distance_km: float) -> float:
    """Стоимость рейса по тарифу с учётом per_km на перерасстояние."""
    base = _to_float(tariff.get("base"))
    per_km = _to_float(tariff.get("per_km"))
    min_d = _to_float(tariff.get("min_distance"))
    max_d = _to_float(tariff.get("max_distance"))

    if per_km and max_d == min_d and distance_km > max_d:
        extra_km = max(distance_km - max_d, 0)
        return base + per_km * extra_km
    return base


def _select_tariff_for_load(
    tariffs: List[Dict[str, Any]], tag: str, distance_km: float, load_ton: float
) -> Optional[Dict[str, Any]]:
    """Возвращает лучшую строку тарифа под указанный тег/нагрузку."""
    candidates = []
    for t in tariffs:
        if _norm_str(t.get("tag")) != _norm_str(tag):
            continue
        if not _distance_in_range(t, distance_km):
            continue

        weight_if = _norm_str(t.get("weight_if") or "any")
        if weight_if == "≤20" and load_ton > 20:
            continue
        if weight_if == ">20" and load_ton <= 20:
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
) -> Optional[Dict[str, Any]]:
    """Простая жадная стратегия: заполняем самыми выгодными машинами."""
    candidates: List[Tuple[str, Dict[str, Any]]] = []
    for tag in allowed_tags:
        tariff = _select_tariff_for_load(tariffs, tag, distance_km, 1)
        if not tariff:
            continue
        capacity = _to_float(tariff.get("грузоподъёмность")) or 0
        if capacity <= 0:
            continue
        cost = _trip_cost(tariff, distance_km)
        cost_per_ton = cost / capacity if capacity else float("inf")
        candidates.append((tag, {"tariff": tariff, "capacity": capacity, "cost": cost, "cpt": cost_per_ton}))

    if not candidates:
        return None

    # сортируем по выгодности (стоимость за тонну)
    candidates.sort(key=lambda x: x[1]["cpt"])

    weight_left = total_weight
    trips: List[Dict[str, Any]] = []

    def _assign_trip(tag: str, info: Dict[str, Any]):
        nonlocal weight_left
        load = min(weight_left, info["capacity"])
        tariff = _select_tariff_for_load(tariffs, tag, distance_km, load)
        if not tariff:
            return False
        cost = _trip_cost(tariff, distance_km)
        trips.append(
            {
                "tag": tag,
                "tariff_name": tariff.get("название") or tariff.get("name") or tag,
                "trip_cost": cost,
                "load_ton": round(load, 2),
                "distance_km": distance_km,
                "items": [f"Смешанная загрузка ({round(load,2)}т)"],
            }
        )
        weight_left -= load
        return True

    # гарантируем хотя бы один манипулятор, если требуется
    if require_manipulator:
        mani = next((c for c in candidates if c[0] == "manipulator"), None)
        if not mani:
            return None
        _assign_trip(mani[0], mani[1])

    while weight_left > 0.01:
        progress = False
        for tag, info in candidates:
            if weight_left <= 0.01:
                break
            before = weight_left
            _assign_trip(tag, info)
            if weight_left < before:
                progress = True
        # если ничего не изменилось — выходим, чтобы избежать бесконечного цикла
        if weight_left > 0.01 and not progress:
            return None

    total_cost = sum(t["trip_cost"] for t in trips)
    return {
        "type": "linear",
        "transport_cost": total_cost,
        "trips": trips,
    }

def _daf_plan(
    items: List[Dict[str, Any]],
    distance_km: float,
    tariffs: List[Dict[str, Any]],
    require_manipulator: bool,
) -> Optional[Dict[str, Any]]:
    """Расчёт с опорой на DAF (ступенчатый тариф по special_threshold)."""
    daf_capacity = 55.0
    daf_tariff = _select_tariff_for_load(tariffs, "long_haul", distance_km, 30)
    if not daf_tariff or "DAF" not in (daf_tariff.get("название") or ""):
        return None

    trips = []
    total_cost = 0.0

    for item in items:
        qty = item.get("quantity", 0)
        if qty <= 0:
            continue
        threshold = _to_float(item.get("special_threshold"))
        max_per_trip = _to_float(item.get("max_per_trip")) or qty
        weight_per_item = _to_float(item.get("weight_per_item"))
        remaining = qty

        while remaining > 0:
            load_items = min(remaining, max_per_trip)
            load_weight = weight_per_item * load_items
            if load_weight > daf_capacity:
                load_items = max(int(daf_capacity // weight_per_item), 1)
                load_weight = weight_per_item * load_items

            trip_tariff = _select_tariff_for_load(tariffs, "long_haul", distance_km, load_weight)
            if not trip_tariff:
                return None
            base_cost = _trip_cost(trip_tariff, distance_km)
            if threshold and load_items >= threshold:
                cost = base_cost / threshold * load_items
            else:
                cost = base_cost

            trips.append(
                {
                    "tag": "long_haul",
                    "tariff_name": trip_tariff.get("название") or "DAF",
                    "trip_cost": cost,
                    "load_ton": round(load_weight, 2),
                    "distance_km": distance_km,
                    "items": [
                        f"{item.get('category')} {item.get('subtype')}: {load_items} шт"
                    ],
                }
            )
            total_cost += cost
            remaining -= load_items

    if not trips:
        return None

    # добавляем обязательный манипулятор, если требуется
    if require_manipulator:
        mani_tariff = _select_tariff_for_load(tariffs, "manipulator", distance_km, 5)
        if not mani_tariff:
            return None
        mani_cost = _trip_cost(mani_tariff, distance_km)
        trips.append(
            {
                "tag": "manipulator",
                "tariff_name": mani_tariff.get("название") or "Манипулятор",
                "trip_cost": mani_cost,
                "load_ton": min(10.0, sum(i.get("load_ton", 0) for i in trips)),
                "distance_km": distance_km,
                "items": ["Обязательный манипулятор (+1)",],
            }
        )
        total_cost += mani_cost

    return {
        "type": "daf",
        "transport_cost": total_cost,
        "trips": trips,
    }


# === ОСНОВНОЙ РАСЧЁТ ========================================================

def evaluate_scenario_transport(
    scenario: Dict[str, Any],
    req,
    calc_tariffs: Optional[List[Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    """Считает лучший вариант доставки для сценария (комбинация заводов)."""

    if not calc_tariffs:
        logger.warning("⚠️ calc_tariffs пуст или None, расчёт невозможен.")
        return None

    factories_map = scenario.get("factories") or {}
    if not factories_map:
        logger.warning("⚠️ В сценарии нет ни одного завода: %s", scenario)
        return None

    transport_type = _norm_str(getattr(req, "transport_type", "auto"))
    add_manipulator = bool(getattr(req, "add_manipulator", False) or getattr(req, "addManipulator", False))
    selected_special = getattr(req, "selected_special", None)

    if selected_special:
        allowed_tags = ["special"]
        require_mani = False
    elif transport_type == "manipulator":
        allowed_tags = ["manipulator"]
        require_mani = True if add_manipulator else False
    elif transport_type == "long_haul":
        allowed_tags = ["long_haul"] + (["manipulator"] if add_manipulator else [])
        require_mani = add_manipulator
    else:
        allowed_tags = ["long_haul", "manipulator"]
        require_mani = add_manipulator

    factory_plans = []
    total_material = 0.0
    total_delivery = 0.0
    factory_distances = {}

    for factory_name, items in factories_map.items():
        if not items:
            continue
        f_obj = items[0].get("factory") or {}
        lat = f_obj.get("lat")
        lon = f_obj.get("lon")
        if lat is None or lon is None:
            logger.warning("⚠️ У завода %s отсутствуют координаты.", factory_name)
            continue

        distance_km = get_osrm_distance_km(lon, lat, req.upload_lon, req.upload_lat)
        if distance_km is None:
            logger.warning("⚠️ Не удалось получить расстояние до клиента для %s", factory_name)
            continue

        factory_distances[factory_name] = distance_km

        total_weight = sum(_to_float(x.get("weight_total")) for x in items)
        material_cost = sum(_to_float(x.get("price_per_item") or x.get("price")) * _to_float(x.get("quantity") or x.get("count")) for x in items)
        total_material += material_cost

        # варианты планов
        plans = []
        linear_allowed = [t for t in allowed_tags if t in ("manipulator", "long_haul", "special")]
        if linear_allowed:
            linear_plan = _linear_plan(total_weight, distance_km, calc_tariffs, linear_allowed, require_mani, items)
            if linear_plan:
                plans.append(linear_plan)

        # DAF применяется только если доступен длинномер и есть товары с порогом
        has_threshold_items = any(_to_float(x.get("special_threshold")) > 0 and _to_float(x.get("max_per_trip")) > 0 for x in items)
        if "long_haul" in allowed_tags and has_threshold_items:
            daf_plan = _daf_plan(items, distance_km, calc_tariffs, require_mani)
            if daf_plan:
                plans.append(daf_plan)

        if not plans:
            logger.warning("⚠️ Не удалось построить план для завода %s", factory_name)
            continue

        best_plan = min(plans, key=lambda p: p["transport_cost"])
        total_delivery += best_plan["transport_cost"]

        factory_plans.append(
            {
                "factory_name": factory_name,
                "distance_km": distance_km,
                "transport_cost": best_plan["transport_cost"],
                "trips": best_plan["trips"],
                "material_cost": material_cost,
            }
        )

    if not factory_plans:
        return None

    total_cost = total_material + total_delivery
    trip_count = sum(len(f["trips"]) for f in factory_plans)
    transport_names = sorted({t.get("tariff_name") for f in factory_plans for t in f["trips"]})

    return {
        "scenario": scenario,
        "material_sum": total_material,
        "delivery_cost": total_delivery,
        "total_cost": total_cost,
        "trip_count": trip_count,
        "transport_name": ", ".join(transport_names),
        "factory_distances": factory_distances,
        "factory_plans": factory_plans,
    }

def build_shipment_details_from_result(best_result, req):
    """Формирует детальный список по каждому рейсу и товарам."""
    rows = []
    for f_plan in best_result.get("factory_plans", []):
        factory_name = f_plan.get("factory_name")
        distance = f_plan.get("distance_km", 0)
        for trip in f_plan.get("trips", []):
            rows.append(
                {
                    "машина": trip.get("tariff_name"),
                    "tag": trip.get("tag"),
                    "завод": factory_name,
                    "расстояние_км": round(distance, 2),
                    "вес_тонн": trip.get("load_ton"),
                    "стоимость_доставки": round(trip.get("trip_cost", 0), 2),
                    "содержимое": trip.get("items", []),
                }
            )

    return rows
