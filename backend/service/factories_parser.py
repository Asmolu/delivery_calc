import os
import json
import gspread
from dotenv import load_dotenv

load_dotenv()

SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
CREDENTIALS_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

STORAGE_PATH = "backend/storage/factories_products.json"


def parse_google_sheet():
    """Парсит все листы Google Sheets в единую структуру:
    [{
        "category": "Дорожные ПЛИТЫ/ПАГИ",
        "subtype": "2п30.18.30 ГОСТ",
        "weight_per_item": 2.2,
        "special_threshold": 20,
        "max_per_trip": 25,
        "factories": [
            {"name": "...", "lat": ..., "lon": ..., "price": ..., "contact": "..."}
        ]
    }]
    """

    gc = gspread.service_account(filename=CREDENTIALS_PATH)
    sh = gc.open_by_key(SHEET_ID)
    all_data = []

    for worksheet in sh.worksheets():
        category_name = worksheet.title.strip()
        print(f"📄 Загружаем лист: {category_name}")

        data = worksheet.get_all_values()

        # базовая валидация
        if len(data) < 6:
            print(f"⚠️ Пропущен лист {category_name} — слишком мало строк.")
            continue

        # === Заголовочная часть (параметры товаров) ===
        headers = data[0]
        weights_row = data[0]
        special_row = data[1]
        max_row = data[2]
        subtypes_row = data[3]  # Подтипы идут с 4-й строки (зеленая строка в твоем скрине)

        # Определяем границы таблицы
        col_start = 3  # обычно с колонки D начинаются продукты
        col_end = len(data[3])

        # Собираем список подтипов (названия колонок)
        subtypes = []
        for col in range(col_start, col_end):
            subtype_name = subtypes_row[col].strip()
            if subtype_name:
                subtypes.append((col, subtype_name))

        # === Данные по заводам ===
        factories = []
        for row in data[4:]:  # данные начинаются с 6-й строки (после зелёной)
            if not row or len(row) < 4:
                continue

            name = row[0].strip()
            if not name:
                continue

            try:
                lat = float(row[2].replace(",", "."))
                lon = float(row[3].replace(",", "."))
            except Exception:
                lat = lon = None

            contact = row[1].strip() if len(row) > 1 else ""

            # Цены по каждому подтипу
            for col, subtype in subtypes:
                try:
                    price = float(row[col].replace(" ", "").replace(",", "."))
                except Exception:
                    price = None

                if not price:
                    continue

                # Для каждого продукта (столбца) создаем связку "товар+завод"
                weight_val = float(weights_row[col].replace(",", ".") or 0)
                special_val = float(special_row[col].replace(",", ".") or 0)
                max_val = float(max_row[col].replace(",", ".") or 0)

                all_data.append({
                    "category": category_name,
                    "subtype": subtype,
                    "weight_per_item": weight_val,
                    "special_threshold": special_val,
                    "max_per_trip": max_val,
                    "factory": {
                        "name": name,
                        "lat": lat,
                        "lon": lon,
                        "price": price,
                        "contact": contact
                    }
                })

        print(f"🔹 {category_name}: добавлено {len(subtypes)} товаров × {len(data[4:])} заводов")

    # === Преобразуем в формат: товар -> список заводов ===
    combined = {}
    for entry in all_data:
        key = (entry["category"], entry["subtype"])
        if key not in combined:
            combined[key] = {
                "category": entry["category"],
                "subtype": entry["subtype"],
                "weight_per_item": entry["weight_per_item"],
                "special_threshold": entry["special_threshold"],
                "max_per_trip": entry["max_per_trip"],
                "factories": []
            }
        combined[key]["factories"].append(entry["factory"])

    combined_list = list(combined.values())

    os.makedirs(os.path.dirname(STORAGE_PATH), exist_ok=True)
    with open(STORAGE_PATH, "w", encoding="utf-8") as f:
        json.dump(combined_list, f, ensure_ascii=False, indent=2)

    print(f"✅ factories_products.json обновлён — всего {len(combined_list)} товаров.")


if __name__ == "__main__":
    parse_google_sheet()
