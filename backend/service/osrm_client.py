import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

OSRM_BASE_URL = "http://router.project-osrm.org"


def get_osrm_distance_km(
    lon_from: float,
    lat_from: float,
    lon_to: float,
    lat_to: float,
) -> Optional[float]:
    """
    Запрашивает у публичного OSRM расстояние по дороге между двумя точками.
    Возвращает расстояние в километрах или None в случае ошибки.
    """
    try:
        url = (
            f"{OSRM_BASE_URL}/route/v1/driving/"
            f"{lon_from},{lat_from};{lon_to},{lat_to}?overview=false"
        )
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        data = resp.json()

        routes = data.get("routes") or []
        if not routes:
            logger.warning("OSRM: пустой список routes: %s", data)
            return None

        distance_m = routes[0].get("distance")
        if distance_m is None:
            logger.warning(
                "OSRM: нет поля distance в первом маршруте: %s",
                routes[0],
            )
            return None

        return float(distance_m) / 1000.0

    except Exception as e:
        logger.warning("Ошибка при обращении к OSRM: %s", e)
        return None
