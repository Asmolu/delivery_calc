from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from typing import Any, Optional, TYPE_CHECKING

from backend.core.logger import get_logger
from backend.core.database import get_db
from backend.core.auth import get_current_user_optional
from backend.core.rbac import get_user_org_role, org_role_rank
from backend.models.db_models import OrgRole, User
from backend.models.dto import QuoteRequest
from backend.core.data_loader import load_factories_and_tariffs
from backend.service.osrm_client import OSRMUnavailableError
from backend.service.transport_calc import (
    MAX_PLANS,
    build_shipment_details_from_result,
    build_trip_items_details,
    evaluate_scenario_transport_variants,
)
from backend.service.scenario_builder import build_factory_scenarios_v2

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
else:
    Session = Any

router = APIRouter(tags=["quote"])
log = get_logger("routes.quote")


@router.post("/quote")
async def make_quote(
    req: QuoteRequest,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Основной эндпоинт расчёта маршрутов.
    """
    log.info("Запрос на расчёт: %s", req.dict())

    # Бизнес-правило: если в заказе товары из разных категорий — требуется проверка логистом.
    # Плюс: будем добавлять причины (warningReasons), чтобы фронт мог объяснить, почему требуется проверка.
    warning_reasons: list[str] = []
    req_categories = sorted({(i.category or "").strip() for i in req.items if (i.category or "").strip()})
    if len(req_categories) > 1:
        warning_reasons.append("Товары из разных категорий (логистика считается раздельно).")

    needs_logistics_check = len(warning_reasons) > 0
    logistics_warning_text = "Выполнить проверку логистом!" if needs_logistics_check else None

    # ✅ загружаем объединённые данные (товары + заводы) из БД
    factories_products, tariffs = load_factories_and_tariffs(db)
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
    if len(scenarios) > MAX_PLANS:
        log.info("⚠️ Сценариев больше лимита: %s -> %s", len(scenarios), MAX_PLANS)
        scenarios = scenarios[:MAX_PLANS]
    log.info("📊 num_plans_generated=%s", len(scenarios))

    if not scenarios:
        return JSONResponse(
            status_code=400,
            content={"detail": "Не удалось построить ни одного сценария"},
        )

    results = []

    try:
        for sc in scenarios:
            variants = evaluate_scenario_transport_variants(sc, req, tariffs)
            if variants:
                results.extend(variants)
    except OSRMUnavailableError:
        return JSONResponse(
            status_code=503,
            content={"detail": "OSRM недоступен, попробуйте позже"},
        )
    log.info("📊 num_variants_generated=%s", len(results))

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

    all_sorted_full = sorted(valid_results, key=lambda x: x["total_cost"])


    def _has_container(r: dict) -> bool:
        for fp in (r or {}).get("factory_plans") or []:
            for tr in (fp or {}).get("trips", []) or []:
                if str(tr.get("tag") or "").strip().lower() == "container_carrier":
                    return True
        return False

    def _scenario_id(r: dict) -> int | None:
        sc = (r or {}).get("scenario") or {}
        try:
            sid = sc.get("scenario_id")
            return int(sid) if sid is not None else None
        except Exception:
            return None

    def _scenario_key(r: dict) -> int | str:
        sid = _scenario_id(r)
        return sid if sid is not None else f"mem:{id(r)}"

    def _factory_key_from_items(items: list) -> str:
        if not items:
            return ""
        f = (items[0] or {}).get("factory") or {}
        fid = f.get("id")
        if fid is not None:
            try:
                return f"id:{int(fid)}"
            except Exception:
                return f"id:{str(fid).strip()}"
        return str(f.get("name") or "").strip().lower()

    def _production_combo_key(r: dict) -> tuple[str, ...]:
        sc = (r or {}).get("scenario") or {}
        factories_map = (sc or {}).get("factories") or {}
        if not isinstance(factories_map, dict) or not factories_map:
            return tuple()
        keys = {
            _factory_key_from_items(items)
            for items in factories_map.values()
            if isinstance(items, list) and items
        }
        keys = {k for k in keys if k}
        return tuple(sorted(keys))

    def _unique_by_scenario(items: list[dict]) -> list[dict]:
        seen: set[int | str] = set()
        unique: list[dict] = []
        for item in items:
            key = _scenario_key(item)
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique

    all_sorted = _unique_by_scenario(all_sorted_full)


    # Топ-3 самых дешёвых вариантов без контейнеровоза (уникальные комбинации производств).
    top3: list[dict] = []
    seen_combos: set[tuple[str, ...]] = set()
    for candidate in all_sorted_full:
        if _has_container(candidate):
            continue
        combo = _production_combo_key(candidate)
        if combo in seen_combos:
            continue
        seen_combos.add(combo)
        top3.append(candidate)
        if len(top3) >= 3:
            break

    def _is_single_factory(r: dict) -> bool:
        return len(_production_combo_key(r)) == 1

    def _single_factory_name(r: dict) -> str | None:
        sc = (r or {}).get("scenario") or {}
        factories_map = (sc or {}).get("factories") or {}
        if not isinstance(factories_map, dict) or not factories_map:
            return None
        # Берём первый завод как "имя" (UI/логисту), даже если ключи в map не нормализованы.
        for k, items in factories_map.items():
            if isinstance(items, list) and items:
                f = (items[0] or {}).get("factory") or {}
                nm = str(f.get("name") or k or "").strip()
                return nm or None
        return None

    single_factory_results = [r for r in all_sorted_full if isinstance(r, dict) and _is_single_factory(r)]
    best_single_factory = single_factory_results[0] if single_factory_results else None

    container_sorted = [r for r in all_sorted_full if _has_container(r)]
    best_container = container_sorted[0] if container_sorted else None

    # Итоговый список результатов для отображения:
    # - всегда топ-3
    # - + отдельный вариант "один завод", если он есть и не попал в топ-3

    def _in_results(candidate: dict, current: list[dict]) -> bool:
        if candidate is None:
            return False
        candidate_key = _scenario_key(candidate)
        return any(_scenario_key(r) == candidate_key for r in current)

    def _pick_unique(candidates: list[dict], current: list[dict]) -> dict | None:
        for c in candidates:
            if not _in_results(c, current):
                return c
        return None

    results: list[dict] = list(top3)
    # 4-й вариант: все позиции из одного производства (если есть).
    single_factory_candidate = _pick_unique(single_factory_results, results) or best_single_factory
    if single_factory_candidate:
        results.append(single_factory_candidate)

    # 5-й вариант: самый дешёвый вариант с контейнеровозом (если есть).
    container_candidate = _pick_unique(container_sorted, results) or best_container
    if container_candidate and len(results) < 5:
        results.append(container_candidate)

    # добираем до 5 уникальными вариантами, если получилось меньше
    if len(results) < 5:
        for r in all_sorted_full:
            if len(results) >= 5:
                break
            if not _in_results(r, results):
                results.append(r)

    # Дополнительные правила "нужна проверка логистом" — по лучшему (самому дешёвому) сценарию.
    # Эти причины не меняют расчёт, только маркируют потенциально сложные кейсы.
    try:
        best = all_sorted[0] if all_sorted else None
        best_plans = (best or {}).get("factory_plans") or []
        best_trip_count = int((best or {}).get("trip_count") or 0)
        if isinstance(best_plans, list) and len(best_plans) > 1:
            warning_reasons.append("В сценарии несколько заводов (несколько точек загрузки).")
        if best_trip_count > 1:
            warning_reasons.append(f"Требуется несколько рейсов: {best_trip_count}.")

        # Контейнеровоз/кран — часто “ручной” кейс из-за нюансов разгрузки/подачи.
        has_container = False
        for fp in (best_plans or []):
            for tr in (fp or {}).get("trips", []) or []:
                if str(tr.get("tag") or "").strip().lower() == "container_carrier":
                    has_container = True
                    break
            if has_container:
                break
        if has_container:
            warning_reasons.append("Использован контейнеровоз (проверьте подачу/разгрузку).")

        unload_tag = str(((best or {}).get("unloading") or {}).get("tag") or "").strip().lower()
        if unload_tag == "crane":
            warning_reasons.append("Разгрузка краном (проверьте доступность техники на объекте).")
    except Exception:
        # Никогда не валим /quote из-за формирования предупреждений
        pass

    # Если нет НИ ОДНОГО варианта, где все позиции можно забрать с одного производства — это повод для проверки логистом.
    if not best_single_factory:
        warning_reasons.append("Нет ни одного варианта доставить все позиции с одного производства.")

    if warning_reasons:
        needs_logistics_check = True
        logistics_warning_text = logistics_warning_text or "Выполнить проверку логистом!"

    # Детализация видна только логисту и выше (org role).
    can_view_details = False
    if current_user is not None:
        try:
            r = get_user_org_role(db, current_user)
            can_view_details = org_role_rank(r) >= org_role_rank(OrgRole.LOGIST)
        except Exception:
            can_view_details = False

    # формируем варианты (детально или “сжатый” вид)
    variants = []
    for r in results:
        shipment_details = build_shipment_details_from_result(r, req) if can_view_details else None
        trip_items = build_trip_items_details(r) if can_view_details else []
        transport_title = r.get("transport_name", "Неизвестный транспорт")
        scenario_weight = r.get("scenario", {}).get("total_weight", 0)
        base_variant = {
            "totalCost": round(float(r.get("total_cost") or (r.get("material_sum", 0) + r.get("delivery_cost", 0) + r.get("unloading_cost", 0))), 2),
            "materialCost": round(r["material_sum"], 2),
            "deliveryCost": round(float(r.get("delivery_cost") or 0.0), 2),
            "unloadingCost": round(float(r.get("unloading_cost") or 0.0), 2),
            "totalWeight": round(scenario_weight, 2),
            "transportName": transport_title,
            "tripCount": r.get("trip_count", 0),
            "isSingleFactory": _is_single_factory(r),
            # Название завода — только логисту и выше (иначе это “конкретика”).
            "singleFactoryName": (_single_factory_name(r) if (can_view_details and _is_single_factory(r)) else None),
        }

        if can_view_details:
            base_variant["unloading"] = r.get("unloading") or None
            base_variant["transportDetails"] = r.get("factory_plans", [])
            base_variant["details"] = shipment_details
            base_variant["tripItems"] = trip_items

        variants.append(base_variant)

    # выводим в лог выбранные результаты (топ-3 + опционально "один завод")
    print(f"\n=== 📊 ВАРИАНТЫ (показано: {len(variants)}) ===")
    for i, v in enumerate(variants, start=1):
        unload = v.get("unloadingCost") or 0
        unload_txt = f", {unload} разгрузка" if unload else ""
        print(f"{i}) {v['transportName']}: {v['totalCost']}₽ ({v['deliveryCost']} доставка{unload_txt})")
    print("==================================\n")

    return JSONResponse(
        {
            "success": True,
            "variants": variants,
            "needsLogisticsCheck": needs_logistics_check,
            "warningText": logistics_warning_text,
            "warningReasons": warning_reasons,
        }
    )


@router.get("/factories")
def get_factories(db: Session = Depends(get_db)):
    factories_products, _ = load_factories_and_tariffs(db)

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
                "update_date": f.get("update_date"),
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
def get_tariffs(db: Session = Depends(get_db)):
    _, tariffs = load_factories_and_tariffs(db)
    # возвращаем массив напрямую, без ключа "tariffs"
    return tariffs


@router.get("/categories")
def get_categories(db: Session = Depends(get_db)):
    factories_products, _ = load_factories_and_tariffs(db)

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
