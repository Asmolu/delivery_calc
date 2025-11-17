from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import json
import math
import os
import requests
from functools import lru_cache
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv
from fastapi import FastAPI
import json
from fastapi import FastAPI, Request, HTTPException
from pathlib import Path
from google.oauth2 import service_account
import threading, time
from gspread.exceptions import APIError
import re
from math import ceil

app = FastAPI()

from pathlib import Path

# Определяем базовую директорию проекта (где лежит main.py)
BASE_DIR = Path(__file__).resolve().parent

# Универсальные пути к файлам
FACTORIES_FILE = BASE_DIR / "factories.json"
VEHICLES_FILE = BASE_DIR / "vehicles.json"
TARIFFS_FILE = BASE_DIR / "tariffs.json"


# Разрешаем запросы с фронтенда (можно указать конкретно адрес)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # или ["http://localhost:5173"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# На Linux/WSL — свой путь, на Windows используем raw-string:
# Универсальная загрузка окружения
env_path = "/root/delivery_calc/.env" if os.path.exists("/root/delivery_calc/.env") else r"C:\Project\delivery_calc\.env"
load_dotenv(dotenv_path=env_path)

# Список API доступов
 

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
GOOGLE_SHEET_ID = "1TECrfLG4qGJDo3l9MQava7SMJpPKnhK3RId8wcnEgm8"
IGNORE_SHEETS = {"Factories", "КОЛЬЦА КОЛОДЕЗНЫЕ", "ПЛИТЫ ПЕРЕКРЫТИЯ" }    #игнорируем эти листы

def get_gspread_client():
    """
    Универсальная авторизация:
    - если есть GOOGLE_APPLICATION_CREDENTIALS (путь к файлу) — используем его;
    - иначе, если есть GOOGLE_CREDENTIALS (json-строка) — используем её;
    - иначе — бросаем понятную ошибку.
    """
    from google.oauth2.service_account import Credentials
    import json, os, gspread

    GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS")

    if GOOGLE_CREDENTIALS_PATH and os.path.exists(GOOGLE_CREDENTIALS_PATH):
        print("✅ Используем ключ из файла:", GOOGLE_CREDENTIALS_PATH)
        creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_PATH, scopes=SCOPES)
    elif GOOGLE_CREDENTIALS_JSON:
        print("✅ Используем ключ из переменной окружения GOOGLE_CREDENTIALS")
        raw = GOOGLE_CREDENTIALS_JSON.replace("\\n", "\n").replace("\\\\n", "\n")
        creds = Credentials.from_service_account_info(json.loads(raw), scopes=SCOPES)
    else:
        raise RuntimeError("❌ Нет ключа Google: задайте GOOGLE_APPLICATION_CREDENTIALS (путь) или GOOGLE_CREDENTIALS (json).")

    return gspread.authorize(creds)


# Подключаем папку static для HTML файлов
import os
from fastapi.staticfiles import StaticFiles

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "..", "static")



# Пути к JSON файлам
FACTORIES_FILE = "factories.json"
TARIFFS_FILE = "tariffs.json"

# Кэш тарифов в памяти (инициализация)
TARIFFS_CACHE: list = []

def _to_float(x) -> float:
    """
    Универсальный парсер чисел вида '39.5 Т', '20т', '12,3' и т.п.
    Нужен для работы планировщика транспорта.
    """
    if isinstance(x, (int, float)):
        return float(x)
    if x is None:
        return 0.0
    s = str(x).strip().lower()
    s = s.replace("т", "").replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return 0.0


import unicodedata
import re as _re

def _norm_str(s: str) -> str:
    """Безопасная нормализация строк для сравнения:
    - NFKC нормализация Юникода
    - убираем неразрывные пробелы/уплотняем пробелы
    - нижний регистр
    """
    if s is None:
        return ""
    s = unicodedata.normalize("NFKC", str(s))
    s = s.replace("\u00A0", " ")
    s = _re.sub(r"\s+", " ", s).strip().lower()
    return s



def load_factories_from_google():
    try:
        print("✅ Используем ключ для Google Sheets")
        client = get_gspread_client()
        sheet = client.open_by_key(GOOGLE_SHEET_ID)

        IGNORE_SHEETS = {"factories", "Factories", "Vehicles", "ПЛИТЫ ПЕРЕКРЫТИЯ", "КОЛЬЦА КОЛОДЕЗНЫЕ"} #  теперь лист машин игнорируется
        worksheets = sheet.worksheets()
        sheet_titles = [ws.title for ws in worksheets]
        print(f"📘 Найдены листы: {', '.join(sheet_titles)}")

        factories_data = []

        for ws in worksheets:
            sheet_name = ws.title.strip()
            if sheet_name.lower() in [s.lower() for s in IGNORE_SHEETS]:
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

            # проверим, совпадают ли длины
            if len(weights) != len(product_names):
                print(f"⚠️ Лист '{sheet_name}': количество весов и товаров не совпадает.")
                continue

            # обрабатываем заводы
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

                    products.append({
                        "category": sheet_name,
                        "subtype": subtype,
                        "weight_ton": weight,
                        "price": price
                    })

                factories_data.append({
                    "name": factory_name,
                    "lat": lat,
                    "lon": lon,
                    "products": products
                })
        
        def _valid_coords(lat, lon):
            try:
                if lat is None or lon is None:
                    return False
                if float(lat) == 0.0 and float(lon) == 0.0:
                    return False
                # Проверка диапазона
                return -90 <= float(lat) <= 90 and -180 <= float(lon) <= 180
            except Exception:
                return False

        # Добавляем поле valid_coords для удобной фильтрации
        for f in factories_data:
            f["valid_coords"] = _valid_coords(f.get("lat"), f.get("lon"))


        # Сохраняем JSON локально
        with open("factories.json", "w", encoding="utf-8-sig") as f:
            json.dump(factories_data, f, ensure_ascii=False, indent=2)

        print(f"💾 factories.json обновлён ({len(factories_data)} заводов, {sum(len(f['products']) for f in factories_data)} товаров)")
        return factories_data

    except Exception as e:
        print("❌ Ошибка при загрузке таблицы:")
        import traceback
        traceback.print_exc()
        return []


    
def load_tariffs_from_google():
    global TARIFFS_CACHE
    """
    Читает лист 'Vehicles' и сохраняет tariffs.json (устойчиво к различиям в заголовках).
    """
    try:
        import re

        # --- та же логика ключа, что и в factories ---
        def load_credentials():
            path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            raw = os.getenv("GOOGLE_CREDENTIALS")
            if path and os.path.exists(path):
                print(f"✅ Используем ключ из файла: {path}")
                return Credentials.from_service_account_file(path, scopes=SCOPES)
            elif raw:
                print("✅ Используем ключ из переменной окружения GOOGLE_CREDENTIALS")
                raw = raw.replace("\\n", "\n").replace("\\\\n", "\n")
                return Credentials.from_service_account_info(json.loads(raw), scopes=SCOPES)
            raise RuntimeError("Нет GOOGLE_CREDENTIALS / GOOGLE_APPLICATION_CREDENTIALS")

        def norm(s: str) -> str:
            return str(s).replace("\xa0", " ").strip().lower()

        def to_float(x):
            if x is None or x == "":
                return 0.0
            try:
                # допускаем запятые и пробелы
                return float(str(x).replace(" ", "").replace("\u00a0", "").replace(",", "."))
            except Exception:
                return 0.0

        # синонимы заголовков (нормализованные)
        COLS = {
            "name": {"название", "name"},
            "capacity": {"грузоподъёмность", "грузоподъемность", "capacity"},
            "tag": {"тег", "tag"},
            "weight_if": {"вес_если", "вес если", "условие веса", "weight_if"},
            "dist_min": {"минимальная дистанция в тарифе", "мин дистанция", "dist_min"},
            "dist_max": {"максимальная дистанция в тарифе", "макс дистанция", "dist_max"},
            "price": {"цена в конкретном тарифе", "цена", "стоимость", "price"},
            "per_km": {"за каждый км", "за км", "руб/км", "руб за км", "per_km"},
            "desc": {"описание", "description", "desc"},
            "note": {"заметки", "примечание", "note"},
        }

        def getv(row: dict, keys_set: set[str]):
            # ищем значение по любому из синонимов
            for k, v in row.items():
                if norm(k) in keys_set:
                    return v
            return None

        # --- читаем таблицу ---
        creds = load_credentials()
        client = gspread.authorize(creds)
        sheet = client.open_by_key(GOOGLE_SHEET_ID)
        ws = next(
            (s for s in sheet.worksheets() if "veh" in s.title.lower() or "тариф" in s.title.lower()),
            None
        )
        if not ws:
            raise RuntimeError("❌ Не найден лист с тарифами (Vehicles/Тарифы) в Google Sheets")
        rows = ws.get_all_records()  # список dict, ключи — оригинальные заголовки

        tariffs = []
        for row in rows:
            # пропустим полностью пустые строки
            if all(str(v).strip() == "" for v in row.values()):
                continue

            name      = getv(row, COLS["name"]) or ""
            capacity  = getv(row, COLS["capacity"]) or ""
            tag       = getv(row, COLS["tag"]) or ""
            weight_if = getv(row, COLS["weight_if"]) or "any"
            dmin      = to_float(getv(row, COLS["dist_min"]))
            dmax      = to_float(getv(row, COLS["dist_max"]) or 9999)
            price     = to_float(getv(row, COLS["price"]))
            per_km    = to_float(getv(row, COLS["per_km"]))
            desc      = getv(row, COLS["desc"]) or ""
            note      = getv(row, COLS["note"]) or ""

            tariffs.append({
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
            })

        TARIFFS_FILE = "tariffs.json"
        with open(TARIFFS_FILE, "w", encoding="utf-8-sig") as f:
            json.dump(tariffs, f, ensure_ascii=False, indent=2)

        print(f"✅ Тарифы обновлены ({len(tariffs)} записей)")
        TARIFFS_CACHE = tariffs
        print(f"💾 TARIFFS_CACHE обновлён ({len(TARIFFS_CACHE)} тарифов в памяти)")
        return {"status": "ok", "count": len(tariffs)}

    except Exception as e:
        print(f"❌ Ошибка загрузки тарифов: {e}")
        return {"status": "error", "message": str(e)}

# Вспомогалки для тарифов #
def capacity_to_ton(x) -> float:
    """ '39.5 Т' -> 39.5 """
    if x is None:
        return 0.0
    s = str(x).lower().replace("т", "").replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return 0.0

def max_capacity_by_tag(tariffs: list, tag: str) -> float:
    caps = [capacity_to_ton(t.get("грузоподъёмность")) for t in tariffs if t.get("тег") == tag]
    return max(caps) if caps else 0.0


# --- Инициализируем данные при старте ---
factories = load_factories_from_google()

if not factories:
    # подстраховка — читаем локальный кэш, если гугл недоступен
    def load_json(filename):
        if not os.path.exists(filename):
            return []
        try:
            with open(filename, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return []
    factories = load_json(FACTORIES_FILE)

# --- Фоновое периодическое обновление ---
def refresh_factories_periodically():
    global factories
    while True:
        try:
            new_factories = load_factories_from_google()
            if new_factories:
                factories = new_factories
                # при желании — кэшируем локально
                try:
                    with open(FACTORIES_FILE, "w", encoding="utf-8-sig") as f:
                        json.dump(factories, f, ensure_ascii=False, indent=2)
                except Exception as e:
                    print(f"⚠️ Не удалось сохранить кэш factories.json: {e}")
                print("✅ Заводы обновлены из Google Sheets")
        except Exception as e:
            print(f"⚠️ Ошибка обновления (поток): {e}")
        time.sleep(600)  # каждые 10 минут

threading.Thread(target=refresh_factories_periodically, daemon=True).start()

def refresh_tariffs_periodically():
    """Фоновое автообновление тарифов каждые 10 минут."""
    while True:
        try:
            result = load_tariffs_from_google()
            if result.get("status") == "ok":
                print(f"🔁 Автообновление тарифов — {result['count']} записей.")
            else:
                print(f"⚠️ Ошибка автообновления тарифов: {result.get('message')}")
        except Exception as e:
            print(f"⚠️ Ошибка в потоке автообновления тарифов: {e}")
        time.sleep(600)  # 10 минут

# Запускаем поток автообновления тарифов
threading.Thread(target=refresh_tariffs_periodically, daemon=True).start()


@app.post("/admin/reload")
async def admin_reload():
    """
    🔄 Ручная перезагрузка данных из Google Sheets.
    Теперь обновляет и заводы, и тарифы.
    """
    global factories
    try:
        print("🔁 Запуск обновления данных из Google Sheets...")

        # --- Обновляем заводы ---
        new_factories = load_factories_from_google()
        if new_factories:
            factories = new_factories
            with open(FACTORIES_FILE, "w", encoding="utf-8-sig") as f:
                json.dump(factories, f, ensure_ascii=False, indent=2)
            print(f"✅ Заводы обновлены ({len(factories)} записей)")
        else:
            print("⚠️ Не удалось обновить заводы")

        # --- Обновляем тарифы ---
        tariffs_result = load_tariffs_from_google()
        if tariffs_result.get("status") == "ok":
            print(f"✅ Тарифы обновлены ({tariffs_result.get('count', 0)} записей)")
        else:
            print(f"⚠️ Ошибка при обновлении тарифов: {tariffs_result.get('message')}")

        return {
            "status": "ok",
            "factories": len(factories),
            "tariffs": tariffs_result.get("count", 0),
            "message": "Заводы и тарифы успешно обновлены"
        }

    except Exception as e:
        import traceback
        error_text = traceback.format_exc()
        print(f"❌ Ошибка при обновлении данных:\n{error_text}")
        # сохраняем в отдельный лог для диагностики
        with open("/var/log/delivery_calc_update_error.log", "a") as f:
            f.write(error_text + "\n")
        return JSONResponse(status_code=500, content={"detail": f"Ошибка при обновлении данных: {e}"})


    
@app.post("/admin/reload_tariffs")
async def admin_reload_tariffs():
    """
    🔄 Ручная перезагрузка тарифов (Vehicles) из Google Sheets.
    """
    try:
        result = load_tariffs_from_google()
        return JSONResponse(content=result)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"detail": f"Ошибка при обновлении тарифов: {e}"})


# ===== Вспомогательные функции =====
# Функция для загрузки данных из JSON
def load_json(filename):
    if not os.path.exists(filename):
        return []
    with open(filename, "r", encoding="utf-8-sig") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []

# Функция для сохранения данных в JSON
def save_json(filename, data):
    with open(filename, "w", encoding="utf-8-sig") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)



# ===== Модели данных =====
class Product(BaseModel):
    category: str
    subtype: str
    weight_ton: float
    price: float


class Factory(BaseModel):
    name: str
    lat: float
    lon: float


class Vehicle(BaseModel):
    name: str
    capacity_ton: float


# ===== API: Работа с производствами =====
@app.get("/api/factories")
async def get_factories():
    try:
        factories = load_json(FACTORIES_FILE)
        if not factories:
            raise Exception("Не удалось загрузить данные из factories.json")
        return factories
    except Exception as e:
        print(f"⚠️ Ошибка при загрузке данных о производствах: {e}")
        raise HTTPException(status_code=500, detail="Ошибка при загрузке данных о производствах")


@app.post("/api/factories")
async def add_factory(factory: Factory):
    return JSONResponse(status_code=403, content={"detail": "Добавление производств отключено. Используйте Google Sheets."})



@app.delete("/api/factories/{factory_name}")
async def delete_factory(factory_name: str):
    factories = load_json(FACTORIES_FILE)
    updated = [f for f in factories if f["name"] != factory_name]
    if len(updated) == len(factories):
        return JSONResponse(status_code=404, content={"detail": "Производство не найдено"})
    save_json(FACTORIES_FILE, updated)
    return {"message": f"Производство {factory_name} удалено"}

@app.get("/api/tariffs")
def get_tariffs():
    path = Path("tariffs.json")

    if not path.exists():
        raise HTTPException(status_code=404, detail="Файл tariffs.json не найден")

    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            content = f.read().strip()

        if not content:
            raise HTTPException(status_code=500, detail="Файл tariffs.json пуст")

        data = json.loads(content)
        print(f"✅ API /api/tariffs: отправлено {len(data)} тарифов")
        # Преобразуем ключи в английские для фронта
        normalized = []
        for t in data:
            normalized.append({
                "name": t.get("название"),
                "capacity_ton": t.get("грузоподъёмность"),
                "tag": t.get("тег"),
                "distance_min": t.get("дистанция_мин"),
                "distance_max": t.get("дистанция_макс"),
                "price": t.get("цена"),
                "per_km": t.get("за_км"),
                "desc": t.get("описание"),
                "note": t.get("заметки"),
            })
        print(f"✅ API /api/tariffs: отправлено {len(normalized)} тарифов (нормализовано)")
        return normalized

    except json.JSONDecodeError as e:
        print(f"❌ Ошибка JSON в tariffs.json: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка в структуре tariffs.json: {e}")
    except Exception as e:
        print(f"❌ Ошибка при чтении tariffs.json: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ======== КАТЕГОРИИ (categories) ========
@app.get("/api/categories")
def get_categories():
    try:
        factories = load_json(FACTORIES_FILE)
        categories = {}
        for f in factories:
            if not f.get("valid_coords", False):
                continue  # игнорируем в расчётах, но в файле они есть

            for p in f.get("products", []):
                cat = p.get("category")
                sub = p.get("subtype")
                if not cat or not sub:
                    continue
                categories.setdefault(cat, set()).add(sub)
        return {cat: sorted(list(subs)) for cat, subs in categories.items()}
    except Exception as e:
        print("⚠️ Ошибка при генерации категорий:", e)
        return {"detail": f"Ошибка при генерации категорий: {e}"}



# ===== Геометрия: расстояние по координатам (Haversine) =====
import math
import requests

# 🔑 Твой персональный API-ключ OpenRouteService
# OSRM в новой версии

from functools import lru_cache


@lru_cache(maxsize=1000)
def get_cached_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Кэшированное получение дистанции между точками."""
    return calculate_road_distance(lat1, lon1, lat2, lon2)
def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Расстояние по прямой (Haversine)
    """
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def calculate_road_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Возвращает расстояние по дорогам (в км)
    с использованием OSRM (Open Source Routing Machine).
    """
    try:
        url = f"http://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=false"
        response = requests.get(url, timeout=10)
        data = response.json()

        if "routes" in data and len(data["routes"]) > 0:
            dist_m = data["routes"][0]["distance"]
            return round(dist_m / 1000, 2)
        else:
            print("⚠️ Неожиданный ответ OSRM:", data)
            return calculate_distance(lat1, lon1, lat2, lon2)
    except Exception as e:
        print("⚠️ Ошибка при обращении к OSRM:", e)
        return calculate_distance(lat1, lon1, lat2, lon2)


# ======= Расчёт стоимости по тарифам =======
def calculate_tariff_cost(transport_tag: str, distance_km: float, weight_ton: float | None = None):
    """Рассчитывает стоимость по тарифам из tariffs.json."""
    try:
        with open("tariffs.json", "r", encoding="utf-8-sig") as f:
            tariffs = json.load(f)
    except Exception as e:
        print(f"⚠️ Не удалось загрузить tariffs.json: {e}")
        return None, "Ошибка загрузки тарифов"

    # нормализуем теги
    def _norm_tag(s: str) -> str:
        s = (s or "").strip().lower()
        if "манипулятор" in s or s == "manipulator":
            return "manipulator"
        if "длинномер" in s or "long" in s or s == "long_haul":
            return "long_haul"
        if "спец" in s or "special" in s:
            return "special"
        return s

    transport_tag = _norm_tag(transport_tag)

    # НАДО: проставить tag у каждой строки тарифа
    for t in tariffs:
        t["tag"] = _norm_tag(t.get("tag") or t.get("тег"))

    suitable = [t for t in tariffs if t.get("tag") == transport_tag]
    if not suitable:
        print(f"⚠️ Нет тарифов для '{transport_tag}' (из {len(tariffs)} строк)")
        return None, f"Нет подходящих тарифов для '{transport_tag}'"

    best_price = None
    best_desc = ""
    for tariff in suitable:
        try:
            dmin = float(tariff.get("дистанция_мин", 0))
            dmax = float(tariff.get("дистанция_макс", 0))
            base = float(tariff.get("цена", 0))
            per_km = float(tariff.get("за_км", 0))
        except Exception:
            continue

        weight_rule = (tariff.get("вес_если") or "any").strip().lower()
        if weight_ton is not None and weight_rule not in ("any", "", None):
            try:
                if "≤" in weight_rule and weight_ton > float(weight_rule.replace("≤", "")):
                    continue
                if ">" in weight_rule and weight_ton <= float(weight_rule.replace(">", "")):
                    continue
            except Exception:
                pass

        if dmin <= distance_km <= dmax:
            total = base
        elif dmin == dmax and distance_km > dmax:
            total = base + (distance_km - dmax) * per_km
        else:
            continue

        if best_price is None or total < best_price:
            best_price = total
            best_desc = tariff.get("описание", "")

    if best_price is not None:
        return float(best_price), best_desc

    print(f"⚠️ Тариф не найден для {transport_tag}, расстояние {distance_km} км")
    return None, "Тариф не найден"

def compute_best_plan(total_weight, distance_km, tariffs, allow_mani, selected_tag=None, require_one_mani=False):
    """
    Полный расчёт оптимального плана доставки.
    Манипулятор и длинномер участвуют на равных.
    Если выбран конкретный тип (selected_tag='manipulator' или 'long_haul'),
    подбираются только такие рейсы.
    Если require_one_mani=True — добавляем хотя бы один манипулятор.
    """
    import itertools
    import math

    # === Нормализуем теги тарифов ===
    for t in tariffs:
        tag_val = (t.get("tag") or t.get("тег") or "").strip().lower()
        if "манипулятор" in tag_val:
            t["tag"] = "manipulator"
        elif "длинномер" in tag_val or "long_haul" in tag_val or "long" in tag_val:
            t["tag"] = "long_haul"

    # === Утилиты ===
    def tag_capacity(tag: str) -> float:
        """Возвращает максимальную грузоподъёмность по тегу"""
        caps = [
            _to_float(t.get("capacity_ton") or t.get("грузоподъёмность"))
            for t in tariffs
            if (t.get("tag") or t.get("тег")) == tag
        ]
        return max(caps) if caps else 0.0

    def make_trip_entry(tag, load, cost, desc):
        """Оформление одной машины"""
        real_name = next(
            (t.get("name") or t.get("название")
             for t in tariffs
             if (t.get("tag") == tag or t.get("тег") == tag)),
            tag
        )
        return {
            "тип": tag,
            "реальное_имя": real_name,
            "рейсы": 1,
            "вес_перевезено": round(load, 2),
            "стоимость": round(float(cost), 2),
            "описание": desc,
        }

    def plan_cost(plan):
        return sum(float(p["стоимость"]) for p in plan)

    # === Нормализация selected_tag ===
    if selected_tag:
        st = selected_tag.strip().lower()
        if st in ("manipulator", "манипулятор", "манипулятор "):
            selected_tag = "manipulator"
        elif st in ("длинномер", "long_haul", "long"):
            selected_tag = "long_haul"

    # === Определяем доступные теги ===
    if selected_tag in ("manipulator", "long_haul"):
        allowed_tags = [selected_tag]
    else:
        allowed_tags = ["long_haul"]
        if allow_mani:
            allowed_tags.append("manipulator")

    if not allowed_tags:
        return None, None

    # === Подготовка тарифов ===
    capacities = {tag: tag_capacity(tag) for tag in allowed_tags}
    if not capacities or all(v <= 0 for v in capacities.values()):
        return None, None

    # === Функция для расчёта стоимости комбинации ===
    def evaluate_combo(combo_counts):
        total = 0.0
        plan = []
        weight_left = total_weight
        for tag, count in combo_counts.items():
            cap = capacities[tag]
            for i in range(count):
                if weight_left <= 0:
                    break
                load = min(weight_left, cap)
                cost, desc = calculate_tariff_cost(tag, distance_km, load)
                if not cost:
                    return None, None
                plan.append(make_trip_entry(tag, load, cost, desc))
                total += cost
                weight_left -= load
        if weight_left > 0.1:
            return None, None
        return total, plan

    # === Перебор комбинаций машин (до 5 рейсов суммарно) ===
    best_plan = None
    best_cost = float("inf")

    max_reisov = 5
    for n in range(1, max_reisov + 1):
        for combo in itertools.combinations_with_replacement(allowed_tags, n):
            combo_counts = {t: combo.count(t) for t in allowed_tags}
            total_weight_possible = sum(capacities[t] * combo_counts[t] for t in allowed_tags)
            if total_weight_possible < total_weight:
                continue
            total, plan = evaluate_combo(combo_counts)
            if total and total < best_cost:
                best_cost = total
                best_plan = plan

    # === Если ничего не подошло, вернём None ===
    if not best_plan:
        return None, None

    # === Если нужно гарантировать хотя бы один манипулятор ===
    if require_one_mani and "manipulator" in capacities:
        has_mani = any(p["тип"] == "manipulator" for p in best_plan)
        if not has_mani and total_weight > 0:
            mani_cap = capacities["manipulator"]
            mani_load = min(mani_cap, total_weight)
            cost, desc = calculate_tariff_cost("manipulator", distance_km, mani_load)
            mani_trip = make_trip_entry("manipulator", mani_load, cost, desc)

            # снимаем вес с последнего длинномера, если он есть
            taken = False
            for trip in reversed(best_plan):
                if trip["тип"] == "long_haul" and trip["вес_перевезено"] > mani_load:
                    trip["вес_перевезено"] -= mani_load
                    taken = True
                    break

            if not taken:
                # если длинномера нет или мало веса — оставляем план как есть и просто добавляем манипулятор
                pass

            best_plan.append(mani_trip)
            best_plan = [p for p in best_plan if p["вес_перевезено"] > 0]
            best_cost = plan_cost(best_plan)

    best_human = ", ".join(sorted({t["реальное_имя"] for t in best_plan}))
    return best_cost, {"транспорт_детали": {"доп": best_plan}, "транспорт": best_human}


# ============================================================
#  FACTORY SCENARIO BUILDER — часть DeliveryCalc 2.0
# ============================================================

from itertools import product
from collections import defaultdict

def build_factory_scenarios(factories, items):
    """
    Создаёт ВСЕ возможные сценарии поставки товаров с разных заводов.

    factories — список заводов из factories.json
    items — [{category, subtype, quantity}, ...]

    Возвращает список сценариев:
        [
          {
            "scenario_id": 1,
            "factories": {
                "Завод А": [ {product}, {product} ],
                "Завод B": [ ... ]
            },
            "total_weight": ...,
            "weights_by_factory": {"Завод А": 12.4, "Завод B": 48.2}
          },
          ...
        ]
    """

    # ========================================================
    # 1. Строим карту: товар → список заводов, где он есть
    # ========================================================
    candidates = []  # список списков: [[factory1, factory2], [factory1], ...]

    item_meta = []   # сохраним вес/цену каждого товара

    for item in items:
        cat = item.category.strip().lower()
        sub = item.subtype.strip().lower()
        qty = item.quantity

        possible_factories = []

        for f in factories:
            for p in f.get("products", []):
                if p["category"].strip().lower() == cat and \
                   p["subtype"].strip().lower() == sub:

                    possible_factories.append({
                        "factory": f,
                        "product": p,
                        "quantity": qty
                    })

        if not possible_factories:
            print(f"⚠️ Нет заводов для товара {item.category} / {item.subtype}")
            return []

        candidates.append(possible_factories)

    # ========================================================
    # 2. Комбинаторика: декартово произведение всех вариантов
    # ========================================================
    all_scenarios_raw = list(product(*candidates))

    scenarios = []
    scenario_id = 1

    # ========================================================
    # 3. Группируем товары по заводам
    # ========================================================
    for raw_scenario in all_scenarios_raw:
        grouped = defaultdict(list)

        for choice in raw_scenario:
            f = choice["factory"]
            p = choice["product"]
            qty = choice["quantity"]

            grouped[f["name"]].append({
                "factory": f,
                "product": p,
                "quantity": qty,
                "weight_total": p["weight_ton"] * qty
            })

        # считаем суммарный вес по заводу
        weights = {}
        for fname, plist in grouped.items():
            weights[fname] = sum(x["weight_total"] for x in plist)

        scenarios.append({
            "scenario_id": scenario_id,
            "factories": grouped,
            "weights_by_factory": weights,
            "total_weight": sum(weights.values())
        })

        scenario_id += 1

    return scenarios

def evaluate_scenario_transport(scenario, req, calc_tariffs):
    """
    Считает полный план по одному сценарию (раскладка по заводам уже задана).

    Возвращает dict:
      {
        "scenario": scenario,
        "material_sum": ...,
        "delivery_cost": ...,
        "total_cost": ...,
        "plans": [список рейсов],
        "transport_name": "...",
        "factory_distances": {имя_завода: дистанция_км},
      }
    либо None, если сценарий невозможен.
    """

    factories_map = scenario["factories"]
    total_weight = scenario["total_weight"]

    if total_weight <= 0:
        return None

    # --- подготовка ограничений по типам транспорта ---
    forbidden = set((req.forbidden_types or []))

    # выбрали спецтранспорт? тогда игнорируем манипуляторы/длинномеры
    use_special = bool(req.selected_special and req.selected_special != "Не выбирать")

    # фильтруем тарифы по запретам
    usable_tariffs = [
        t for t in calc_tariffs
        if str(t.get("tag") or "").strip().lower() not in forbidden
    ]

    if not usable_tariffs:
        print("⚠️ Нет доступных тарифов после фильтрации по forbidden_types")
        return None

    # helper: расстояние от завода до клиента
    factory_distances = {}
    material_sum = 0.0

    # соберём данные по заводам
    factories_info = []  # список {name, weight, distance, material_cost, items}

    for fname, items in factories_map.items():
        # берём первый объект завода (везде один и тот же)
        f_obj = items[0]["factory"]
        lat = f_obj.get("lat")
        lon = f_obj.get("lon")

        dist = get_cached_distance(lat, lon, req.upload_lat, req.upload_lon)
        factory_distances[fname] = dist

        weight = sum(x["weight_total"] for x in items)
        mat_cost = 0.0
        for x in items:
            p = x["product"]
            qty = x["quantity"]
            price = p.get("price") or 0
            mat_cost += price * qty

        material_sum += mat_cost

        factories_info.append({
            "name": fname,
            "factory": f_obj,
            "items": items,
            "weight": weight,
            "distance": dist,
            "material_cost": mat_cost,
        })

    # === Ветка: выбран конкретный спецтранспорт ===
    if use_special:
        special_name_norm = _norm_str(req.selected_special)
        special_tariff = next(
            (t for t in usable_tariffs if _norm_str(t.get("name")) == special_name_norm),
            None
        )
        if not special_tariff:
            print(f"⚠️ Не найден спецтранспорт '{req.selected_special}'")
            return None

        cap_t = _to_float(special_tariff.get("capacity_ton") or 0) or 1.0
        tag = special_tariff.get("tag") or special_tariff.get("тег") or "special"

        all_trips = []
        delivery_cost = 0.0

        for finfo in factories_info:
            weight_left = finfo["weight"]
            dist = finfo["distance"]

            while weight_left > 0:
                load = min(cap_t, weight_left)
                cost_per_trip, desc = calculate_tariff_cost(tag, dist, load)
                if not cost_per_trip:
                    return None

                all_trips.append({
                    "тип": "special",
                    "реальное_имя": special_tariff.get("name"),
                    "рейсы": 1,
                    "вес_перевезено": round(load, 2),
                    "стоимость": round(float(cost_per_trip), 2),
                    "описание": desc or "",
                })
                delivery_cost += float(cost_per_trip)
                weight_left -= load

        transport_name = special_tariff.get("name")
        total_cost = material_sum + delivery_cost

        return {
            "scenario": scenario,
            "material_sum": material_sum,
            "delivery_cost": delivery_cost,
            "total_cost": total_cost,
            "plans": all_trips,
            "transport_name": transport_name,
            "factory_distances": factory_distances,
        }

    # === Обычный режим: манипы / длинномеры / auto ===

    # определяем, что пользователь задал
    ttype = (req.transport_type or "auto").strip().lower()

    if ttype == "manipulator":
        selected_tag = "manipulator"
        allow_mani = True
    elif ttype == "long_haul":
        selected_tag = "long_haul"
        # манипулятор возможен только как "+1", через require_one_mani в compute_best_plan
        allow_mani = True
    else:
        # auto — даём свободу комбинировать оба типа
        selected_tag = None
        allow_mani = True

    # --- для "+1 манипулятор" будем считать по двум вариантам на каждый завод ---
    per_factory_variants = []  # [{name, no_mani, with_mani}]

    for finfo in factories_info:
        fname = finfo["name"]
        weight = finfo["weight"]
        dist = finfo["distance"]

        # если веса нет — пропускаем
        if weight <= 0:
            continue

        # считаем вариант "без обязательного манипулятора"
        cost_no, plan_pack_no = compute_best_plan(
            weight,
            dist,
            usable_tariffs,
            allow_mani=allow_mani,
            selected_tag=selected_tag,
            require_one_mani=False
        )

        # по умолчанию вариант с манипулятором отсутствует
        cost_with = None
        plan_pack_with = None

        # если пользователь отметил "+1 манипулятор" и тип транспорта не pure-manipulator
        if req.add_manipulator and ttype != "manipulator":
            cost_with, plan_pack_with = compute_best_plan(
                weight,
                dist,
                usable_tariffs,
                allow_mani=allow_mani,
                selected_tag=selected_tag,
                require_one_mani=True
            )

        if cost_no is None and cost_with is None:
            # с этим заводом сценарий нереализуем
            return None

        per_factory_variants.append({
            "name": fname,
            "distance": dist,
            "weight": weight,
            "material_cost": finfo["material_cost"],
            "no_mani": (cost_no, plan_pack_no),
            "with_mani": (cost_with, plan_pack_with),
        })

    # === собираем итоговый план по сценарию ===

    def extract_trips(plan_pack):
        if not plan_pack:
            return []
        return (plan_pack or {}).get("транспорт_детали", {}).get("доп", []) or []

    # если "+1 манипулятор" НЕ включён — просто берём самые дешёвые варианты по каждому заводу
    if not req.add_manipulator or ttype == "manipulator":
        all_trips = []
        delivery_cost = 0.0

        for v in per_factory_variants:
            cost_no, pack_no = v["no_mani"]
            cost_with, pack_with = v["with_mani"]

            # выбираем существующий и более дешёвый
            if cost_no is None and cost_with is not None:
                use_cost, use_pack = cost_with, pack_with
            elif cost_with is None and cost_no is not None:
                use_cost, use_pack = cost_no, pack_no
            else:
                # оба есть — берём минимальный
                if cost_with is not None and cost_with < cost_no:
                    use_cost, use_pack = cost_with, pack_with
                else:
                    use_cost, use_pack = cost_no, pack_no

            delivery_cost += float(use_cost or 0)
            all_trips.extend(extract_trips(use_pack))

        if not all_trips:
            return None

        transport_name = ", ".join(sorted({t["реальное_имя"] for t in all_trips}))
        total_cost = material_sum + delivery_cost

        return {
            "scenario": scenario,
            "material_sum": material_sum,
            "delivery_cost": delivery_cost,
            "total_cost": total_cost,
            "plans": all_trips,
            "transport_name": transport_name,
            "factory_distances": factory_distances,
        }

    # === режим: нужен хотя бы один манипулятор глобально (+1 манипулятор) ===

    best_total = None
    best_trips = None

    # пробуем сделать "манипулятор живёт на заводе k"
    for k, vk in enumerate(per_factory_variants):
        all_trips_k = []
        total_delivery_k = 0.0

        has_mani_here = False

        for idx, v in enumerate(per_factory_variants):
            # на заводе k стараемся использовать вариант with_mani
            if idx == k:
                cost_with, pack_with = v["with_mani"]
                if cost_with is not None:
                    use_cost, use_pack = cost_with, pack_with
                else:
                    use_cost, use_pack = v["no_mani"]
            else:
                # на остальных — берём более дешёвый без учёта манипулятора
                cost_no, pack_no = v["no_mani"]
                cost_with, pack_with = v["with_mani"]
                if cost_no is None and cost_with is not None:
                    use_cost, use_pack = cost_with, pack_with
                elif cost_with is None and cost_no is not None:
                    use_cost, use_pack = cost_no, pack_no
                else:
                    if cost_with is not None and cost_with < cost_no:
                        use_cost, use_pack = cost_with, pack_with
                    else:
                        use_cost, use_pack = cost_no, pack_no

            if use_cost is None:
                all_trips_k = None
                break

            trips_here = extract_trips(use_pack)
            all_trips_k.extend(trips_here)
            total_delivery_k += float(use_cost or 0)

        if not all_trips_k:
            continue

        # проверим, что в плане вообще есть манипулятор
        if not any("manipulator" in (t.get("тип") or "") for t in all_trips_k):
            continue

        if best_total is None or total_delivery_k < best_total:
            best_total = total_delivery_k
            best_trips = all_trips_k

    # если так и не нашли валидный план с манипулятором — откатываемся к варианту без требования
    if best_trips is None:
        # просто берём минимальные комбинации по заводам
        all_trips = []
        delivery_cost = 0.0
        for v in per_factory_variants:
            cost_no, pack_no = v["no_mani"]
            delivery_cost += float(cost_no or 0)
            all_trips.extend(extract_trips(pack_no))
        if not all_trips:
            return None
        transport_name = ", ".join(sorted({t["реальное_имя"] for t in all_trips}))
        total_cost = material_sum + delivery_cost
        return {
            "scenario": scenario,
            "material_sum": material_sum,
            "delivery_cost": delivery_cost,
            "total_cost": total_cost,
            "plans": all_trips,
            "transport_name": transport_name,
            "factory_distances": factory_distances,
        }

    # успех: есть план с манипулятором
    transport_name = ", ".join(sorted({t["реальное_имя"] for t in best_trips}))
    total_cost = material_sum + best_total

    return {
        "scenario": scenario,
        "material_sum": material_sum,
        "delivery_cost": best_total,
        "total_cost": total_cost,
        "plans": best_trips,
        "transport_name": transport_name,
        "factory_distances": factory_distances,
    }

def build_shipment_details_from_result(best_result, req):
    """
    Формирует список 'детали' для ответа /quote,
    распределяя стоимость доставки пропорционально весу.
    """
    scenario = best_result["scenario"]
    factories_map = scenario["factories"]
    factory_distances = best_result["factory_distances"]

    # сначала собираем все строки без стоимости доставки
    rows = []
    for fname, items in factories_map.items():
        dist = factory_distances.get(fname, 0.0)
        for x in items:
            f_obj = x["factory"]
            p = x["product"]
            qty = x["quantity"]
            weight = x["weight_total"]
            mat_cost = (p.get("price") or 0) * qty

            rows.append({
                "товар": f"{p['category']} ({p['subtype']})",
                "завод": fname,
                "машина": best_result["transport_name"],
                "tag": req.transport_type,
                "реальное_имя_машины": best_result["transport_name"],
                "кол-во": qty,
                "вес_тонн": round(weight, 2),
                "расстояние_км": round(dist, 2),
                "стоимость_материала": mat_cost,
                "стоимость_доставки": 0.0,  # пока 0, заполним ниже
                "тариф": "",
                "итого": 0.0,
            })

    total_weight = sum(r["вес_тонн"] for r in rows) or 1.0
    delivery_cost = best_result["delivery_cost"]

    # описание тарифа — просто склейка описаний из рейсов
    desc_parts = []
    for t in best_result["plans"]:
        d = (t.get("описание") or "").strip()
        if d and d not in desc_parts:
            desc_parts.append(d)
    tariff_desc = " + ".join(desc_parts)

    # распределяем стоимость доставки по весу
    for r in rows:
        share = (r["вес_тонн"] or 0.0) / total_weight
        r["стоимость_доставки"] = round(delivery_cost * share, 2)
        r["тариф"] = tariff_desc
        r["итого"] = round(r["стоимость_материала"] + r["стоимость_доставки"], 2)

    return rows


# ===== Калькулятор стоимости доставки =====
class QuoteItem(BaseModel):
    category: str
    subtype: str
    quantity: int


from pydantic import BaseModel, Field
from typing import Optional

class QuoteRequest(BaseModel):
    upload_lat: float
    upload_lon: float
    transport_type: str  # "auto" | "manipulator" | "long_haul"
    forbidden_types: list[str] = []
    items: list[QuoteItem]

    # новые поля (с алиасами под camelCase с фронта)
    add_manipulator: bool = Field(False, alias="addManipulator")
    selected_special: Optional[str] = Field(None, alias="selectedSpecial")


@app.post("/quote")
async def quote(req: QuoteRequest):
    import json

    # --- лог входного запроса (как у тебя было) ---
    try:
        print("\n=== 🧾 RAW REQUEST (получен от фронта) ===")
        print(json.dumps(req.dict(by_alias=True), ensure_ascii=False, indent=2))
        print("========================================\n")
    except Exception as e:
        print("Ошибка при выводе JSON:", e)

    factories = load_json(FACTORIES_FILE)
    global TARIFFS_CACHE
    tariffs = TARIFFS_CACHE or load_json(TARIFFS_FILE)

    if not factories:
        return JSONResponse(status_code=400, content={"detail": "Нет данных о производствах"})
    if not tariffs:
        return JSONResponse(status_code=400, content={"detail": "Нет данных о тарифах"})

    # --- нормализуем тарифы под compute_best_plan / evaluate_scenario_transport ---
    calc_tariffs = []
    for t in tariffs:
        raw_tag = t.get("тег") or t.get("tag") or ""
        tag_norm = raw_tag.strip().lower()
        if "манипулятор" in tag_norm:
            tag_norm = "manipulator"
        elif "длинномер" in tag_norm or "long" in tag_norm:
            tag_norm = "long_haul"
        elif "спец" in tag_norm or "special" in tag_norm:
            tag_norm = "special"

        calc_tariffs.append({
            "name":         t.get("название")         or t.get("name"),
            "capacity_ton": t.get("грузоподъёмность") or t.get("capacity_ton"),
            "tag":          tag_norm,
            "distance_min": t.get("дистанция_мин")    or t.get("distance_min"),
            "distance_max": t.get("дистанция_макс")   or t.get("distance_max"),
            "price":        t.get("цена")             or t.get("price"),
            "per_km":       t.get("за_км")            or t.get("per_km"),
            "desc":         t.get("описание")         or t.get("desc"),
            "note":         t.get("заметки")          or t.get("note"),
        })


    # --- строим ВСЕ сценарии по комбинациям заводов ---
    scenarios = build_factory_scenarios(factories, req.items)
    if not scenarios:
        return JSONResponse(
            status_code=400,
            content={"detail": "Не удалось подобрать заводы под выбранные товары"}
        )

    print(f"🧩 Построено сценариев по заводам: {len(scenarios)}")

    # --- оцениваем каждый сценарий и выбираем самый дешёвый ---
    best_result = None

    for scen in scenarios:
        res = evaluate_scenario_transport(scen, req, calc_tariffs)
        if not res:
            continue
        if best_result is None or res["total_cost"] < best_result["total_cost"]:
            best_result = res

    if not best_result:
        return JSONResponse(
            status_code=400,
            content={"detail": "Не удалось подобрать транспорт под заданные ограничения"}
        )

    # --- формируем детали для фронта ---
    shipment_details = build_shipment_details_from_result(best_result, req)

    total_weight = best_result["scenario"]["total_weight"]
    trips_list = best_result["plans"]
    transport_title = best_result["transport_name"]
    material_sum = best_result["material_sum"]
    delivery_cost = best_result["delivery_cost"]

    # количество рейсов — сумма по всем trip'ам
    total_trips = sum(t.get("рейсы", 1) for t in trips_list)

    response = {
        "transport": transport_title,
        "транспорт": transport_title,
        "транспорт_детали": {"доп": trips_list},

        "общий_вес": round(total_weight, 2),
        "количество_рейсов": total_trips,
        "итого": round(material_sum + delivery_cost, 2),

        "детали": shipment_details,
    }

    # отладочный вывод
    try:
        print("\n=== 📊 РЕЗУЛЬТАТ РАСЧЁТА (2.0) ===")
        print(f"Лучший сценарий: #{best_result['scenario']['scenario_id']}")
        print(f"Тип транспорта: {transport_title}")
        print(f"Вес общий: {round(total_weight, 2)}т")
        print(f"План рейсов: {json.dumps(trips_list, ensure_ascii=False, indent=2)}")
        print(f"Доставка: {round(delivery_cost, 2)}₽, материалы: {round(material_sum, 2)}₽")
        print(f"Итого: {round(material_sum + delivery_cost, 2)}₽")
        print("==================================\n")
    except Exception as e:
        print("⚠️ Ошибка печати результата:", e)

    return JSONResponse(response)



# ===== Путь к фронтенду =====
frontend_dir = os.path.join(os.path.dirname(__file__), "../frontend/dist")

# Смонтировать фронтенд после всех API-маршрутов
if os.path.isdir(frontend_dir):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dir, "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_react_app(full_path: str):
        """
        Возвращает index.html для всех React-маршрутов.
        Работает для /, /admin, /calculator и т.д.
        """
        index_path = os.path.join(frontend_dir, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return JSONResponse(status_code=404, content={"detail": "Frontend not built"})


# ===== Локальный запуск =====
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
