from backend.service.factories_service import (
    _norm_str,
    _to_float,
    _detect_standard_for_factory_items,
    _plan_special_single_heavy_long_haul,
    calculate_tariff_cost,
    set_current_tariffs,
)
from backend.service.osrm_client import get_osrm_distance_km  # ✅ расстояния через OSRM
import math
import logging
log = logging.getLogger(__name__)


import math
from typing import Any, Dict, List, Optional

from .osrm_client import get_osrm_distance_km

logger = logging.getLogger(__name__)


def evaluate_scenario_transport(
    scenario: Dict[str, Any],
    req,
    calc_tariffs: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """
    Считает варианты доставки для одного сценария.

    Ожидаем, что scenario имеет структуру (из build_factory_scenarios):

    {
        "scenario_id": int,
        "factories": {
            "<имя завода>": [
                {
                    "product": {...}  # товар из factories_products.json
                    "count": int,     # количество
                    "weight_total": float,  # общий вес этой позиции
                    "price": float,   # цена за 1 шт
                    "factory": {      # мета завода
                        "name": str,
                        "lat": float,
                        "lon": float,
                        "contact": str,
                        "price": float
                    },
                    ...
                },
                ...
            ]
        },
        ...
    }
    """

    if not calc_tariffs:
        logger.warning("⚠️ calc_tariffs пуст или None, расчёт невозможен.")
        return []

    factories_map = scenario.get("factories") or {}
    if not factories_map:
        logger.warning("⚠️ В сценарии нет ни одного завода: %s", scenario)
        return []

    results: List[Dict[str, Any]] = []

    for factory_name, items in factories_map.items():
        if not items:
            continue

        # 1. Координаты завода
        f_obj = items[0].get("factory") or {}
        lat = f_obj.get("lat")
        lon = f_obj.get("lon")

        if lat is None or lon is None:
            logger.warning(
                "⚠️ У завода %s отсутствуют координаты: lat=%s, lon=%s, f_obj=%r",
                factory_name,
                lat,
                lon,
                f_obj,
            )
            continue

        # 2. Расстояние до точки выгрузки через OSRM
        distance_km = get_osrm_distance_km(
            lon,
            lat,
            req.upload_lon,
            req.upload_lat,
        )
        if distance_km is None:
            logger.warning(
                "⚠️ Не удалось получить расстояние до клиента для завода %s",
                factory_name,
            )
            continue

        # 3. Вес и стоимость материалов
        total_weight = 0.0
        material_cost = 0.0
        items_payload: List[Dict[str, Any]] = []

        for x in items:
            prod = x.get("product") or {}
            qty = x.get("count", 0) or 0
            price_per_item = x.get("price", 0.0) or 0.0
            weight_total = x.get("weight_total", 0.0) or 0.0

            total_weight += weight_total
            material_cost += price_per_item * qty

            items_payload.append(
                {
                    "category": prod.get("category"),
                    "subtype": prod.get("subtype"),
                    "quantity": qty,
                    "weight_per_item": prod.get("weight_per_item"),
                    "weight_total": weight_total,
                    "price_per_item": price_per_item,
                    "factory_name": factory_name,
                }
            )

        if total_weight <= 0:
            logger.warning(
                "⚠️ Сценарий с заводом %s имеет нулевой вес, пропускаем.",
                factory_name,
            )
            continue

        # 4. Фильтрация тарифов по типу техники / спецтехнике
        tariffs = calc_tariffs

        # Если выбран спецтранспорт — смотрим только его (tag совпадает)
        selected_special = getattr(req, "selected_special", "") or ""
        if selected_special:
            tariffs = [t for t in tariffs if t.get("tag") == selected_special]

        # Если пользователь явно выбрал тип транспорта
        transport_type = getattr(req, "transport_type", "auto")
        if transport_type in ("manipulator", "long_haul", "special"):
            tariffs = [t for t in tariffs if t.get("tag") == transport_type]

        if not tariffs:
            logger.warning(
                "⚠️ Нет подходящих тарифов для завода %s после фильтрации.",
                factory_name,
            )
            continue

        # 5. Перебираем тарифы и считаем стоимость
        for tariff in tariffs:
            try:
                min_d = float(tariff.get("min_distance", 0.0) or 0.0)
                max_d = float(tariff.get("max_distance", 0.0) or 0.0)
                base = float(tariff.get("base", 0.0) or 0.0)
                per_km = float(tariff.get("per_km", 0.0) or 0.0)
                capacity = float(tariff.get("грузоподъёмность", 0.0) or 0.0)
            except Exception as e:
                logger.warning("⚠️ Некорректный тариф %r: %s", tariff, e)
                continue

            weight_if = (tariff.get("weight_if") or "any").strip()

            # --- проверка по расстоянию ---
            use_row = False
            if max_d and max_d != min_d:
                # обычный диапазон, напр. 0–30, 30–60, 60–80 и т.п.
                if min_d <= distance_km <= max_d:
                    use_row = True
            elif max_d == min_d and max_d > 0:
                # строка вида 120 / 120 — это ">= 120 км" с доплатой per_km
                if distance_km >= max_d:
                    use_row = True
            else:
                # если в данных нули — считаем, что строка универсальная
                use_row = True

            if not use_row:
                continue

            # --- проверка по весу ---
            if weight_if == "≤20" and total_weight > 20:
                continue
            if weight_if == ">20" and total_weight <= 20:
                continue
            # weight_if == "any" — подходит всегда

            # --- стоимость одного рейса ---
            trip_cost = base
            # Особый случай: строка вида 120 / 120 и есть per_km
            if (
                per_km
                and max_d == min_d
                and max_d > 0
                and distance_km > max_d
            ):
                extra_km = max(0.0, distance_km - max_d)
                trip_cost = base + per_km * extra_km

            # Считаем количество рейсов по грузоподъёмности
            if capacity > 0:
                trips = int(math.ceil(total_weight / capacity))
            else:
                trips = 1

            transport_cost = trip_cost * max(trips, 1)
            total_cost = material_cost + transport_cost

            results.append(
                {
                    "factory_name": factory_name,
                    "factory_lat": lat,
                    "factory_lon": lon,
                    "distance_km": distance_km,
                    "tariff_name": tariff.get("название"),
                    "tariff_tag": tariff.get("tag"),
                    "tariff_description": tariff.get("описание"),
                    "tariff_notes": tariff.get("заметки"),
                    "tariff_min_distance": min_d,
                    "tariff_max_distance": max_d,
                    "tariff_capacity": capacity,
                    "tariff_per_km": per_km,
                    "trips": trips,
                    "material_cost": material_cost,
                    "transport_cost": transport_cost,
                    "total_cost": total_cost,
                    "items": items_payload,
                }
            )

    if not results:
        log.warning("⚠️ Нет валидных результатов с total_cost — проверь фильтрацию сценариев")
        return {"results": [], "error": "no_valid_results"}

    return results


def build_shipment_details_from_result(best_result, req):
    """
    Формирует список 'детали' для ответа /quote,
    распределяя стоимость доставки пропорционально весу.
    """
    scenario = best_result["scenario"]
    factories_map = scenario["factories"]
    factory_distances = best_result["factory_distances"]

    # сначала собираем все строки без стоимости доставки
    rows = []
    for fname, items in factories_map.items():
        print(f"🏭 Завод: {fname}, товаров: {len(items)}")
        dist = factory_distances.get(fname, 0.0)
        for x in items:
            f_obj = x["factory"]
            p = x.get("product") or x
            qty = x["quantity"]
            weight = x["weight_total"]
            mat_cost = (p.get("price") or 0) * qty

            rows.append({
                "товар": f"{p['category']} ({p['subtype']})",
                "завод": fname,
                "машина": best_result["transport_name"],
                "tag": req.transport_type,
                "реальное_имя_машины": best_result["transport_name"],
                "кол-во": qty,
                "вес_тонн": round(weight, 2),
                "расстояние_км": round(dist, 2),
                "стоимость_материала": mat_cost,
                "стоимость_доставки": 0.0,  # пока 0, заполним ниже
                "тариф": "",
                "итого": 0.0,
            })

    total_weight = sum(r["вес_тонн"] for r in rows) or 1.0
    delivery_cost = best_result["delivery_cost"]

    # описание тарифа — просто склейка описаний из рейсов
    desc_parts = []
    for t in best_result["plans"]:
        d = (t.get("описание") or "").strip()
        if d and d not in desc_parts:
            desc_parts.append(d)
    tariff_desc = " + ".join(desc_parts)

    # распределяем стоимость доставки по весу
    for r in rows:
        share = (r["вес_тонн"] or 0.0) / total_weight
        r["стоимость_доставки"] = round(delivery_cost * share, 2)
        r["тариф"] = tariff_desc
        r["итого"] = round(r["стоимость_материала"] + r["стоимость_доставки"], 2)

    return rows

def calculate_daf_tariff(base_tariff: float, subtype: str, item_count: int):
    """Упрощённый расчёт тарифа для DAF 55т."""
    total_weight = item_count * 2.2  # предположительно 2.2т за плиту
    if total_weight > 55:
        return None, f"перегруз: {total_weight:.1f}т > 55т"
    return base_tariff, f"DAF тариф ({item_count} шт, {total_weight:.1f}т)"


def compute_best_plan(total_weight, distance_km, tariffs, allow_mani, selected_tag=None, require_one_mani=False):
    print(f"\n🔍 compute_best_plan: total_weight={total_weight}т, distance={distance_km} км, selected_tag={selected_tag}, allow_mani={allow_mani}, require_one_mani={require_one_mani}")
    print(f"   Тарифов получено: {len(tariffs)}")

    """
    Полный расчёт оптимального плана доставки.
    Манипулятор и длинномер участвуют на равных.
    Если выбран конкретный тип (selected_tag='manipulator' или 'long_haul'),
    подбираются только такие рейсы.
    Если require_one_mani=True — добавляем хотя бы один манипулятор.
    """
    import itertools 

    # === Нормализуем теги тарифов ===
    for t in tariffs:
        tag_val = (t.get("tag") or t.get("тег") or "").strip().lower()
        if "манипулятор" in tag_val:
            t["tag"] = "manipulator"
        elif "длинномер" in tag_val or "long_haul" in tag_val or "long" in tag_val:
            t["tag"] = "long_haul"

    # === Утилиты ===
    def tag_capacity(tag: str) -> float:
        """Возвращает максимальную грузоподъёмность по тегу"""
        caps = [
            _to_float(t.get("capacity_ton") or t.get("грузоподъёмность"))
            for t in tariffs
            if (t.get("tag") or t.get("тег")) == tag
        ]
        return max(caps) if caps else 0.0

    def make_trip_entry(tag, load, cost, desc):
        """Оформление одной машины"""
        real_name = next(
            (t.get("name") or t.get("название")
             for t in tariffs
             if (t.get("tag") == tag or t.get("тег") == tag)),
            tag
        )
        return {
            "тип": tag,
            "реальное_имя": real_name,
            "рейсы": 1,
            "вес_перевезено": round(load, 2),
            "стоимость": round(float(cost), 2),
            "описание": desc,
        }

    def plan_cost(plan):
        return sum(float(p["стоимость"]) for p in plan)

    # === Нормализация selected_tag ===
    if selected_tag:
        st = selected_tag.strip().lower()
        if st in ("manipulator", "манипулятор", "манипулятор "):
            selected_tag = "manipulator"
        elif st in ("длинномер", "long_haul", "long"):
            selected_tag = "long_haul"

    # === Определяем доступные теги ===
    if selected_tag in ("manipulator", "long_haul"):
        allowed_tags = [selected_tag]
    else:
        allowed_tags = ["long_haul"]
        if allow_mani:
            allowed_tags.append("manipulator")

    if not allowed_tags:
        return None, None

    # === Подготовка тарифов ===
    capacities = {tag: tag_capacity(tag) for tag in allowed_tags}
    print(f"   Доступные теги и грузоподъёмность: {capacities}")
    if not capacities or all(v <= 0 for v in capacities.values()):
        return None, None

    # === Функция для расчёта стоимости комбинации ===
    def evaluate_combo(combo_counts):
        print(f"      🔸 Проверяем комбинацию: {combo_counts}")
        total = 0.0
        plan = []
        weight_left = total_weight
        for tag, count in combo_counts.items():
            cap = capacities[tag]
            for i in range(count):
                if weight_left <= 0:
                    break
                load = min(weight_left, cap)
                # выбираем подходящий тариф по грузоподъемности
                matching_tariffs = [
                    t for t in tariffs
                    if (t.get("tag") == tag or t.get("тег") == tag)
                    and _to_float(t.get("capacity_ton") or t.get("грузоподъёмность") or 0) >= load
                ]

                # ❗ Гарантия выбора тарифа >20т
                # запрещаем подбор тарифа, если груз превышает его лимит
                matching_tariffs = [
                    t for t in matching_tariffs
                    if load <= _to_float(t.get("capacity_ton") or 0)
                ]
                print(f"         ➡️ {tag}: груз={load}, cap={cap}, найдено тарифов={len(matching_tariffs)}")
                if not matching_tariffs:
                    return None, None

                # берём ближайший по вместимости
                selected_tariff = min(
                    matching_tariffs,
                    key=lambda t: _to_float(t.get("capacity_ton") or t.get("грузоподъёмность") or 999)
                )

                cost, desc = calculate_tariff_cost(tag, distance_km, load)
                if not cost:
                    return None, None
                plan.append(make_trip_entry(tag, load, cost, desc))
                total += cost
                weight_left -= load
        if weight_left > 0.1:
            return None, None
        return total, plan

    # === Перебор комбинаций машин (до 5 рейсов суммарно) ===
    best_plan = None
    best_cost = float("inf")

    max_reisov = 5
    for n in range(1, max_reisov + 1):
        for combo in itertools.combinations_with_replacement(allowed_tags, n):
            combo_counts = {t: combo.count(t) for t in allowed_tags}
            total_weight_possible = sum(capacities[t] * combo_counts[t] for t in allowed_tags)
            print(f"   ⚖️ Комбинация {combo_counts}: вместимость={total_weight_possible} < нужно {total_weight}? -> {total_weight_possible < total_weight}")
            if total_weight_possible < total_weight:
                continue
            total, plan = evaluate_combo(combo_counts)
            if total and total < best_cost:
                best_cost = total
                best_plan = plan
    print(f"✅ Результат: best_cost={best_cost}, есть план={best_plan is not None}")

    # === Если ничего не подошло, вернём None ===
    if not best_plan:
        return None, None

    # === Если нужно гарантировать хотя бы один манипулятор ===
    if require_one_mani and "manipulator" in capacities:
        has_mani = any(p["тип"] == "manipulator" for p in best_plan)
        if not has_mani and total_weight > 0:
            mani_cap = capacities["manipulator"]
            mani_load = min(mani_cap, total_weight)
            cost, desc = calculate_tariff_cost("manipulator", distance_km, mani_load)
            mani_trip = make_trip_entry("manipulator", mani_load, cost, desc)

            # снимаем вес с последнего длинномера, если он есть
            taken = False
            for trip in reversed(best_plan):
                if trip["тип"] == "long_haul" and trip["вес_перевезено"] > mani_load:
                    trip["вес_перевезено"] -= mani_load
                    taken = True
                    break

            if not taken:
                # если длинномера нет или мало веса — оставляем план как есть и просто добавляем манипулятор
                pass

            best_plan.append(mani_trip)
            best_plan = [p for p in best_plan if p["вес_перевезено"] > 0]
            best_cost = plan_cost(best_plan)

    best_human = ", ".join(sorted({t["реальное_имя"] for t in best_plan}))
    return best_cost, {"транспорт_детали": {"доп": best_plan}, "транспорт": best_human}

