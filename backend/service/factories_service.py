from __future__ import annotations

from typing import List, Dict, Any, Tuple, Optional
from functools import lru_cache
import math

# ==== ДИСТАНЦИЯ ======================================================

try:
    # Если у тебя уже есть реализация в backend/core/distance.py — используем её
    from backend.core.distance import get_cached_distance as _distance_impl
except ImportError:
    # Fallback: считаем через OSRM + хаверсайн
    import requests

    def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        R = 6371.0
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)

        a = (
            math.sin(dphi / 2) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return round(R * c, 2)

    def _osrm_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        try:
            url = (
                f"http://router.project-osrm.org/route/v1/driving/"
                f"{lon1},{lat1};{lon2},{lat2}?overview=false"
            )
            resp = requests.get(url, timeout=10)
            data = resp.json()
            if "routes" in data and data["routes"]:
                dist_m = data["routes"][0]["distance"]
                return round(dist_m / 1000, 2)
            return _haversine(lat1, lon1, lat2, lon2)
        except Exception:
            return _haversine(lat1, lon1, lat2, lon2)

    def _distance_impl(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        return _osrm_distance(lat1, lon1, lat2, lon2)


@lru_cache(maxsize=2000)
def get_cached_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Кэшированная дистанция между заводом и точкой выгрузки.
    """
    return _distance_impl(lat1, lon1, lat2, lon2)


# ==== ОБЩИЕ ХЕЛПЕРЫ ==================================================


def _norm_str(s: Any) -> str:
    if s is None:
        return ""
    return str(s).replace("\xa0", " ").strip().lower()


def _to_float(x: Any) -> float:
    if x is None or x == "":
        return 0.0
    try:
        return float(str(x).replace(" ", "").replace("\xa0", "").replace(",", "."))
    except Exception:
        return 0.0


# ==== ХРАНИЛИЩЕ ТАРИФОВ ДЛЯ calculate_tariff_cost =====================

_CURRENT_TARIFFS: List[Dict[str, Any]] = []


def set_current_tariffs(tariffs: List[Dict[str, Any]]) -> None:
    """
    Вызывается из evaluate_scenario_transport, чтобы calculate_tariff_cost
    знал, по каким тарифам считать.
    """
    global _CURRENT_TARIFFS
    _CURRENT_TARIFFS = tariffs or []


def _match_tag(t: Dict[str, Any], tag: str) -> bool:
    raw = _norm_str(t.get("tag") or t.get("тег"))
    return raw == tag


def _distance_in_range(t: Dict[str, Any], dist: float) -> bool:
    dmin = _to_float(t.get("distance_min") or t.get("дистанция_мин") or 0)
    dmax = _to_float(t.get("distance_max") or t.get("дистанция_макс") or 999999)
    return dmin <= dist <= dmax


def calculate_tariff_cost(
    tag: str,
    distance_km: float,
    load_ton: float,
) -> Tuple[Optional[float], Optional[str]]:

    if not _CURRENT_TARIFFS:
        return None, None

    candidates: List[Dict[str, Any]] = []

    for t in _CURRENT_TARIFFS:
        if not _match_tag(t, tag):
            continue
        if not _distance_in_range(t, distance_km):
            continue

        capacity = _to_float(t.get("capacity_ton") or t.get("грузоподъёмность") or 0)
        if capacity <= 0:
            continue

        # --- ❗ Ключевой момент: тариф должен выдерживать груз ---
        if load_ton > capacity:
            continue

        candidates.append(t)

    if not candidates:
        return None, None

    # Выбираем тариф с минимальной стоимостью
    best_cost = None
    best_tariff = None

    for t in candidates:
        base_price = _to_float(t.get("price") or t.get("цена") or 0)
        per_km = _to_float(t.get("per_km") or t.get("за_км") or 0)
        cost = base_price + per_km * distance_km

        if best_cost is None or cost < best_cost:
            best_cost = cost
            best_tariff = t

    if best_tariff is None:
        return None, None

    name = best_tariff.get("name") or best_tariff.get("название") or tag
    dmin = _to_float(best_tariff.get("distance_min") or best_tariff.get("дистанция_мин") or 0)
    dmax = _to_float(best_tariff.get("distance_max") or best_tariff.get("дистанция_макс") or 0)

    desc_parts = [name, f"{dmin}–{dmax} км"]

    note = (best_tariff.get("desc") or best_tariff.get("описание") or "").strip()
    if note:
        desc_parts.append(note)

    desc = ", ".join(desc_parts)

    return float(best_cost), desc



def _detect_standard_for_factory_items(items: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Анализирует товары завода и определяет,
    попадает ли всё под «стандартную» схему типа 44–55 / 41–55 / 42–55.

    Сейчас возвращаем None (нет спец-схемы), чтобы алгоритм всегда
    шёл через compute_best_plan. Функция оставлена как extension point.
    """
    return None


def _plan_special_single_heavy_long_haul(
    factory_info: Dict[str, Any],
    std_info: Dict[str, Any],
    req,
    usable_tariffs: List[Dict[str, Any]],
) -> Tuple[Optional[float], Optional[Dict[str, Any]]]:
    """
    Спец-планирование для тяжёлого длинномера (одна машина 44–55/41–55/42–55 и т.п.).

    Сейчас это заглушка: всегда возвращает (None, None),
    чтобы управление переходило обратно в обычный compute_best_plan.
    """
    return None, None
