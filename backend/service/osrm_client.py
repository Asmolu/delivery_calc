import logging
import os
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class OSRMUnavailableError(RuntimeError):
    """Сигнализирует о недоступности сервиса OSRM."""


# Позволяем переопределять URL через переменную окружения, чтобы
# на проде указывать собственный инстанс OSRM.
OSRM_BASE_URL = os.getenv("OSRM_BASE_URL", "https://router.project-osrm.org")


def _request_osrm(url: str, timeout: float = 5.0) -> dict:
    """Выполняет запрос к OSRM с небольшой ретри-логикой."""
    last_error: Optional[Exception] = None
    for attempt in range(3):
        try:
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: PERF203 — оставляем ради отладки
            last_error = exc
            logger.warning("OSRM попытка %s не удалась: %s", attempt + 1, exc)
            time.sleep(0.3)

    raise OSRMUnavailableError(f"OSRM недоступен: {last_error}")


def get_osrm_distance_km(
    lon_from: float,
    lat_from: float,
    lon_to: float,
    lat_to: float,
) -> float:
    """Возвращает дорожное расстояние через OSRM в километрах."""

    url = (
        f"{OSRM_BASE_URL}/route/v1/driving/"
        f"{lon_from},{lat_from};{lon_to},{lat_to}?overview=false"
    )

    data = _request_osrm(url)

    routes = data.get("routes") or []
    if not routes:
        logger.warning("OSRM: пустой список routes: %s", data)
        raise OSRMUnavailableError("OSRM недоступен, попробуйте позже")

    distance_m = routes[0].get("distance")
    if distance_m is None:
        logger.warning("OSRM: нет поля distance в первом маршруте: %s", routes[0])
        raise OSRMUnavailableError("OSRM вернул пустое расстояние")

    try:
        return float(distance_m) / 1000.0
    except Exception as exc:  # noqa: PERF203 — единоразовая обработка
        logger.warning("OSRM: не удалось преобразовать distance: %s", exc)
        raise OSRMUnavailableError("OSRM вернул некорректное расстояние") from exc