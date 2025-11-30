from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.core.logger import get_logger
from backend.models.dto import QuoteRequest
from backend.core.data_loader import load_factories_and_tariffs
from backend.service.osrm_client import OSRMUnavailableError
from backend.service.transport_calc import (
    build_shipment_details_from_result,
    build_trip_items_details,
    evaluate_scenario_transport,
)
from backend.service.scenario_builder import build_factory_scenarios_v2

router = APIRouter(tags=["quote"])
log = get_logger("routes.quote")


@router.post("/quote")
async def make_quote(req: QuoteRequest):
    """
    Основной эндпоинт расчёта маршрутов.
    """
    log.info("Запрос на расчёт: %s", req.dict())

    # ✅ загружаем объединённые данные (товары + заводы)
    factories_products, tariffs = load_factories_and_tariffs()
    if not factories_products:
        return JSONResponse(
            status_code=500,
            content={"detail": "Не удалось загрузить factories_products.json"},
        )

    # 🧩 строим сценарии (используем товары с вложенными заводами)
    # Приводим factories_products в список объектов
    if isinstance(factories_products, dict):
        factories_list = []
        for sheet, items in factories_products.items():
            if isinstance(items, list):
                factories_list.extend(items)
    else:
        factories_list = factories_products

    # Преобразуем Pydantic-модели в обычные словари
    items_data = [item.dict() for item in req.items]

    scenarios = build_factory_scenarios_v2(factories_list, items_data)

    if not scenarios:
        return JSONResponse(
            status_code=400,
            content={"detail": "Не удалось построить ни одного сценария"},
        )

    results = []

    try:
        for sc in scenarios:
            r = evaluate_scenario_transport(sc, req, tariffs)
            if r:
                results.append(r)
    except OSRMUnavailableError:
        return JSONResponse(
            status_code=503,
            content={"detail": "OSRM недоступен, попробуйте позже"},
        )

    if not results:
        return JSONResponse(
            status_code=400,
            content={"detail": "Не удалось подобрать подходящий вариант"},
        )

    # --- фильтруем результаты, у которых нет total_cost ---
    valid_results = [r for r in results if isinstance(r, dict) and "total_cost" in r]

    if not valid_results:
        print("⚠️ Нет валидных результатов с total_cost")
        return {"ok": False, "reason": "Не удалось рассчитать стоимость"}

    results = sorted(valid_results, key=lambda x: x["total_cost"])[:3]

    # формируем детализированные варианты
    variants = []
    for r in results:
        shipment_details = build_shipment_details_from_result(r, req)
        trip_items = build_trip_items_details(r)
        transport_title = r.get("transport_name", "Неизвестный транспорт")
        scenario_weight = r.get("scenario", {}).get("total_weight", 0)
        variants.append({
            "totalCost": round(r["material_sum"] + r["delivery_cost"], 2),
            "materialCost": round(r["material_sum"], 2),
            "deliveryCost": round(r["delivery_cost"], 2),
            "totalWeight": round(scenario_weight, 2),
            "transportName": transport_title,
            "tripCount": r.get("trip_count", 0),
            "transportDetails": r.get("factory_plans", []),
            "details": shipment_details,
            "tripItems": trip_items,
        })

    # выводим в лог лучший результат
    print("\n=== 📊 ТОП-3 РЕЗУЛЬТАТОВ ===")
    for i, v in enumerate(variants, start=1):
        print(f"{i}) {v['transportName']}: {v['totalCost']}₽ ({v['deliveryCost']} доставка)")
    print("==================================\n")

    return JSONResponse({"success": True, "variants": variants})


@router.get("/factories")
def get_factories():
    factories_products, _ = load_factories_and_tariffs()

    factories = []
    for category, items in factories_products.items():
        for item in items:
            f = item.get("factory", {})
            if not f.get("name"):
                continue

            factories.append({
                "name": f.get("name"),
                "lat": f.get("lat"),
                "lon": f.get("lon"),
                "contact": f.get("contact"),
                "category": category,
                "subtype": item.get("subtype"),
                "weight_per_item": item.get("weight_per_item"),
                "special_threshold": item.get("special_threshold"),
                "max_per_trip": item.get("max_per_trip"),
                "price": f.get("price"),
            })

    # возвращаем массив напрямую, без ключа "factories"
    return factories


@router.get("/tariffs")
def get_tariffs():
    _, tariffs = load_factories_and_tariffs()
    # возвращаем массив напрямую, без ключа "tariffs"
    return tariffs


@router.get("/categories")
def get_categories():
    factories_products, _ = load_factories_and_tariffs()

    result = {}
    if isinstance(factories_products, dict):
        for category, items in factories_products.items():
            if not isinstance(items, list):
                continue

            # Берём список уникальных подтипов
            subtypes = sorted({
                str(item.get("subtype"))
                for item in items
                if item.get("subtype")
            })
            if subtypes:
                result[category] = subtypes

    return result
