from functools import lru_cache

from backend.service.osrm_client import OSRMUnavailableError, get_osrm_distance_km

@lru_cache(maxsize=1000)
def get_cached_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Кэшированное получение дистанции между точками через OSRM."""
    return calculate_road_distance(lat1, lon1, lat2, lon2)


def calculate_road_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Получает дорожное расстояние через OSRM или бросает OSRMUnavailableError."""
    try:
        return round(get_osrm_distance_km(lon1, lat1, lon2, lat2), 2)
    except OSRMUnavailableError:
        # Перебрасываем исключение без глушения, чтобы фронт показал корректное сообщение
        raise