import os
import json

import gspread
from google.oauth2.service_account import Credentials

# __file__ = backend/core/data_loader.py
BASE_PATH = os.path.dirname(os.path.dirname(__file__))        # .../backend
STORAGE = os.path.join(BASE_PATH, "storage")

FACTORIES_FILE = os.path.join(STORAGE, "factories.json")
TARIFFS_FILE = os.path.join(STORAGE, "tariffs.json")
CATS_FILE = os.path.join(STORAGE, "cats.json")

TARIFFS_CACHE: list | None = None

# ==== GOOGLE CONSTANTS ====

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")


def get_gspread_client():
    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    creds_raw = os.getenv("GOOGLE_CREDENTIALS")

    print("GOOGLE_APPLICATION_CREDENTIALS =", creds_path)
    print("GOOGLE_CREDENTIALS exists =", bool(creds_raw))

    if creds_path and os.path.exists(creds_path):
        creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
        return gspread.authorize(creds)

    if creds_raw:
        creds_raw = creds_raw.replace("\\n", "\n")
        creds = Credentials.from_service_account_info(json.loads(creds_raw), scopes=SCOPES)
        return gspread.authorize(creds)

    raise RuntimeError("Нет GOOGLE_CREDENTIALS или GOOGLE_APPLICATION_CREDENTIALS")


def load_factories_from_google():
    """
    Читает все листы товаров, игнорируя служебные/машинные, и сохраняет factories.json.
    """
    try:
        print("✅ Используем ключ для Google Sheets")
        client = get_gspread_client()
        sheet = client.open_by_key(GOOGLE_SHEET_ID)

        IGNORE_SHEETS = {
            "factories",
            "Factories",
            "Vehicles",
            "ПЛИТЫ ПЕРЕКРЫТИЯ",
            "КОЛЬЦА КОЛОДЕЗНЫЕ",
        }

        worksheets = sheet.worksheets()
        sheet_titles = [ws.title for ws in worksheets]
        print(f"📘 Найдены листы: {', '.join(sheet_titles)}")

        factories_data: list[dict] = []

        for ws in worksheets:
            sheet_name = ws.title.strip()
            if sheet_name.lower() in (s.lower() for s in IGNORE_SHEETS):
                print(f"⚠️ Пропускаем лист '{sheet_name}' (в списке исключений)")
                continue

            rows = ws.get_all_values()
            if len(rows) < 3:
                print(f"⚠️ Лист '{sheet_name}' пустой или слишком короткий, пропускаем.")
                continue

            # первая строка — веса
            weights = rows[0][3:]
            # вторая строка — названия товаров
            product_names = rows[1][3:]

            if len(weights) != len(product_names):
                print(f"⚠️ Лист '{sheet_name}': количество весов и товаров не совпадает.")
                continue

            for row in rows[2:]:
                if not row or not row[0].strip():
                    continue

                factory_name = row[0].strip()
                contacts = row[1].strip() if len(row) > 1 else ""
                coords = row[2].strip() if len(row) > 2 else ""

                lat, lon = 0.0, 0.0
                if coords and "," in coords:
                    try:
                        lat_str, lon_str = coords.split(",", 1)
                        lat, lon = float(lat_str.strip()), float(lon_str.strip())
                    except Exception:
                        pass

                products = []
                for col_index, price_str in enumerate(row[3:], start=3):
                    if not price_str.strip():
                        continue
                    try:
                        price = float(price_str.replace(",", "."))
                    except ValueError:
                        continue

                    subtype = product_names[col_index - 3].strip()
                    weight_str = weights[col_index - 3].strip()
                    try:
                        weight = float(weight_str.replace(",", "."))
                    except ValueError:
                        weight = 0.0

                    products.append(
                        {
                            "category": sheet_name,
                            "subtype": subtype,
                            "weight_ton": weight,
                            "price": price,
                        }
                    )

                factories_data.append(
                    {
                        "name": factory_name,
                        "contacts": contacts,
                        "lat": lat,
                        "lon": lon,
                        "products": products,
                    }
                )

        def _valid_coords(lat, lon):
            try:
                if lat is None or lon is None:
                    return False
                if float(lat) == 0.0 and float(lon) == 0.0:
                    return False
                return -90 <= float(lat) <= 90 and -180 <= float(lon) <= 180
            except Exception:
                return False

        for f in factories_data:
            f["valid_coords"] = _valid_coords(f.get("lat"), f.get("lon"))

        with open(FACTORIES_FILE, "w", encoding="utf-8-sig") as f:
            json.dump(factories_data, f, ensure_ascii=False, indent=2)

        print(
            f"💾 factories.json обновлён "
            f"({len(factories_data)} заводов, "
            f"{sum(len(f['products']) for f in factories_data)} товаров)"
        )
        return factories_data

    except Exception:
        print("❌ Ошибка при загрузке таблицы:")
        import traceback

        traceback.print_exc()
        return []


def load_tariffs_from_google():
    """
    Читает лист 'Vehicles' и сохраняет tariffs.json (устойчиво к различиям в заголовках).
    """
    global TARIFFS_CACHE

    try:
        def load_credentials():
            path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            raw = os.getenv("GOOGLE_CREDENTIALS")
            if path and os.path.exists(path):
                print(f"✅ Используем ключ из файла: {path}")
                return Credentials.from_service_account_file(path, scopes=SCOPES)
            elif raw:
                print("✅ Используем ключ из переменной окружения GOOGLE_CREDENTIALS")
                raw = raw.replace("\\n", "\n").replace("\\\\n", "\n")
                return Credentials.from_service_account_info(
                    json.loads(raw), scopes=SCOPES
                )
            raise RuntimeError("Нет GOOGLE_CREDENTIALS / GOOGLE_APPLICATION_CREDENTIALS")

        def norm(s: str) -> str:
            return str(s).replace("\xa0", " ").strip().lower()

        def to_float(x):
            if x is None or x == "":
                return 0.0
            try:
                return float(str(x).replace(" ", "").replace("\u00a0", "").replace(",", "."))
            except Exception:
                return 0.0

        COLS = {
            "name": {"название", "name"},
            "capacity": {"грузоподъёмность", "грузоподъемность", "capacity"},
            "tag": {"тег", "tag"},
            "weight_if": {"вес_если", "вес если", "условие веса", "weight_if"},
            "dist_min": {
                "минимальная дистанция в тарифе",
                "мин дистанция",
                "dist_min",
            },
            "dist_max": {
                "максимальная дистанция в тарифе",
                "макс дистанция",
                "dist_max",
            },
            "price": {"цена в конкретном тарифе", "цена", "стоимость", "price"},
            "per_km": {"за каждый км", "за км", "руб/км", "руб за км", "per_km"},
            "desc": {"описание", "description", "desc"},
            "note": {"заметки", "примечание", "note"},
        }

        def getv(row: dict, keys_set: set[str]):
            for k, v in row.items():
                if norm(k) in keys_set:
                    return v
            return None

        creds = load_credentials()
        client = gspread.authorize(creds)
        sheet = client.open_by_key(GOOGLE_SHEET_ID)

        ws = next(
            (s for s in sheet.worksheets()
             if "veh" in s.title.lower() or "тариф" in s.title.lower()),
            None,
        )
        if not ws:
            raise RuntimeError("❌ Не найден лист с тарифами (Vehicles/Тарифы) в Google Sheets")

        rows = ws.get_all_records()

        tariffs = []
        for row in rows:
            if all(str(v).strip() == "" for v in row.values()):
                continue

            name = getv(row, COLS["name"]) or ""
            capacity = getv(row, COLS["capacity"]) or ""
            tag = getv(row, COLS["tag"]) or ""
            weight_if = getv(row, COLS["weight_if"]) or "any"
            dmin = to_float(getv(row, COLS["dist_min"]))
            dmax = to_float(getv(row, COLS["dist_max"]) or 9999)
            price = to_float(getv(row, COLS["price"]))
            per_km = to_float(getv(row, COLS["per_km"]))
            desc = getv(row, COLS["desc"]) or ""
            note = getv(row, COLS["note"]) or ""

            tariffs.append(
                {
                    "название": str(name).strip(),
                    "грузоподъёмность": str(capacity).strip(),
                    "тег": str(tag).strip(),
                    "вес_если": str(weight_if).strip(),
                    "дистанция_мин": dmin,
                    "дистанция_макс": dmax,
                    "цена": price,
                    "за_км": per_km,
                    "описание": str(desc).strip(),
                    "заметки": str(note).strip(),
                }
            )

        with open(TARIFFS_FILE, "w", encoding="utf-8-sig") as f:
            json.dump(tariffs, f, ensure_ascii=False, indent=2)

        print(f"✅ Тарифы обновлены ({len(tariffs)} записей)")
        TARIFFS_CACHE = tariffs
        print(f"💾 TARIFFS_CACHE обновлён ({len(TARIFFS_CACHE)} тарифов в памяти)")
        return {"status": "ok", "count": len(tariffs)}

    except Exception as e:
        print(f"❌ Ошибка загрузки тарифов: {e}")
        return {"status": "error", "message": str(e)}


def load_json(filename: str):
    if not os.path.exists(filename):
        return []
    with open(filename, "r", encoding="utf-8-sig") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []


def save_json(filename: str, data):
    with open(filename, "w", encoding="utf-8-sig") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

import gspread
from google.oauth2.service_account import Credentials
import json
from pathlib import Path

PRODUCT_SPECS_FILE = Path("backend/storage/product_specs.json")

def fetch_all_product_specs(sheet_id: str, sheet_names: list[str]):
    """Загружает данные спецификаций товара с нескольких листов Google Sheet."""
    creds = Credentials.from_service_account_file(
        "google_credentials.json",
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
    )
    client = gspread.authorize(creds)
    sheet = client.open_by_key(sheet_id)

    result = {}

    for sheet_name in sheet_names:
        print(f"📄 Загружаем лист: {sheet_name}")
        ws = sheet.worksheet(sheet_name)
        data = ws.get_all_values()

        # ---- правильные строки ----
        weights_row = data[0][3:]       # вес
        special_row = data[1][3:]       # особый тариф (порог)
        max_per_trip_row = data[2][3:]  # макс. за рейс
        names_row = data[3][3:]         # название подтипа

        for i, subtype in enumerate(names_row):
            subtype = subtype.strip()
            if not subtype:
                continue

            # вес
            try:
                weight = float(weights_row[i].replace(",", "."))
            except:
                weight = 0.0

            # особый тариф
            try:
                special_threshold = int(special_row[i] or 0)
            except:
                special_threshold = 0

            # максимум в рейс
            try:
                max_trip = int(max_per_trip_row[i] or 0)
            except:
                max_trip = 0

            result[subtype] = {
                "weight_per_item": weight,
                "special_threshold": special_threshold,
                "max_per_trip": max_trip
            }

        print(f"🔹 Лист {sheet_name}: загружено {len(names_row)} товаров")

    # сохраняем в JSON
    PRODUCT_SPECS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PRODUCT_SPECS_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"✅ product_specs.json обновлён — всего {len(result)} позиций.")
    return result


if __name__ == "__main__":
    fetch_all_product_specs(
        sheet_id=os.getenv("GOOGLE_SHEET_ID"),
        sheet_names=[
            "Дорожные ПЛИТЫ/ПАГИ",
            "ФБС БЛОКИ",
        ]
    )

