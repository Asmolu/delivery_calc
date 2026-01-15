"""Transport planning and tariff selection utilities."""

from typing import Any, Dict, List, Optional, Tuple
import math
from backend.core.logger import get_logger
from backend.service.factories_service import _norm_str, _to_float
from backend.service.osrm_client import OSRMUnavailableError, get_osrm_distance_km

logger = get_logger(__name__)


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


def _radius_ok(tariff: Dict[str, Any], distance_km: float) -> bool:
    r = tariff.get("radius_limit_km", None)
    if r is None:
        return True
    rr = _to_float(r)
    if rr <= 0:
        return True
    return distance_km <= rr + 1e-9


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in km."""
    R = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def _radius_ok_with_center(
    tariff: Dict[str, Any],
    distance_km: float,
    upload_lat: Optional[float],
    upload_lon: Optional[float],
) -> bool:
    """Проверка радиуса:
    - если задан центр (radius_center_lat/lon) и есть координаты выгрузки — считаем по прямой (haversine)
    - иначе fallback: сравниваем с distance_km (как раньше)
    """
    r = tariff.get("radius_limit_km", None)
    if r is None:
        return True
    rr = _to_float(r)
    if rr <= 0:
        return True

    clat = tariff.get("radius_center_lat", None)
    clon = tariff.get("radius_center_lon", None)
    if clat is not None and clon is not None and upload_lat is not None and upload_lon is not None:
        try:
            d = _haversine_km(float(clat), float(clon), float(upload_lat), float(upload_lon))
            return d <= rr + 1e-9
        except Exception:
            # fallback
            return distance_km <= rr + 1e-9

    return distance_km <= rr + 1e-9


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
    upload_lat: Optional[float],
    upload_lon: Optional[float],
) -> bool:
    """Проверяет, применим ли тариф к расстоянию с учётом “последнего диапазона” и радиуса."""
    if not bool(tariff.get("is_active", True)):
        return False

    if not _radius_ok_with_center(tariff, distance_km, upload_lat, upload_lon):
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


def _tariff_label(tariff: Dict[str, Any]) -> str:
    """Читабельная подпись выбранного тарифа."""

    name = tariff.get("название") or tariff.get("name") or "Тариф"
    descr = tariff.get("описание") or tariff.get("description") or ""
    if descr:
        return f"{name} — {descr}"

    min_d = _to_float(tariff.get("min_distance"))
    max_d = _to_float(tariff.get("max_distance"))
    cond, thr = _parse_weight_rule(tariff)

    range_descr = ""
    if max_d and max_d != min_d:
        range_descr = f"{min_d}-{max_d} км"
    elif max_d > 0 and max_d == min_d:
        range_descr = f"{min_d}-{max_d} км"
    elif max_d > 0:
        range_descr = f"{min_d}-{max_d} км"
    elif min_d > 0:
        range_descr = f">={min_d} км"

    weight_descr = ""
    if cond == "le":
        weight_descr = f"≤{thr}т" if thr is not None else "≤?"
    elif cond == "gt":
        weight_descr = f">{thr}т" if thr is not None else ">?"

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
    group_max_distance: Dict[Tuple[str, str, str, Optional[float]], float],
    upload_lat: Optional[float],
    upload_lon: Optional[float],
    name_contains: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Возвращает лучшую строку тарифа под указанный тег/нагрузку."""
    candidates = []
    for t in tariffs:
        if _norm_str(t.get("tag")) != _norm_str(tag):
            continue
        if not _distance_matches_tariff(t, distance_km, group_max_distance, upload_lat, upload_lon):
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
    upload_lat: Optional[float],
    upload_lon: Optional[float],
) -> Optional[Dict[str, Any]]:
    """Жадно заполняем самыми выгодными машинами, сравнивая тарифы по цене/тонне."""
    candidates: List[Dict[str, Any]] = []

    for t in tariffs:
        tag = _norm_str(t.get("tag"))
        if tag not in allowed_tags:
            continue
        if not _distance_matches_tariff(t, distance_km, group_max_distance, upload_lat, upload_lon):
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

    def _allocate_items_for_trip(load_limit: float) -> Tuple[List[str], float]:
        """Возвращает список товаров, помещённых в рейс, их мета и фактический вес.

        ВАЖНО (бизнес-правило): в одной машине нельзя смешивать разные категории.
        Поэтому один вызов аллоцирует товары только из ОДНОЙ категории.
        """

        assigned: List[str] = []
        load_used = 0.0
        if load_limit <= 0:
            return assigned, load_used

        # Выбираем категорию для этого рейса: берём ту, у которой больше всего
        # оставшегося веса (или количества, если веса нет).
        cat_candidates = []
        for it in remaining_items:
            qty_left = _to_float(it.get("remaining_qty", 0))
            if qty_left <= 0:
                continue
            wpi = _to_float(it.get("weight_per_item"))
            cat = it.get("category")
            if not cat:
                continue
            cat_candidates.append((cat, qty_left * (wpi if wpi > 0 else 1.0)))

        if not cat_candidates:
            return assigned, load_used

        # категория с максимальным “объёмом” к отгрузке
        target_category = max(cat_candidates, key=lambda x: x[1])[0]

        for item in remaining_items:
            if load_limit - load_used < 0.01:
                break

            if (item.get("category") or "") != target_category:
                continue

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
        return assigned, load_used

    def _assign_trip(tag: str, info: Dict[str, Any], load: float, tariff: Dict[str, Any], base_cost: float) -> bool:
        nonlocal weight_left

        items_loaded, real_weight = _allocate_items_for_trip(load)
        if real_weight <= 0 and weight_left > 0:
            return False
        
        trips.append(
            {
                "tag": tag,
                "tariff_name": tariff.get("название") or tariff.get("name") or tag,
                "tariff_label": _tariff_label(tariff),
                "trip_cost": base_cost,
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

            if not _weight_ok(info["tariff"], load):
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

    transport_type = _norm_str(getattr(req, "transport_type", "auto"))
    add_manipulator = bool(getattr(req, "add_manipulator", False) or getattr(req, "addManipulator", False))

    delivery_transport_tag = _norm_str(getattr(req, "delivery_transport_tag", None) or getattr(req, "deliveryTransportTag", None) or "auto")
    unloading_transport_tag = _norm_str(getattr(req, "unloading_transport_tag", None) or getattr(req, "unloadingTransportTag", None) or "auto")

    delivery_tags = ["long_haul", "container_carrier", "flatbed"]
    all_tags = delivery_tags + ["manipulator", "crane"]

    # Доставка: если явно выбран тег — используем его, иначе fallback на старое transport_type
    if delivery_transport_tag and delivery_transport_tag != "auto":
        allowed_tags = [delivery_transport_tag] if delivery_transport_tag in all_tags else delivery_tags + ["manipulator"]
        require_mani = False
    else:
        # legacy route
        if transport_type == "manipulator":
            allowed_tags = ["manipulator"]
            require_mani = add_manipulator
        elif transport_type == "long_haul":
            allowed_tags = delivery_tags + (["manipulator"] if add_manipulator else [])
            require_mani = add_manipulator
        else:
            allowed_tags = delivery_tags + ["manipulator"]
            require_mani = add_manipulator

    factory_plans: List[Dict[str, Any]] = []
    total_material = 0.0
    total_delivery = 0.0
    unloading_cost_total = 0.0
    factory_distances: Dict[str, float] = {}

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
        if linear_allowed:
            linear_plan = _linear_plan(
                total_weight,
                distance_km,
                calc_tariffs,
                linear_allowed,
                require_mani,
                items,
                group_max_distance,
                getattr(req, "upload_lat", None),
                getattr(req, "upload_lon", None),
            )
            if linear_plan:
                plans.append(linear_plan)

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

    # Добавляем стоимость разгрузки (один раз на заказ/точку выгрузки), если выбрано
    try:
        if unloading_transport_tag and unloading_transport_tag != "none":
            unloading_tariffs = [t for t in (calc_tariffs or []) if _norm_str(t.get("service_type")) == "unloading"]
            if unloading_tariffs:
                # total weight for unloading selection
                scenario_total_weight = sum(
                    _to_float(it.get("weight_total") or (it.get("weight_per_item") or 0) * (it.get("quantity") or it.get("count") or 0))
                    for items in factories_map.values()
                    for it in (items or [])
                )

                # helper: choose best unloading row
                def _best_unloading_for_tag(tag: str) -> Optional[Dict[str, Any]]:
                    tag_norm = _norm_str(tag)
                    candidates = []
                    for tt in unloading_tariffs:
                        if tag_norm and tag_norm != "auto" and _norm_str(tt.get("tag")) != tag_norm:
                            continue
                        if not _distance_matches_tariff(
                            tt,
                            0.0,
                            group_max_distance,
                            getattr(req, "upload_lat", None),
                            getattr(req, "upload_lon", None),
                        ):
                            continue
                        if not _weight_ok(tt, scenario_total_weight):
                            continue
                        candidates.append(tt)
                    if not candidates:
                        return None
                    return min(candidates, key=lambda x: _to_float(x.get("base")))

                if unloading_transport_tag == "auto":
                    best_unload = _best_unloading_for_tag("auto")
                else:
                    best_unload = _best_unloading_for_tag(unloading_transport_tag)

                if best_unload:
                    unloading_cost_total = _to_float(best_unload.get("base"))
    except Exception as e:
        logger.warning("⚠️ Не удалось применить разгрузку: %s", e)

    total_cost = total_material + total_delivery
    if unloading_cost_total:
        total_delivery += unloading_cost_total
        total_cost += unloading_cost_total
    trip_count = sum(len(f["trips"]) for f in factory_plans)
    transport_names = sorted(
        {
            t.get("tariff_label")
            or t.get("tariff_name")
            or t.get("tag")
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

def build_trip_items_details(best_result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Возвращает детализацию погрузки по каждой машине."""

    trip_rows = []
    for f_plan in best_result.get("factory_plans", best_result.get("factories", [])):
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
