import json
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.core.logger import get_logger
from backend.models.dto import QuoteRequest
from backend.service.factories_service import get_all_products
from backend.service.scenario_builder import build_factory_scenarios
from backend.service.transport_calc import evaluate_scenario_transport, build_shipment_details_from_result

router = APIRouter(tags=["quote"])
log = get_logger("routes.quote")


@router.post("/quote")
async def make_quote(req: QuoteRequest):
    """
    Основной эндпоинт расчёта маршрутов.
    """
    log.info("Запрос на расчёт: %s", req.dict())

    # ✅ загружаем объединённые данные (товары + заводы)
    factories_products = get_all_products()
    if not factories_products:
        return JSONResponse(
            status_code=500,
            content={"detail": "Не удалось загрузить factories_products.json"},
        )

    # 🧩 строим сценарии (используем товары с вложенными заводами)
    scenarios = build_factory_scenarios(factories_products, req.items)
    if not scenarios:
        return JSONResponse(
            status_code=400,
            content={"detail": "Не удалось построить ни одного сценария"},
        )

    results = []
    for sc in scenarios:
        r = evaluate_scenario_transport(sc, req, None)
        if r:
            results.append(r)

    if not results:
        return JSONResponse(
            status_code=400,
            content={"detail": "Не удалось подобрать подходящий вариант"},
        )

    # сортируем по общей стоимости и берём топ-3
    results = sorted(results, key=lambda x: x["total_cost"])[:3]

    # формируем детализированные варианты
    variants = []
    for r in results:
        shipment_details = build_shipment_details_from_result(r, req)
        transport_title = r.get("transport_name", "Неизвестный транспорт")
        variants.append({
            "totalCost": round(r["material_sum"] + r["delivery_cost"], 2),
            "materialCost": round(r["material_sum"], 2),
            "deliveryCost": round(r["delivery_cost"], 2),
            "totalWeight": round(r["scenario"]["total_weight"], 2),
            "transportName": transport_title,
            "tripCount": r.get("trip_count", 0),
            "transportDetails": r.get("transport_details", {}),
            "details": shipment_details,
        })

    # выводим в лог лучший результат
    print("\n=== 📊 ТОП-3 РЕЗУЛЬТАТОВ ===")
    for i, v in enumerate(variants, start=1):
        print(f"{i}) {v['transportName']}: {v['totalCost']}₽ ({v['deliveryCost']} доставка)")
    print("==================================\n")

    return JSONResponse({"success": True, "variants": variants})
