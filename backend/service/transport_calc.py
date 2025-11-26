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


def evaluate_scenario_transport(scenario, req, calc_tariffs):
    def _extend_result(base_dict):
        trips = base_dict.get("plans", [])
        base_dict["trip_count"] = len(trips)
        base_dict["transport_details"] = {
            "доп": [
                {
                    "тип": t.get("тип"),
                    "реальное_имя": t.get("реальное_имя"),
                    "вес_перевезено": t.get("вес_перевезено"),
                    "стоимость": t.get("стоимость"),
                    "описание": t.get("описание", ""),
                }
                for t in trips
            ]
        }
        return base_dict
    
    factories_map = scenario["factories"]
    total_weight = scenario["total_weight"]

    if total_weight <= 0:
        return None

    # --- подготовка ограничений по типам транспорта ---
    forbidden = set((req.forbidden_types or []))

    # выбрали спецтранспорт? тогда игнорируем манипуляторы/длинномеры
    use_special = bool(req.selected_special and req.selected_special != "Не выбирать")

    # фильтруем тарифы по запретам
    usable_tariffs = [
        t for t in calc_tariffs
        if str(t.get("tag") or "").strip().lower() not in forbidden
    ]

    if not usable_tariffs:
        print("⚠️ Нет доступных тарифов после фильтрации по forbidden_types")
        return None
    else:
        print(f"✅ Тарифов доступно после фильтрации: {len(usable_tariffs)}")

    # сообщаем factories_service, по каким тарифам нужно считать
    set_current_tariffs(usable_tariffs)

    # helper: расстояние от завода до клиента
    factory_distances = {}
    material_sum = 0.0

    # соберём данные по заводам
    factories_info = []  # список {name, weight, distance, material_cost, items}

    for fname, items in factories_map.items():
        # берём первый объект завода (везде один и тот же)
        f_obj = items[0]["factory"]
        lat = f_obj.get("lat")
        lon = f_obj.get("lon")

        dist = get_osrm_distance_km(lon, lat, req.upload_lon, req.upload_lat)
        factory_distances[fname] = dist
        print(f"  📍 расстояние до клиента: {dist} км")

        weight = sum(x["weight_total"] for x in items)
        mat_cost = 0.0
        for x in items:
            p = x["product"]
            qty = x["quantity"]
            price = p.get("price") or 0
            mat_cost += price * qty

        material_sum += mat_cost

        factories_info.append({
            "name": fname,
            "factory": f_obj,
            "items": items,
            "weight": weight,
            "distance": dist,
            "material_cost": mat_cost,
        })

    # === Ветка: выбран конкретный спецтранспорт ===
    if use_special:
        special_name_norm = _norm_str(req.selected_special)
        special_tariff = next(
            (t for t in usable_tariffs if _norm_str(t.get("name")) == special_name_norm),
            None
        )
        if not special_tariff:
            print(f"⚠️ Не найден спецтранспорт '{req.selected_special}'")
            return None

        cap_t = _to_float(special_tariff.get("capacity_ton") or 0) or 1.0
        tag = special_tariff.get("tag") or special_tariff.get("тег") or "special"

        all_trips = []
        delivery_cost = 0.0

        for finfo in factories_info:
            weight_left = finfo["weight"]
            dist = finfo["distance"]

            while weight_left > 0:
                load = min(cap_t, weight_left)
                # --- особая логика для длинномера DAF (55т) ---
                if "DAF" in (special_tariff.get("name") or "") and any("ФБС" in (it["subtype"] or "") for it in req.items):
                    subtype = req.items[0]["subtype"]
                    item_count = req.items[0]["quantity"]
                    base_tariff = float(special_tariff.get("base_cost") or special_tariff.get("цена") or 0)
                    cost_per_trip, desc = calculate_daf_tariff(base_tariff, subtype, item_count)
                else:
                    cost_per_trip, desc = calculate_tariff_cost(tag, dist, load)
                if not cost_per_trip:
                    return None

                all_trips.append({
                    "тип": "special",
                    "реальное_имя": special_tariff.get("name"),
                    "рейсы": 1,
                    "вес_перевезено": round(load, 2),
                    "стоимость": round(float(cost_per_trip), 2),
                    "описание": desc or "",
                })
                delivery_cost += float(cost_per_trip)
                weight_left -= load

        transport_name = special_tariff.get("name")
        total_cost = material_sum + delivery_cost

        return _extend_result({
            "scenario": scenario,
            "material_sum": material_sum,
            "delivery_cost": delivery_cost,
            "total_cost": total_cost,
            "plans": all_trips,
            "transport_name": transport_name,
            "factory_distances": factory_distances,
        })

    # === Обычный режим: манипы / длинномеры / auto ===

    # определяем, что пользователь задал
    ttype = (req.transport_type or "auto").strip().lower()

    if ttype == "manipulator":
        selected_tag = "manipulator"
        allow_mani = True
    elif ttype == "long_haul":
        selected_tag = "long_haul"
        # манипулятор возможен только как "+1", через require_one_mani в compute_best_plan
        allow_mani = True
    else:
        # auto — даём свободу комбинировать оба типа
        selected_tag = None
        allow_mani = True

    # --- для "+1 манипулятор" будем считать по двум вариантам на каждый завод ---
    per_factory_variants = []  # [{name, no_mani, with_mani}]

    for finfo in factories_info:
        fname = finfo["name"]
        weight = finfo["weight"]
        dist = finfo["distance"]

        # --- Проверяем особый тариф для конкретного товара ---
        # Берём первый продукт из списка (предполагаем, что завод поставляет один тип)
        if finfo["items"]:
            item = finfo["items"][0]["product"]
            qty = finfo["items"][0]["quantity"]
            print(f"   🔎 Проверяем спецтариф: {item['subtype']} (qty={qty})")

        # если веса нет — пропускаем
        if weight <= 0:
            continue

        # --- 4.1. пробуем спец-логику 44–55 / 41–55 / 42–55 для длинномера ---
        std_info = _detect_standard_for_factory_items(finfo["items"])
        special_cost_no = None
        special_plan_no = None

        if std_info:
            special_cost_no, special_plan_no = _plan_special_single_heavy_long_haul(
                finfo, std_info, req, usable_tariffs
            )

        if special_cost_no is not None and special_plan_no is not None:
            # спец-логика отработала — этот завод считаем ТОЛЬКО так,
            # без compute_best_plan (чтобы не было конфликтов)
            cost_no = special_cost_no
            plan_pack_no = special_plan_no

            # вариант с обязательным манипулятором здесь пока не поддерживаем,
            # чтобы не усложнять — можно добавить позже отдельной веткой
            cost_with = None
            plan_pack_with = None

        else:
            # --- 4.2. обычная логика через compute_best_plan ---
            cost_no, plan_pack_no = compute_best_plan(
                weight,
                dist,
                usable_tariffs,
                allow_mani=allow_mani,
                selected_tag=selected_tag,
                require_one_mani=False
            )

            # по умолчанию вариант с манипулятором отсутствует
            cost_with = None
            plan_pack_with = None

            # если пользователь отметил "+1 манипулятор" и тип транспорта не pure-manipulator
            if req.add_manipulator and ttype != "manipulator":
                cost_with, plan_pack_with = compute_best_plan(
                    weight,
                    dist,
                    usable_tariffs,
                    allow_mani=allow_mani,
                    selected_tag=selected_tag,
                    require_one_mani=True
                )
        print(f"⚙️ План по {fname}: cost_no={cost_no}, cost_with={cost_with}")

        if cost_no is None and cost_with is None:
            # с этим заводом сценарий нереализуем
            return None

        per_factory_variants.append({
            "name": fname,
            "distance": dist,
            "weight": weight,
            "material_cost": finfo["material_cost"],
            "no_mani": (cost_no, plan_pack_no),
            "with_mani": (cost_with, plan_pack_with),
        })


    # === собираем итоговый план по сценарию ===

    def extract_trips(plan_pack):
        if not plan_pack:
            return []
        return (plan_pack or {}).get("транспорт_детали", {}).get("доп", []) or []

    # если "+1 манипулятор" НЕ включён — просто берём самые дешёвые варианты по каждому заводу
    if not req.add_manipulator or ttype == "manipulator":
        all_trips = []
        delivery_cost = 0.0

        for v in per_factory_variants:
            cost_no, pack_no = v["no_mani"]
            cost_with, pack_with = v["with_mani"]

            # выбираем существующий и более дешёвый
            if cost_no is None and cost_with is not None:
                use_cost, use_pack = cost_with, pack_with
            elif cost_with is None and cost_no is not None:
                use_cost, use_pack = cost_no, pack_no
            else:
                # оба есть — берём минимальный
                if cost_with is not None and cost_with < cost_no:
                    use_cost, use_pack = cost_with, pack_with
                else:
                    use_cost, use_pack = cost_no, pack_no

            # --- Проверяем, есть ли для завода спец-тариф ---
            finfo = next((f for f in factories_info if f["name"] == v["name"]), None)
            if finfo and "adjusted_delivery_cost" in finfo:
                delivery_cost += finfo["adjusted_delivery_cost"]
                all_trips.extend(finfo.get("adjusted_trips_list", []))
                print(...)
            else:
                delivery_cost += float(use_cost or 0)

            all_trips.extend(extract_trips(use_pack))

        if not all_trips:
            print(f"❌ Нет ни одного рейса (заводы={len(per_factory_variants)})")
            return None

        transport_name = ", ".join(sorted({t["реальное_имя"] for t in all_trips}))
        total_cost = material_sum + delivery_cost

        return _extend_result({
            "scenario": scenario,
            "material_sum": material_sum,
            "delivery_cost": delivery_cost,
            "total_cost": total_cost,
            "plans": all_trips,
            "transport_name": transport_name,
            "factory_distances": factory_distances,
        })


    # === режим: нужен хотя бы один манипулятор глобально (+1 манипулятор) ===

    best_total = None
    best_trips = None

    # пробуем сделать "манипулятор живёт на заводе k"
    for k, vk in enumerate(per_factory_variants):
        all_trips_k = []
        total_delivery_k = 0.0

        has_mani_here = False

        for idx, v in enumerate(per_factory_variants):
            # на заводе k стараемся использовать вариант with_mani
            if idx == k:
                cost_with, pack_with = v["with_mani"]
                if cost_with is not None:
                    use_cost, use_pack = cost_with, pack_with
                else:
                    use_cost, use_pack = v["no_mani"]
            else:
                # на остальных — берём более дешёвый без учёта манипулятора
                cost_no, pack_no = v["no_mani"]
                cost_with, pack_with = v["with_mani"]
                if cost_no is None and cost_with is not None:
                    use_cost, use_pack = cost_with, pack_with
                elif cost_with is None and cost_no is not None:
                    use_cost, use_pack = cost_no, pack_no
                else:
                    if cost_with is not None and cost_with < cost_no:
                        use_cost, use_pack = cost_with, pack_with
                    else:
                        use_cost, use_pack = cost_no, pack_no

            if use_cost is None:
                all_trips_k = None
                break

            trips_here = extract_trips(use_pack)
            all_trips_k.extend(trips_here)
            total_delivery_k += float(use_cost or 0)

        if not all_trips_k:
            continue

        # проверим, что в плане вообще есть манипулятор
        if not any("manipulator" in (t.get("тип") or "") for t in all_trips_k):
            continue

        if best_total is None or total_delivery_k < best_total:
            best_total = total_delivery_k
            best_trips = all_trips_k

    # если так и не нашли валидный план с манипулятором — откатываемся к варианту без требования
    if best_trips is None:
        # просто берём минимальные комбинации по заводам
        all_trips = []
        delivery_cost = 0.0
        for v in per_factory_variants:
            cost_no, pack_no = v["no_mani"]
            delivery_cost += float(cost_no or 0)
            all_trips.extend(extract_trips(pack_no))
        if not all_trips:
            print("❌ evaluate_scenario_transport вернул None (нет подходящих тарифов или ошибка в планах)")
            return None
        transport_name = ", ".join(sorted({t["реальное_имя"] for t in all_trips}))
        total_cost = material_sum + delivery_cost
        return _extend_result({
            "scenario": scenario,
            "material_sum": material_sum,
            "delivery_cost": delivery_cost,
            "total_cost": total_cost,
            "plans": all_trips,
            "transport_name": transport_name,
            "factory_distances": factory_distances,
        })

    # успех: есть план с манипулятором
    transport_name = ", ".join(sorted({t["реальное_имя"] for t in best_trips}))
    total_cost = material_sum + best_total

    result = {
        "scenario": scenario,
        "material_sum": material_sum,
        "delivery_cost": best_total,
        "total_cost": total_cost,
        "plans": best_trips,
        "transport_name": transport_name,
        "factory_distances": factory_distances,
    }
    print(f"✅ Успешный расчёт сценария: total_cost={result['total_cost']}, delivery={result['delivery_cost']}, рейсов={len(result['plans'])}")
    return _extend_result(result)



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
            p = x["product"]
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

