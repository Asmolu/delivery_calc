import os
import json
import gspread
from dotenv import load_dotenv

load_dotenv()

SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
CREDENTIALS_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

STORAGE_DIR = os.path.join("backend", "storage")
os.makedirs(STORAGE_DIR, exist_ok=True)

FACTORIES_PRODUCTS_PATH = os.path.join(STORAGE_DIR, "factories_products.json")
TARIFFS_PATH = os.path.join(STORAGE_DIR, "tariffs.json")

# Какие листы реально парсим
ALLOWED_SHEETS = ["Дорожные ПЛИТЫ/ПАГИ", "ФБС БЛОКИ", "Vehicles"]


def parse_google_sheet():
    """
    Загружает данные из Google Sheets и создаёт:
      - factories_products.json — товары+заводы
      - tariffs.json — тарифы (из листа Vehicles)
    """
    gc = gspread.service_account(filename=CREDENTIALS_PATH)
    sh = gc.open_by_key(SHEET_ID)

    parsed_products = {}
    parsed_tariffs = []

    for worksheet in sh.worksheets():
        category_name = worksheet.title.strip()
        if category_name not in ALLOWED_SHEETS:
            print(f"⚙️ Пропускаем лист {category_name} — не входит в ALLOWED_SHEETS")
            continue

        print(f"📄 Загружаем лист: {category_name}")
        data = worksheet.get_all_values()

        if not data or len(data) < 4:
            print(f"⚠️ Пропущен лист {category_name} — слишком мало строк.")
            continue

        # === Тарифы ===
        if category_name.lower() == "vehicles":
            for row in data[1:]:
                if not any(row):
                    continue
                try:
                    parsed_tariffs.append({
                        "название": row[0].strip(),
                        "тип": row[1].strip() if len(row) > 1 else "",
                        "base": _safe_float(row[2]),
                        "per_km": _safe_float(row[3]),
                        "min_distance": _safe_float(row[4]),
                        "max_load": _safe_float(row[5]),
                        "tag": row[6].strip().lower() if len(row) > 6 else "",
                    })
                except Exception as e:
                    print(f"⚠️ Ошибка парсинга строки в Vehicles: {e}")
            print(f"🚛 Vehicles: добавлено {len(parsed_tariffs)} тарифов")
            continue

        # === Продукты ===
        try:
            weights_row = data[0]
            special_row = data[1]
            max_row = data[2]
            subtypes_row = data[3]
        except IndexError:
            print(f"⚠️ Недостаточно строк в листе {category_name}")
            continue

        col_start = 3
        subtypes = [
            (col, subtypes_row[col].strip())
            for col in range(col_start, len(subtypes_row))
            if subtypes_row[col].strip()
        ]

        category_items = []
        for row in data[4:]:
            if len(row) < 4 or not row[0].strip():
                continue

            factory_name = row[0].strip()
            contact = row[1].strip() if len(row) > 1 else ""
            lat, lon = _safe_coords(row)

            for col, subtype in subtypes:
                price = _safe_float(row[col])
                if not price:
                    continue

                item = {
                    "category": category_name,
                    "subtype": subtype,
                    "weight_per_item": _safe_float(weights_row[col]),
                    "special_threshold": _safe_float(special_row[col]),
                    "max_per_trip": _safe_float(max_row[col]),
                    "factory": {
                        "name": factory_name,
                        "lat": lat,
                        "lon": lon,
                        "price": price,
                        "contact": contact,
                    },
                }
                category_items.append(item)

        parsed_products[category_name] = category_items
        print(f"🔹 {category_name}: добавлено {len(category_items)} связок 'товар+завод'")

    # === Сохраняем файлы ===
    with open(FACTORIES_PRODUCTS_PATH, "w", encoding="utf-8") as f:
        json.dump(parsed_products, f, ensure_ascii=False, indent=2)
    print(f"✅ factories_products.json сохранён ({len(parsed_products)} категорий).")

    with open(TARIFFS_PATH, "w", encoding="utf-8") as f:
        json.dump(parsed_tariffs, f, ensure_ascii=False, indent=2)
    print(f"✅ tariffs.json сохранён ({len(parsed_tariffs)} тарифов).")

    return {"products": parsed_products, "tariffs": parsed_tariffs}


# ==== ХЕЛПЕРЫ =====================================================

def _safe_float(value):
    try:
        return float(str(value).replace(",", ".").replace(" ", ""))
    except Exception:
        return 0.0


def _safe_coords(row):
    try:
        lat = float(str(row[2]).replace(",", "."))
        lon = float(str(row[3]).replace(",", "."))
        return lat, lon
    except Exception:
        return None, None
