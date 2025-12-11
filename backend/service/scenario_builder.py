"""Tools for generating purchase scenarios across factories."""

from itertools import product
from typing import Any, Dict, Iterable, List, Tuple

from backend.core.logger import get_logger

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


def _unique_variants_by_factory(variants: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate product variants by factory, keeping the cheapest option."""

    best_by_factory: Dict[str, Dict[str, Any]] = {}
    for option in variants:
        factory = option.get("factory") or {}
        name = (factory.get("name") or "").lower()
        current_best = best_by_factory.get(name)
        price = float(factory.get("price") or 0.0)
        if current_best is None:
            best_by_factory[name] = option
            continue

        existing_price = float((current_best.get("factory") or {}).get("price") or 0.0)
        if price < existing_price:
            best_by_factory[name] = option

    return list(best_by_factory.values())


def _scenario_signature(factories: Dict[str, List[Dict[str, Any]]]) -> Tuple[Tuple[str, int], ...]:
    """Create a stable signature for deduplicating scenarios."""

    signature: List[Tuple[str, int]] = []
    for fname, items in factories.items():
        qty_sum = sum(int(i.get("quantity") or i.get("count") or 0) for i in items)
        signature.append((fname, qty_sum))
    return tuple(sorted(signature))


def build_factory_scenarios_v2(
    factories_products: List[Dict[str, Any]],
    items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Создать осмысленные комбинации распределения товаров по заводам.

    - Каждому запрошенному товару сопоставляется список заводов-поставщиков.
    - Дубли по одному и тому же заводу отфильтровываются, оставляя минимальную цену.
    - Комбинации с одинаковым набором заводов и количеств объединяются.
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
            log.warning(
                "⚠️ Не найден ни один завод для товара %s / %s",
                item.get("category"),
                item.get("subtype"),
            )
            return []

        item_quantity = item.get("quantity") or 0

        # Сортируем по цене и оставляем одно предложение на завод
        possible_sorted = sorted(
            possible,
            key=lambda p: float((p.get("factory") or {}).get("price") or 0.0),
        )
        filtered_variants = _unique_variants_by_factory(possible_sorted)

        item_variants: List[Dict[str, Any]] = []
        for prod in filtered_variants:
            factory_info = prod.get("factory") or {}
            weight_per_item = prod.get("weight_per_item") or 0.0
            weight_total = weight_per_item * item_quantity
            price_per_item = factory_info.get("price") or 0.0

            item_variants.append(
                {
                    "factory": {
                        "name": factory_info.get("name") or "Неизвестно",
                        "lat": factory_info.get("lat"),
                        "lon": factory_info.get("lon"),
                        "contact": factory_info.get("contact"),
                        "price": price_per_item,
                    },
                    "category": prod.get("category"),
                    "subtype": prod.get("subtype"),
                    "quantity": item_quantity,
                    "price_per_item": price_per_item,
                    "weight_per_item": weight_per_item,
                    "special_threshold": prod.get("special_threshold") or 0.0,
                    "max_per_trip": prod.get("max_per_trip") or 0.0,
                    "lat": factory_info.get("lat"),
                    "lon": factory_info.get("lon"),
                    "weight_total": weight_total,
                }
            )

        candidates.append(item_variants)
    if not candidates:
        return []


    # --- 3. Генерируем все комбинации (один выбор завода на каждый товар) ---
    scenarios: List[Dict[str, Any]] = []
    seen_signatures: set[Tuple[Tuple[str, int], ...]] = set()

    for combo_id, combo in enumerate(product(*candidates), start=1):
        factories_map: Dict[str, List[Dict[str, Any]]] = {}

        for selection in combo:
            factory_info = selection.get("factory") or {}
            factory_name = factory_info.get("name") or "Неизвестно"
            factories_map.setdefault(factory_name, []).append(selection)

        signature = _scenario_signature(factories_map)
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)

        total_cost = sum(x["price_per_item"] * x["quantity"] for x in combo)
        total_weight = sum(x["weight_per_item"] * x["quantity"] for x in combo)

        scenarios.append(
            {
                "scenario_id": combo_id,
                "factories": factories_map,
                "total_material_cost": total_cost,
                "total_weight": total_weight,
            }
        )

    # --- 4. Сортировка по стоимости материалов ---
    scenarios.sort(key=lambda x: x["total_material_cost"])
    return scenarios
