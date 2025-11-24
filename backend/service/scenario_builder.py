from typing import List, Any, Dict
from backend.core.logger import get_logger

log = get_logger("scenario_builder")


def build_factory_scenarios(factories: List[dict], items: List[Any]) -> List[dict]:
    """
    Генерирует сценарии в формате старого ядра:
    Каждый сценарий -> структура:
    {
        "scenario_id": int,
        "factories": {
            "Название завода": [
                {
                    "factory": {..},
                    "product": {..},
                    "quantity": int,
                    "weight_total": float
                }
            ]
        },
        "total_weight": float
    }
    """

    scenarios = []
    scenario_id = 1

    for factory in factories:
        factory_products = factory.get("products", [])
        product_map = {}

        # индексируем товары завода
        for p in factory_products:
            product_map.setdefault(p["category"], {})
            product_map[p["category"]][p["subtype"]] = p

        factories_map: Dict[str, list] = {}
        total_weight = 0.0
        ok = True

        for req_item in items:
            cat = req_item.category
            sub = req_item.subtype
            qty = req_item.quantity

            if cat not in product_map or sub not in product_map[cat]:
                ok = False
                break

            product = product_map[cat][sub]
            weight_total = product["weight_ton"] * qty

            factories_map.setdefault(factory["name"], [])
            factories_map[factory["name"]].append({
                "factory": factory,
                "product": product,
                "quantity": qty,
                "weight_total": weight_total
            })

            total_weight += weight_total

        if not ok:
            continue

        scenarios.append({
            "scenario_id": scenario_id,
            "factories": factories_map,
            "total_weight": total_weight
        })

        scenario_id += 1

    log.info("Построено %s сценариев", len(scenarios))
    return scenarios
