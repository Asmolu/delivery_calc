import os
import gspread
from dotenv import load_dotenv
from functools import lru_cache
import re
from backend.service.osrm_client import get_osrm_distance_km

load_dotenv()

SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
CREDENTIALS_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")


def parse_google_sheet(ALLOWED_SHEETS=None, include_vehicles: bool = False):
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
            if not include_vehicles:
                print("⚙️ Пропускаем лист Vehicles — тарифы теперь редактируются в админке сайта")
                continue
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
        if len(data) < 3:
            print(f"⚠️ Пропущен лист {category_name} — недостаточно строк для парсинга.")
            continue
        # Layouts:
        # New: row 0 weights, row 1 subtypes, row 2+ factories
        #      col 0 update date, col 1 factory name, col 2 contacts, col 3 coords, col 4+ prices
        # Old: row 0 weights, row 1 special tariff, row 2 max per trip, row 3 subtypes, row 4+ factories
        #      col 0 factory name, col 1 contacts, col 2 coords, col 3+ prices
        header_hint = _norm_str(data[1][0]) if len(data[1]) > 0 else ""
        has_date_column = "дата" in header_hint
        has_old_header = False
        if len(data) > 2:
            row1_hint = _norm_str(data[1][0]) if len(data[1]) > 0 else ""
            row2_hint = _norm_str(data[2][0]) if len(data[2]) > 0 else ""
            has_old_header = row1_hint.startswith("особ") or row2_hint.startswith("максим")
        if not has_date_column and not has_old_header and len(data) > 3:
            has_old_header = any(cell.strip() for cell in data[3][3:])

        if has_date_column or not has_old_header:
            weights_row = data[0]
            subtypes_row = data[1]
            data_rows = data[2:]
            col_start = 4
            name_idx = 1
            contact_idx = 2
            coord_idx = 3
        else:
            weights_row = data[0]
            subtypes_row = data[3]
            data_rows = data[4:]
            col_start = 3
            name_idx = 0
            contact_idx = 1
            coord_idx = 2

        col_end = len(subtypes_row)

        subtypes = []
        for col in range(col_start, col_end):
            subtype_name = subtypes_row[col].strip()
            if subtype_name:
                subtypes.append((col, subtype_name))

        category_items = []
        for row in data_rows:
            if not row or len(row) <= coord_idx:
                continue
            factory_name = row[name_idx].strip()
            if not factory_name:
                continue

            lat = lon = None
            if len(row) > coord_idx and row[coord_idx]:
                coords = str(row[coord_idx]).strip()
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

            contact = row[contact_idx].strip() if len(row) > contact_idx else ""

            for col, subtype in subtypes:
                try:
                    price = float(row[col].replace(" ", "").replace(",", "."))
                except Exception:
                    price = None
                if not price:
                    continue

                weight_val = _to_float(weights_row[col])
                special_val = 0.0
                max_val = 0.0

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
    return round(get_osrm_distance_km(lon1, lat1, lon2, lat2), 2)