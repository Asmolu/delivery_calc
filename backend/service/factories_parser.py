import os
import gspread
from dotenv import load_dotenv
import math
from functools import lru_cache
import re

load_dotenv()

SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
CREDENTIALS_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")


def parse_google_sheet(ALLOWED_SHEETS=None):
    """
    Загружает данные из Google Sheets и возвращает структуру:
    {
        "products": {...},  # словарь категорий и заводов
        "tariffs": [...]    # список тарифов машин
    }
    """
    gc = gspread.service_account(filename=CREDENTIALS_PATH)
    sh = gc.open_by_key(SHEET_ID)

    parsed_products = {}
    parsed_tariffs = []

    for worksheet in sh.worksheets():
        category_name = worksheet.title.strip()
        if ALLOWED_SHEETS and category_name not in ALLOWED_SHEETS:
            print(f"⚙️ Пропускаем лист {category_name} — не входит в ALLOWED_SHEETS")
            continue

        print(f"📄 Загружаем лист: {category_name}")
        data = worksheet.get_all_values()

        if not data or len(data) < 3:
            print(f"⚠️ Пропущен лист {category_name} — слишком мало строк.")
            continue

        if category_name.lower() == "vehicles":
            vehicles = []
            for row in data[1:]:
                if not any(row) or len(row) < 7:
                    continue
                try:
                    # Вес/условие — может быть числом или текстом вроде ">20", "any", "≤10"
                    raw_weight = str(row[3]).strip() if len(row) > 3 else ""
                    if raw_weight.lower() in ["", "any", "все", "любая", "-"]:
                        weight_if = "any"
                    else:
                        weight_if = raw_weight

                    vehicle = {
                        "название": str(row[0]).strip(),             # Название
                        "грузоподъёмность": _to_float_safe(row[1]),   # Грузоподъёмность (тонны)
                        "tag": str(row[2]).strip().lower(),           # Тег (manipulator / long_haul / special)
                        "weight_if": weight_if,                       # Весовое условие (any, >20, ≤10 и т.д.)
                        "min_distance": _to_float_safe(row[4]),       # Мин дистанция
                        "max_distance": _to_float_safe(row[5]),       # Макс дистанция
                        "base": _to_float_safe(row[6]),               # Базовая цена
                        "per_km": _to_float_safe(row[7]),             # За каждый км
                        "описание": str(row[8]).strip() if len(row) > 8 else "",
                        "заметки": str(row[9]).strip() if len(row) > 9 else ""
                    }
                    vehicles.append(vehicle)
                except Exception as e:
                    print(f"⚠️ Ошибка парсинга строки в Vehicles: {e}")
            parsed_tariffs.extend(vehicles)
            print(f"🚛 Vehicles: добавлено {len(vehicles)} тарифов")
            continue


        # === Парсинг товаров и заводов ===
        if len(data) < 5:
            print(f"⚠️ Пропущен лист {category_name} — недостаточно строк для парсинга.")
            continue

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

            lat = lon = None
            if len(row) > 2 and row[2]:
                coords = str(row[2]).strip()
                # Разделяем по запятой или пробелу
                if "," in coords:
                    parts = coords.replace(";", ",").split(",")
                elif " " in coords:
                    parts = coords.split()
                else:
                    parts = [coords]
                try:
                    lat = float(parts[0].strip().replace(",", "."))
                    if len(parts) > 1:
                        lon = float(parts[1].strip().replace(",", "."))
                except Exception:
                    pass

            contact = row[1].strip() if len(row) > 1 else ""

            for col, subtype in subtypes:
                try:
                    price = float(row[col].replace(" ", "").replace(",", "."))
                except Exception:
                    price = None
                if not price:
                    continue

                weight_val = _to_float(weights_row[col])
                special_val = _to_float(special_row[col])
                max_val = _to_float(max_row[col])

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

        parsed_products[category_name] = category_items
        print(f"🔹 {category_name}: добавлено {len(category_items)} связок 'товар+завод'")

    return {"products": parsed_products, "tariffs": parsed_tariffs}


# === Вспомогательные функции ===

import re  # если не было ранее

def _parse_coord(value):
    """Безопасное извлечение координат из строки"""
    if not value:
        return None
    try:
        clean = re.sub(r"[^0-9,\.\-]", "", str(value))
        clean = clean.replace(",", ".")
        return float(clean)
    except Exception:
        return None


def _to_float_safe(x):
    """Безопасное преобразование строки в число"""
    try:
        return float(str(x).replace(",", "."))
    except Exception:
        return 0.0


def _norm_str(s):
    if s is None:
        return ""
    return str(s).replace("\xa0", " ").strip().lower()

def _to_float(x):
    if x is None or x == "":
        return 0.0
    try:
        return float(str(x).replace(" ", "").replace("\xa0", "").replace(",", "."))
    except Exception:
        return 0.0


# === Гео-хелперы ===

@lru_cache(maxsize=2000)
def get_cached_distance(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(R * c, 2)
