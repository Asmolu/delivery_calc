import os
import gspread
from dotenv import load_dotenv
from backend.service.osrm_client import get_osrm_distance_km

load_dotenv()

SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
CREDENTIALS_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")


def parse_google_sheet(ALLOWED_SHEETS=None):
    """
    Загружает данные из Google Sheets и возвращает структуру:
    {
        "Дорожные ПЛИТЫ/ПАГИ": [...],
        "ФБС БЛОКИ": [...],
        "vehicles": [...]
    }
    """
    gc = gspread.service_account(filename=CREDENTIALS_PATH)
    sh = gc.open_by_key(SHEET_ID)

    parsed_data = {}

    for worksheet in sh.worksheets():
        category_name = worksheet.title.strip()
        if ALLOWED_SHEETS and category_name not in ALLOWED_SHEETS:
            print(f"⚙️ Пропускаем лист {category_name} — не входит в ALLOWED_SHEETS")
            continue

        print(f"📄 Загружаем лист: {category_name}")
        data = worksheet.get_all_values()

        if len(data) < 6 and category_name.lower() != "vehicles":
            print(f"⚠️ Пропущен лист {category_name} — слишком мало строк.")
            continue

        # === Парсинг тарифов (Vehicles) ===
        if category_name.lower() == "vehicles":
            vehicles = []
            for row in data[1:]:  # пропускаем заголовок
                if not any(row):
                    continue
                try:
                    vehicle = {
                        "название": row[0].strip(),
                        "тип": row[1].strip() if len(row) > 1 else "",
                        "base": float(row[2].replace(",", ".")) if len(row) > 2 and row[2] else 0,
                        "per_km": float(row[3].replace(",", ".")) if len(row) > 3 and row[3] else 0,
                        "min_distance": float(row[4].replace(",", ".")) if len(row) > 4 and row[4] else 0,
                        "max_load": float(row[5].replace(",", ".")) if len(row) > 5 and row[5] else 0,
                        "tag": row[6].strip().lower() if len(row) > 6 else ""
                    }
                    vehicles.append(vehicle)
                except Exception as e:
                    print(f"⚠️ Ошибка парсинга строки в Vehicles: {e}")
            parsed_data["vehicles"] = vehicles
            print(f"🚛 Vehicles: добавлено {len(vehicles)} тарифов")
            continue

        # === Парсинг товаров и заводов ===
        weights_row = data[0]
        special_row = data[1]
        max_row = data[2]
        subtypes_row = data[3]

        col_start = 3
        col_end = len(subtypes_row)

        subtypes = []
        for col in range(col_start, col_end):
            subtype_name = subtypes_row[col].strip()
            if subtype_name:
                subtypes.append((col, subtype_name))

        category_items = []
        for row in data[4:]:
            if not row or len(row) < 4:
                continue
            factory_name = row[0].strip()
            if not factory_name:
                continue

            try:
                lat = float(row[2].replace(",", "."))
                lon = float(row[3].replace(",", "."))
            except Exception:
                lat = lon = None

            contact = row[1].strip() if len(row) > 1 else ""

            for col, subtype in subtypes:
                try:
                    price = float(row[col].replace(" ", "").replace(",", "."))
                except Exception:
                    price = None

                if not price:
                    continue

                weight_val = float(weights_row[col].replace(",", ".") or 0)
                special_val = float(special_row[col].replace(",", ".") or 0)
                max_val = float(max_row[col].replace(",", ".") or 0)

                category_items.append({
                    "category": category_name,
                    "subtype": subtype,
                    "weight_per_item": weight_val,
                    "special_threshold": special_val,
                    "max_per_trip": max_val,
                    "factory": {
                        "name": factory_name,
                        "lat": lat,
                        "lon": lon,
                        "price": price,
                        "contact": contact
                    }
                })

        parsed_data[category_name] = category_items
        print(f"🔹 {category_name}: добавлено {len(category_items)} связок 'товар+завод'")

    return parsed_data



from functools import lru_cache

# === ПРОСТЫЕ ХЕЛПЕРЫ ======================================================

def _norm_str(s):
    """Нормализует строку (убирает пробелы, \xa0, приводит к нижнему регистру)."""
    if s is None:
        return ""
    return str(s).replace("\xa0", " ").strip().lower()

def _to_float(x):
    """Безопасно приводит значение к float."""
    if x is None or x == "":
        return 0.0
    try:
        return float(str(x).replace(" ", "").replace("\xa0", "").replace(",", "."))
    except Exception:
        return 0.0

import re

def _detect_standard_for_factory_items(name: str) -> str:
    """Пытается определить стандарт изделия по названию."""
    if not name:
        return ""
    s = _norm_str(name)
    if "гост" in s:
        match = re.search(r"гост\s*[\d\-]+", s)
        return match.group(0).upper() if match else "ГОСТ"
    if "ту" in s:
        match = re.search(r"ту\s*[\d\-]+", s)
        return match.group(0).upper() if match else "ТУ"
    if "сто" in s:
        match = re.search(r"сто\s*[\d\-]+", s)
        return match.group(0).upper() if match else "СТО"
    return ""


# === РАССТОЯНИЕ ===========================================================

@lru_cache(maxsize=2000)
def get_cached_distance(lat1, lon1, lat2, lon2):
    """Дорожное расстояние через OSRM."""
    return round(get_osrm_distance_km(lon1, lat1, lon2, lat2), 2)

# === ТАРИФЫ (ПРОСТАЯ ОБЁРТКА) ============================================

_CURRENT_TARIFFS = []

def set_current_tariffs(tariffs):
    """Сохраняет текущие тарифы в памяти."""
    global _CURRENT_TARIFFS
    _CURRENT_TARIFFS = tariffs or []

def calculate_tariff_cost(tag, distance_km, load_ton):
    """Простейший расчёт тарифа по совпадению тега."""
    if not _CURRENT_TARIFFS:
        print("⚠️ Нет доступных тарифов для расчёта.")
        return None, None

    candidates = [
        t for t in _CURRENT_TARIFFS
        if _norm_str(t.get("tag")) == _norm_str(tag)
        and _to_float(t.get("min_distance", 0)) <= distance_km <= _to_float(t.get("max_distance", 999999))
    ]

    if not candidates:
        print(f"⚠️ Нет подходящих тарифов для тега '{tag}' при дистанции {distance_km} км.")
        return None, None

    best = min(
        candidates,
        key=lambda t: _to_float(t.get("base", 0)) + _to_float(t.get("per_km", 0)) * distance_km
    )

    cost = _to_float(best.get("base", 0)) + _to_float(best.get("per_km", 0)) * distance_km
    desc = f"{best.get('название', best.get('name', tag))} ({best.get('tag')}, {distance_km} км)"

    return cost, desc

# === СТАРЫЕ УТИЛИТЫ ДЛЯ СОВМЕСТИМОСТИ =============================
# Они нужны только для transport_calc.py и старых расчётных сценариев

def _plan_special_single_heavy_long_haul(*args, **kwargs):
    """
    Заглушка старой логики: особые сценарии перевозок (негабарит, длинномер и т.д.).
    Раньше подбирала специфический транспорт, теперь просто None.
    """
    return None

def _plan_regular_single_short_haul(*args, **kwargs):
    """
    Заглушка обычного сценария короткой перевозки.
    """
    return None

def _plan_special_multidrop_long_haul(*args, **kwargs):
    """
    Заглушка многоадресной доставки.
    """
    return None

def build_factory_lookup(factories):
    """
    Заглушка — строит индекс по ID заводов (раньше для поиска ближайших).
    """
    if not factories:
        return {}
    lookup = {}
    for f in factories:
        fid = str(f.get("id") or f.get("название") or "").strip()
        if fid:
            lookup[fid] = f
    return lookup

def select_best_factory(factories, product_tag, destination_lat, destination_lon):
    """
    Заглушка — раньше выбирала лучший завод по расстоянию и наличию.
    Сейчас возвращает первый попавшийся.
    """
    if not factories:
        return None
    return factories[0]
