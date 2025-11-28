from typing import List, Any, Dict
from backend.core.logger import get_logger
from itertools import product


log = get_logger("scenario_builder")


def build_factory_scenarios(factories_products: dict, items: list):
    """
    Создаёт возможные сценарии закупки и доставки
    под формат нового парсера (dict: category -> [товары с полем factory]).
    """

    scenarios = []

    # Словарь: { factory_name: {category: [товары...] } }
    factories_index = {}

    # 1️⃣ Построим индекс фабрик из новых данных
    for category, products in factories_products.items():
        for product in products:
            factory = product.get("factory", {})
            factory_name = factory.get("name")
            if not factory_name:
                continue

            if factory_name not in factories_index:
                factories_index[factory_name] = {
                    "name": factory_name,
                    "lat": factory.get("lat"),
                    "lon": factory.get("lon"),
                    "contact": factory.get("contact"),
                    "products": []
                }

            # Объединяем товар в индекс
            factories_index[factory_name]["products"].append({
                "category": category,
                "subtype": product.get("subtype"),
                "weight_per_item": product.get("weight_per_item"),
                "special_threshold": product.get("special_threshold"),
                "max_per_trip": product.get("max_per_trip"),
                "price": factory.get("price"),
            })

    # 2️⃣ Теперь соберём сценарии "все нужные товары из одного завода"
    scenario_id = 0

    for factory_name, factory_data in factories_index.items():
        available_products = factory_data.get("products", [])
        scenario_positions = []
        total_weight = 0.0
        all_present = True

        for req_item in items:
            # Найдём совпадение по категории и subtype
            matched = next(
                (
                    p for p in available_products
                    if p["category"] == req_item.category
                    and p["subtype"] == req_item.subtype
                ),
                None
            )

            if not matched:
                all_present = False
                break  # этот завод не может обеспечить весь набор

            weight_total = (matched["weight_per_item"] or 0) * req_item.quantity
            total_weight += weight_total

            scenario_positions.append({
                "factory": {
                    "name": factory_name,
                    "lat": factory_data["lat"],
                    "lon": factory_data["lon"],
                    "contact": factory_data["contact"],
                },
                "category": matched["category"],
                "subtype": matched["subtype"],
                "price": matched["price"],
                "weight_total": weight_total,
                "count": req_item.quantity,
            })

        if all_present and scenario_positions:
            scenario_id += 1
            scenarios.append({
                "scenario_id": scenario_id,
                "factories": {factory_name: scenario_positions},
                "total_weight": total_weight,
            })

    return scenarios


def build_factory_scenarios_v2(
    factories_products: List[Dict[str, Any]],
    items: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Генерация всех осмысленных комбинаций товаров по заводам
    под формат НОВОГО парсера, где структура такая:

    {
        "category": "ФБС БЛОКИ",
        "subtype": "ФБС 9-3-6",
        "weight_per_item": 0.35,
        "special_threshold": 0.0,
        "max_per_trip": 0.0,
        "factory": {
            "name": "дмитровский мжбк",
            "lat": 56.331169,
            "lon": 37.540919,
            "price": 1090.0,
            "contact": "..."
        }
    }
    """

    # --- 1. Индекс по (category, subtype) ---
    catalog: Dict[tuple, List[Dict[str, Any]]] = {}
    for prod in factories_products:
        key = (prod.get("category"), prod.get("subtype"))
        catalog.setdefault(key, []).append(prod)

    # --- 2. Для каждого запрошенного товара собираем варианты заводов ---
    candidates: List[List[Dict[str, Any]]] = []
    for item in items:
        key = (item.get("category"), item.get("subtype"))
        possible = catalog.get(key, [])

        if not possible:
            # Если ни один завод не производит этот товар — сценариев нет
            log.warning(
                "⚠️ Не найден ни один завод для товара %s / %s",
                item.get("category"),
                item.get("subtype"),
            )
            return []

        # Сортируем по цене за единицу (цену берём из вложенного factory)
        def _price(p: Dict[str, Any]) -> float:
            f = p.get("factory") or {}
            return float(f.get("price") or 0)

        possible_sorted = sorted(possible, key=_price)

        item_quantity = item.get("quantity") or 0

        item_variants: List[Dict[str, Any]] = []
        for p in possible_sorted:
            factory_info = p.get("factory") or {}

            weight_per_item = p.get("weight_per_item") or 0.0
            weight_total = weight_per_item * item_quantity

            price_per_item = factory_info.get("price") or 0.0

            variant = {
                # Полная информация о заводе
                "factory": {
                    "name": factory_info.get("name") or "Неизвестно",
                    "lat": factory_info.get("lat"),
                    "lon": factory_info.get("lon"),
                    "contact": factory_info.get("contact"),
                    "price": price_per_item,
                },
                # Сам товар
                "category": p.get("category"),
                "subtype": p.get("subtype"),
                "quantity": item_quantity,
                "price_per_item": price_per_item,
                "weight_per_item": weight_per_item,
                "special_threshold": p.get("special_threshold") or 0.0,
                "max_per_trip": p.get("max_per_trip") or 0.0,
                "lat": factory_info.get("lat"),
                "lon": factory_info.get("lon"),
                "weight_total": weight_total,
            }

            item_variants.append(variant)

        candidates.append(item_variants)

    # --- 3. Генерируем все комбинации (один выбор завода на каждый товар) ---
    scenarios: List[Dict[str, Any]] = []

    for combo_id, combo in enumerate(product(*candidates), start=1):
        factories_map: Dict[str, List[Dict[str, Any]]] = {}

        for c in combo:
            f_obj = c.get("factory") or {}
            factory_name = f_obj.get("name") or "Неизвестно"
            factories_map.setdefault(factory_name, []).append(c)

        total_cost = sum(x["price_per_item"] * x["quantity"] for x in combo)
        total_weight = sum(x["weight_per_item"] * x["quantity"] for x in combo)

        scenarios.append({
            "scenario_id": combo_id,
            "factories": factories_map,
            "total_material_cost": total_cost,
            "total_weight": total_weight,
        })

    # --- 4. Сортировка по стоимости материалов ---
    scenarios.sort(key=lambda x: x["total_material_cost"])
    return scenarios
