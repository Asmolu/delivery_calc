import json

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.core.logger import get_logger
from backend.models.dto import QuoteRequest
from backend.core.data_loader import load_json, FACTORIES_FILE, TARIFFS_FILE
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

    factories = load_json(FACTORIES_FILE)
    tariffs = load_json(TARIFFS_FILE)

    scenarios = build_factory_scenarios(factories, req.items)
    if not scenarios:
        return JSONResponse(
            status_code=400,
            content={"detail": "Не удалось построить ни одного сценария"},
        )

    calc_tariffs = tariffs  # пока без дополнительной обработки
    best_result = None

    results = []
    for sc in scenarios:
        r = evaluate_scenario_transport(sc, req, calc_tariffs)
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

    # выводим в лог лучший
    best = variants[0]
    print("\n=== 📊 ТОП-3 РЕЗУЛЬТАТОВ ===")
    for i, v in enumerate(variants, start=1):
        print(f"{i}) {v['transportName']}: {v['totalCost']}₽ ({v['deliveryCost']} доставка)")
    print("==================================\n")

    return JSONResponse({"success": True, "variants": variants})
