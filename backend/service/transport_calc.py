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


def _tariff_label(tariff: Dict[str, Any]) -> str:
    """Читабельная подпись выбранного тарифа."""

    name = tariff.get("название") or tariff.get("name") or "Тариф"
    descr = tariff.get("описание") or tariff.get("description") or ""
    if descr:
        return f"{name} — {descr}"

    min_d = _to_float(tariff.get("min_distance"))
    max_d = _to_float(tariff.get("max_distance"))
    weight_if = _norm_str(tariff.get("weight_if") or "any")

    range_descr = ""
    if max_d and max_d != min_d:
        range_descr = f"{min_d}-{max_d} км"
    elif max_d == min_d and max_d > 0:
        range_descr = f">={max_d} км"

    weight_descr = ""
    if weight_if == "≤20":
        weight_descr = "≤20т"
    elif weight_if == ">20":
        weight_descr = ">20т"

    if range_descr and weight_descr:
        return f"{name} — {range_descr}, {weight_descr}"
    if range_descr:
        return f"{name} — {range_descr}"
    if weight_descr:
        return f"{name} — {weight_descr}"
    return name


def _select_tariff_for_load(
    tariffs: List[Dict[str, Any]],
    tag: str,
    distance_km: float,
    load_ton: float,
    name_contains: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Возвращает лучшую строку тарифа под указанный тег/нагрузку.

    name_contains: если задано, оставляет только строки, где название содержит
    указанную подстроку (регистр игнорируется).
    """
    candidates = []
    for t in tariffs:
        if _norm_str(t.get("tag")) != _norm_str(tag):
            continue
        if not _distance_in_range(t, distance_km):
            continue

        if name_contains:
            name = _norm_str(t.get("название") or t.get("name") or "")
            if name_contains.lower() not in name:
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


def _calc_daf_step_cost(base_cost: float, loaded_meta: List[Dict[str, Any]]) -> float:
    """Расчёт ступенчатой цены для DAF по количеству единиц с порогом."""

    thresholds = [
        _to_float(m.get("special_threshold"))
        for m in loaded_meta
        if _to_float(m.get("special_threshold")) > 0
    ]
    if not thresholds:
        return base_cost

    qty_sum = sum(
        _to_float(m.get("qty"))
        for m in loaded_meta
        if _to_float(m.get("special_threshold")) > 0
    )
    if qty_sum <= 0:
        return base_cost

    threshold = min(thresholds)
    if qty_sum >= threshold:
        return base_cost / threshold * qty_sum

    return base_cost


def _linear_plan(
    total_weight: float,
    distance_km: float,
    tariffs: List[Dict[str, Any]],
    allowed_tags: List[str],
    require_manipulator: bool,
    items: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Жадно заполняем самыми выгодными машинами, сравнивая тарифы по цене/тонне."""
    candidates: List[Dict[str, Any]] = []

    for t in tariffs:
        tag = _norm_str(t.get("tag"))
        if tag not in allowed_tags:
            continue
        if not _distance_in_range(t, distance_km):
            continue

        capacity = _to_float(t.get("грузоподъёмность")) or 0
        if capacity <= 0:
            continue

        weight_if = _norm_str(t.get("weight_if") or "any")

        cost = _trip_cost(t, distance_km)
        cpt = cost / capacity if capacity else float("inf")
        candidates.append({
            "tag": tag,
            "tariff": t,
            "capacity": capacity,
            "cost": cost,
            "cpt": cpt,
            "weight_if": weight_if,
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
                "special_threshold": _to_float(it.get("special_threshold")),
                "remaining_qty": qty,
            }
        )

    def _allocate_items_for_trip(load_limit: float) -> Tuple[List[str], List[Dict[str, Any]], float]:
        """Возвращает список товаров, помещённых в рейс, их мета и фактический вес."""

        assigned: List[str] = []
        assigned_meta: List[Dict[str, Any]] = []
        load_used = 0.0
        if load_limit <= 0:
            return assigned, load_used

        for item in remaining_items:
            if load_limit - load_used < 0.01:
                break

            qty_left = item.get("remaining_qty", 0)
            if qty_left <= 0:
                continue

            weight_per_item = _to_float(item.get("weight_per_item"))
            if weight_per_item <= 0:
                # Нулевой вес — просто отгружаем остаток
                take_qty = int(qty_left)
                if take_qty > 0:
                    item["remaining_qty"] = qty_left - take_qty
                    assigned.append(
                        f"{item.get('category')} {item.get('subtype')}: {take_qty} шт"
                    )
                    assigned_meta.append(
                        {
                            "category": item.get("category"),
                            "subtype": item.get("subtype"),
                            "qty": take_qty,
                            "special_threshold": item.get("special_threshold"),
                        }
                    )
                continue

            max_qty_by_weight = int((load_limit - load_used + 1e-6) // weight_per_item)
            if max_qty_by_weight <= 0:
                continue

            take_qty = min(qty_left, max_qty_by_weight)
            if take_qty <= 0:
                continue

            load_used += take_qty * weight_per_item
            item["remaining_qty"] = qty_left - take_qty
            assigned.append(
                f"{item.get('category')} {item.get('subtype')}: {int(take_qty)} шт"
            )
            assigned_meta.append(
                {
                    "category": item.get("category"),
                    "subtype": item.get("subtype"),
                    "qty": take_qty,
                    "special_threshold": item.get("special_threshold"),
                }
            )
        return assigned, assigned_meta, load_used

    def _assign_trip(tag: str, info: Dict[str, Any], load: float, tariff: Dict[str, Any], base_cost: float) -> bool:
        nonlocal weight_left

        items_loaded, meta_loaded, real_weight = _allocate_items_for_trip(load)
        if real_weight <= 0 and weight_left > 0:
            return False
        
        tariff_name_norm = _norm_str(tariff.get("название") or tariff.get("name") or "")
        trip_cost = base_cost
        if "daf" in tariff_name_norm:
            trip_cost = _calc_daf_step_cost(base_cost, meta_loaded)

        trips.append(
            {
                "tag": tag,
                "tariff_name": tariff.get("название") or tariff.get("name") or tag,
                "tariff_label": _tariff_label(tariff),
                "trip_cost": trip_cost,
                "load_ton": round(real_weight, 2),
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

            weight_if = info.get("weight_if", "any")
            if weight_if == "≤20" and load > 20:
                continue
            if weight_if == ">20" and load <= 20:
                continue

            cost = _trip_cost(info["tariff"], distance_km)
            eff_cpt = cost / load if load > 0 else float("inf")
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

def _daf_plan(
    items: List[Dict[str, Any]],
    distance_km: float,
    tariffs: List[Dict[str, Any]],
    require_manipulator: bool,
) -> Optional[Dict[str, Any]]:
    """Расчёт с опорой на DAF (ступенчатый тариф по special_threshold)."""
    daf_capacity = 55.0
    daf_tariff = _select_tariff_for_load(
        tariffs, "long_haul", distance_km, 30, name_contains="daf"
    )
    if not daf_tariff:
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

            # Корректно ограничиваем загрузку вместимостью DAF с учётом плавающей арифметики
            if weight_per_item > 0:
                max_by_capacity = int((daf_capacity + 1e-6) / weight_per_item)
                if max_by_capacity <= 0:
                    max_by_capacity = 1
                load_items = min(load_items, max_by_capacity)

            load_weight = weight_per_item * load_items
            if load_weight > daf_capacity + 1e-6 and load_items > 1:
                load_items -= 1
                load_weight = weight_per_item * load_items
            load_weight = min(load_weight, daf_capacity)

            trip_tariff = _select_tariff_for_load(
                tariffs, "long_haul", distance_km, load_weight, name_contains="daf"
            )
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
                    "tariff_label": _tariff_label(trip_tariff),
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
                "tariff_label": _tariff_label(mani_tariff),
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
    scenario_factories = (best_result.get("scenario") or {}).get("factories") or {}

    for f_plan in best_result.get("factory_plans", []):
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

        rows.append(
            {
                "завод": factory_name,
                "контакт": contact,
                "товар": "; ".join(products) or "—",
                "машина": machine_desc,
                "расстояние_км": distance,
                "стоимость_материала": material_cost,
                "стоимость_доставки": delivery_cost,
                "итого": round(material_cost + delivery_cost, 2),
            }
        )

    return rows

def build_trip_items_details(best_result):
    """Возвращает детализацию погрузки по каждой машине."""

    trip_rows = []
    for f_plan in best_result.get("factory_plans", []):
        factory_name = f_plan.get("factory_name")
        for trip in f_plan.get("trips", []):
            trip_rows.append(
                {
                    "завод": factory_name,
                    "машина": trip.get("tariff_name") or trip.get("tag"),
                    "тариф": trip.get("tariff_label") or trip.get("tariff_name"),
                    "расстояние_км": round(trip.get("distance_km", 0), 2),
                    "загрузка_т": round(trip.get("load_ton", 0), 2),
                    "товары": "; ".join(trip.get("items") or []),
                    "стоимость_доставки": round(trip.get("trip_cost", 0), 2),
                }
            )

    return trip_rows
