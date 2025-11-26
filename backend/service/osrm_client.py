import requests

OSRM_BASE_URL = "http://router.project-osrm.org"

def get_osrm_distance_km(lon_from, lat_from, lon_to, lat_to):
    """
    Возвращает расстояние между двумя точками (в километрах)
    с помощью публичного OSRM API.
    """
    try:
        url = f"{OSRM_BASE_URL}/route/v1/driving/{lon_from},{lat_from};{lon_to},{lat_to}?overview=false"
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        if data.get("routes"):
            distance_m = data["routes"][0]["distance"]
            return round(distance_m / 1000, 2)
    except Exception as e:
        print(f"⚠️ Ошибка при обращении к OSRM: {e}")
    return None
