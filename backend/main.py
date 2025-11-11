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


# Разрешаем запросы с фронтенда (можно указать конкретно адрес)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # или ["http://localhost:5173"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# На Linux/WSL — свой путь, на Windows используем raw-string:
load_dotenv(dotenv_path="/root/delivery_calc/.env")
load_dotenv(dotenv_path=r"C:\Project\delivery_calc\.env")

# Список API доступов
 

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
GOOGLE_SHEET_ID = "1TECrfLG4qGJDo3l9MQava7SMJpPKnhK3RId8wcnEgm8"
IGNORE_SHEETS = {"factories", "тест", "справочник", "сводная"}    #игнорируем эти листы

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


# Разрешаем запросы из любого источника (чтобы HTML мог обращаться к API)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключаем папку static для HTML файлов
import os
from fastapi.staticfiles import StaticFiles

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "..", "static")



# Пути к JSON файлам
FACTORIES_FILE = "factories.json"
TARIFFS_FILE = "tariffs.json"

# Новые утилиты
TON_RE = re.compile(r"([0-9]+(?:[.,][0-9]+)?)")

def _to_float(x: str | float | int) -> float:
    if isinstance(x, (int, float)):
        return float(x)
    m = TON_RE.search(str(x))
    return float(m.group(1).replace(",", ".")) if m else 0.0

def _vehicle_capacity(tariff: dict) -> float:
    # "capacity_ton": "39.5 Т" -> 39.5
    return _to_float(tariff.get("capacity_ton", 0))

def _is_le20_bucket(tariff: dict) -> bool:
    text = f"{tariff.get('desc','')} {tariff.get('note','')}"
    return "≤20" in text or "<=20" in text or "≤20т" in text

def _is_gt20_bucket(tariff: dict) -> bool:
    text = f"{tariff.get('desc','')} {tariff.get('note','')}"
    return ">20" in text or " >20" in text or ">20т" in text

def _distance_ok(tariff: dict, d_km: float) -> bool:
    dmin = float(tariff.get("distance_min", 0) or 0)
    dmax = float(tariff.get("distance_max", dmin) or dmin)
    # у нас для «>120 км» в данных distance_max == distance_min; значит бесконечная вилка
    return dmin <= d_km and (dmax == dmin or d_km <= dmax)

def _price_for(tariff: dict, d_km: float) -> float:
    base = float(tariff.get("price", 0) or 0)
    per_km = float(tariff.get("per_km", 0) or 0)
    dmin = float(tariff.get("distance_min", 0) or 0)
    extra_km = max(0.0, d_km - max(dmin, 0.0))
    return base + per_km * extra_km

def _matches_weight_rule(weight_rule: str | None, load_t: float) -> bool:
    if not weight_rule or str(weight_rule).strip().lower() == "any":
        return True
    s = str(weight_rule).replace("т", "").replace("T", "").strip()
    try:
        if "≤" in weight_rule or "<=" in weight_rule:
            lim = float(s.replace("≤", "").replace("<=", ""))
            return load_t <= lim + 1e-6
        if ">" in weight_rule:
            lim = float(s.replace(">", ""))
            return load_t > lim + 1e-6
    except Exception:
        return True
    return True

def _cost_one_trip(tag: str, distance_km: float, load_t: float, tariffs: list[dict]):
    """
    Возвращает (цена, описание) для ОДНОГО рейса заданной загрузки.
    Учитывает:
      - тег транспорта
      - правило веса (≤20т / >20т / any)
      - диапазон дистанции (или надбавку, если dmin==dmax и поехали дальше)
    Берёт минимальную подходящую цену среди строк одного тега.
    """
    best = None  # (price, desc)
    for t in tariffs:
        if (t.get("tag") or t.get("тег")) != tag:
            continue

        weight_rule = t.get("weight_if") or t.get("вес_если")
        if not _matches_weight_rule(weight_rule, load_t):
            continue

        dmin = float(t.get("distance_min") or t.get("дистанция_мин") or 0)
        dmax = float(t.get("distance_max") or t.get("дистанция_макс") or dmin)
        base = float(t.get("price") or t.get("цена") or 0)
        per_km = float(t.get("per_km") or t.get("за_км") or 0)
        desc = (t.get("desc") or t.get("описание") or "").strip()

        price = None
        if dmin <= distance_km <= dmax:
            price = base + per_km * 0
        elif dmin == dmax and distance_km > dmax:
            # “>120 км” и т.п.: надбавка за каждый км дальше границы
            price = base + per_km * (distance_km - dmax)

        if price is not None:
            if best is None or price < best[0]:
                best = (price, desc)

    return best  # или None



def compute_best_plan(total_weight, distance_km, tariffs, allow_mani, selected_tag=None, require_one_mani=False):
    """
    Полный расчёт оптимального плана доставки.
    Манипулятор и длинномер участвуют на равных.
    Если выбран конкретный тип (selected_tag='manipulator' или 'long_haul'),
    подбираются только такие рейсы.
    Если require_one_mani=True — добавляем ровно один манипулятор, если его нет.
    """

    import itertools

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

    # === Определяем доступные теги ===
    # === Нормализация selected_tag (рус/англ эквиваленты) ===
    if selected_tag:
        st = selected_tag.strip().lower()
        if st in ("манипулятор", "manipulator"):
            selected_tag = "manipulator"
        elif st in ("длинномер", "long_haul"):
            selected_tag = "long_haul"

    # === Определяем доступные теги 2 ===
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

    # === Обеспечиваем наличие манипулятора при флаге +1 ===
    if require_one_mani and "manipulator" in capacities:
        has_mani = any(p["тип"] == "manipulator" for p in best_plan)
        if not has_mani:
            cap = capacities["manipulator"]
            load = min(cap, total_weight)
            cost, desc = calculate_tariff_cost("manipulator", distance_km, load)
            if cost:
                mani_trip = make_trip_entry("manipulator", load, cost, desc)
                remaining_weight = max(0.0, total_weight - load)
                rest_total, rest_plan = None, []
                if remaining_weight > 0:
                    # добавляем оставшийся вес длинномерами
                    rest_total, rest_plan = evaluate_combo({"long_haul": int(remaining_weight // capacities["long_haul"] + 1)})
                if rest_plan:
                    best_plan = [mani_trip] + rest_plan
                    best_cost = plan_cost(best_plan)

    # === Если включена галочка +1 манипулятор, а выбран длинномер ===
    if require_one_mani and selected_tag == "long_haul":
        # ищем тарифы манипулятора
        mani_tariffs = [t for t in tariffs if (t.get("tag") or t.get("тег")) in ("manipulator", "манипулятор")]
        if mani_tariffs and best_plan:
            mani = mani_tariffs[0]
            has_mani = any("manipulator" in (p["тип"] or "").lower() for p in best_plan)
            if not has_mani:
                # берём минимальный остаток веса, который влезет в манипулятор
                mani_capacity = mani.get("capacity_ton", 0)
                total_weight = sum(p["вес_перевезено"] for p in best_plan)
                if mani_capacity > 0 and total_weight > mani_capacity:
                    # отнимаем часть груза у последней машины
                    last = best_plan[-1]
                    if last["вес_перевезено"] > mani_capacity:
                        last["вес_перевезено"] -= mani_capacity
                        # добавляем рейс манипулятора с этой частью
                        cost, desc = calculate_tariff_cost(mani.get("tag"), distance_km, mani_capacity)
                        if cost:
                            best_plan.append({
                                "тип": "manipulator",
                                "реальное_имя": mani.get("name") or mani.get("название") or "Манипулятор",
                                "рейсы": 1,
                                "вес_перевезено": mani_capacity,
                                "стоимость": round(cost, 2),
                                "описание": desc,
                            })
                            best_cost = (best_cost or 0) + cost



    best_human = ", ".join(sorted({t["реальное_имя"] for t in best_plan}))
    return best_cost, {"транспорт_детали": {"доп": best_plan}, "транспорт": best_human}




def load_factories_from_google():
    try:
        creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "google_credentials.json")

        if not os.path.exists(creds_path):
            print(f"❌ Ключ не найден: {creds_path}")
            return {}

        print("✅ Используем ключ для Google Sheets")
        creds = service_account.Credentials.from_service_account_file(creds_path, scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ])
        client = gspread.authorize(creds)

    except Exception as e:
        print(f"❌ Ошибка авторизации Google Sheets: {e}")
        return {}  # <<< важно — сразу выйти, если client не создан

    # если дошли сюда — client есть, можно безопасно открывать
    try:
        sheet = client.open_by_key(GOOGLE_SHEET_ID)
        ...
    except APIError as e:
        print(f"⚠️ Ошибка Google API: {e}")
        return {}

    """
    Загружает данные с заводами и товарами из Google Sheets.
    Структура листа:
    1 строка — вес (тонны)
    2 строка — название товара
    3+ строка — заводы (название, контакты, координаты, цены)
    """

    try:
        print("✅ Используем ключ для Google Sheets")
        client = get_gspread_client()
        sheet = client.open_by_key(GOOGLE_SHEET_ID)

        IGNORE_SHEETS = {"factories", "Factories", "тест", "Тест", "справочник", "Справочник", "Сводная", "Vehicles"} #  теперь лист машин игнорируется
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

        with open("/root/delivery_calc/tariffs.json", "w", encoding="utf-8-sig") as f:
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

def pick_special_by_name(tariffs: list, name: str):
    if not name:
        return None
    for t in tariffs:
        if str(t.get("название", "")).strip().lower() == str(name).strip().lower():
            return t
    return None


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
    """
    Рассчитывает стоимость доставки по тарифам из tariffs.json.
    Возвращает (float: стоимость, str: описание).
    Учитывает надбавку за км при dmin == dmax.
    """
    try:
        with open("tariffs.json", "r", encoding="utf-8-sig") as f:
            tariffs = json.load(f)
    except Exception as e:
        print(f"⚠️ Не удалось загрузить tariffs.json: {e}")
        return None, "Ошибка загрузки тарифов"

    # фильтруем по тегу транспорта
    suitable = [t for t in tariffs if t.get("тег") == transport_tag or t.get("tag") == transport_tag]
    if not suitable:
        return None, f"Нет подходящих тарифов для '{transport_tag}'"

    for tariff in suitable:
        try:
            dmin = float(tariff.get("дистанция_мин", 0))
            dmax = float(tariff.get("дистанция_макс", 0))
            base = float(tariff.get("цена", 0))
            per_km = float(tariff.get("за_км", 0))
        except (TypeError, ValueError):
            continue

        weight_rule = tariff.get("вес_если", "any")

        # Проверяем весовые ограничения
        if weight_ton is not None and weight_rule not in ("any", "", None):
            try:
                if "≤" in weight_rule and weight_ton > float(weight_rule.replace("≤", "")):
                    continue
                if ">" in weight_rule and weight_ton <= float(weight_rule.replace(">", "")):
                    continue
            except Exception:
                pass

        # ✅ Попадание в диапазон
        if dmin <= distance_km <= dmax:
            total = base
            desc = tariff.get("описание", "")
            return float(total), desc

        # ✅ Надбавка при dmin == dmax
        if dmin == dmax and distance_km > dmax:
            extra = (distance_km - dmax) * per_km
            total = base + extra
            desc = f"{tariff.get('описание', '')} (+{per_km}₽/км)"
            return float(total), desc

    # 🚫 Если не найдено
    print(f"⚠️ Тариф не найден для {transport_tag}, расстояние {distance_km} км")
    return None, "Тариф не найден"



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


def cheapest_factory_for(tag: str, factory_ship: dict, shipment_details: list):
    """
    Возвращает завод, где доп.рейс (по данному тегу транспорта)
    выйдет дешевле всего по суммарной стоимости доставки.
    """
    best_factory = None
    best_cost = float("inf")

    for factory_name, info in factory_ship.items():
        # возьмём первую позицию от этого завода, чтобы оценить дистанцию
        positions = [d for d in shipment_details if d["завод"] == factory_name]
        if not positions:
            continue

        # возьмём среднюю дистанцию (если разные товары с разных координат)
        avg_distance = sum(d["расстояние_км"] for d in positions) / len(positions)
        cost_per_trip, _ = calculate_tariff_cost(tag, avg_distance, sum(d["вес_тонн"] for d in positions))
        if cost_per_trip and cost_per_trip < best_cost:
            best_cost = cost_per_trip
            best_factory = factory_name

    return best_factory, best_cost if best_factory else (None, None)


@app.post("/quote")
async def quote(req: QuoteRequest):

    import json
    try:
        raw = await req.__dict__
    except Exception:
        raw = {}
    print("\n=== 🧾 RAW REQUEST (получен от фронта) ===")
    try:
        print(json.dumps(req.dict(by_alias=True), ensure_ascii=False, indent=2))
    except Exception as e:
        print("Ошибка при выводе JSON:", e)
    print("========================================\n")

    # Диагностика: если категории пришли битые
    for item in req.items:
        if "?" in item.category or "?" in item.subtype:
            print(f"⚠️ ВНИМАНИЕ: битая кириллица в запросе — {item.category} / {item.subtype}")

    factories = load_json(FACTORIES_FILE)
    global TARIFFS_CACHE
    tariffs = TARIFFS_CACHE or load_json("/root/delivery_calc/tariffs.json")

    # === Нормализуем теги тарифов ===
    for t in tariffs:
        tag_val = (t.get("tag") or t.get("тег") or "").strip().lower()
        if "манипулятор" in tag_val:
            t["tag"] = "manipulator"
        elif "длинномер" in tag_val or "long_haul" in tag_val:
            t["tag"] = "long_haul"

    # Нормализация тарифов под compute_best_plan (ожидает англ. ключи)
    calc_tariffs = []
    for t in tariffs:
        calc_tariffs.append({
            "name":         t.get("название")         or t.get("name"),
            "capacity_ton": t.get("грузоподъёмность") or t.get("capacity_ton"),
            "tag":          t.get("тег")              or t.get("tag"),
            "distance_min": t.get("дистанция_мин")    or t.get("distance_min"),
            "distance_max": t.get("дистанция_макс")   or t.get("distance_max"),
            "price":        t.get("цена")             or t.get("price"),
            "per_km":       t.get("за_км")            or t.get("per_km"),
            "desc":         t.get("описание")         or t.get("desc"),
            "note":         t.get("заметки")          or t.get("note"),
        })


    if not factories:
        return JSONResponse(status_code=400, content={"detail": "Нет данных о производствах"})
    if not tariffs:
        return JSONResponse(status_code=400, content={"detail": "Нет данных о тарифах"})

    # === 1. Общий вес (по одному совпадению на товар) ===
    def find_weight_ton(category: str, subtype: str) -> float:
        cat = category.strip().lower()
        sub = subtype.strip().lower()
        for f in factories:
            for p in f.get("products", []):
                if p["category"].strip().lower() == cat and p["subtype"].strip().lower() == sub:
                    return float(p.get("weight_ton", 0.0))
        return 0.0

    total_weight = 0.0
    for item in req.items:
        w = find_weight_ton(item.category, item.subtype)
        if w <= 0:
            print(f"❌ Не найден вес для {item.category} / {item.subtype}")
        total_weight += w * item.quantity

    # === 2. Максимальная грузоподъёмность по тегу ===
    def type_capacity(tag: str) -> float:
        def _parse_capacity(value):
            if value is None:
                return 0.0
            s = str(value).replace(",", ".").replace("т", "").replace("Т", "").strip()
            try:
                return float(s)
            except ValueError:
                return 0.0

        caps = [_parse_capacity(t.get("грузоподъёмность")) for t in tariffs if t.get("тег") == tag]
        if not caps:
            return max(_parse_capacity(t.get("грузоподъёмность")) for t in tariffs)
        return max(caps)


    # === 3. Определяем тип транспорта ===
    if req.transport_type == "auto":
        possible_types = sorted({t.get("тег") for t in tariffs if t.get("тег") in ("manipulator", "long_haul")})
        if not possible_types:
            largest = max(tariffs, key=lambda t: float(t.get("грузоподъёмность", 0)))
            transport_type = largest.get("тег", "long_haul")
        else:
            best_type, best_total_delivery = None, float("inf")
            first_factory = factories[0]
            sample_dist = get_cached_distance(first_factory["lat"], first_factory["lon"],
                                              req.upload_lat, req.upload_lon)
            for t in possible_types:
                cap = type_capacity(t)
                if cap <= 0:
                    continue
                cost_per_trip, _ = calculate_tariff_cost(t, sample_dist, total_weight)
                trips = math.ceil(total_weight / cap)
                total_delivery = cost_per_trip * trips if cost_per_trip else float("inf")
                if total_delivery < best_total_delivery:
                    best_total_delivery = total_delivery
                    best_type = t
            transport_type = best_type or "manipulator"
    else:
        transport_type = req.transport_type

    # === 4. Подбор лучших заводов по каждому товару ===
    shipment_details = []
    for item in req.items:
        best = None
        for f in factories:
            for p in f.get("products", []):
                if p["category"].strip().lower() == item.category.strip().lower() and \
                   p["subtype"].strip().lower() == item.subtype.strip().lower():
                    dist = get_cached_distance(f["lat"], f["lon"], req.upload_lat, req.upload_lon)
                    mat_cost = p["price"] * item.quantity
                    weight_here = p["weight_ton"] * item.quantity
                    del_cost_per_trip, tariff_info = calculate_tariff_cost(transport_type, dist, weight_here)
                    if not del_cost_per_trip:
                        continue
                    total = mat_cost + del_cost_per_trip
                    if best is None or total < best[0]:
                        best = (total, f, p, dist, mat_cost, del_cost_per_trip, tariff_info)

        if best:
            total, f, p, dist, mat_cost, del_cost_per_trip, tariff_info = best

            # получаем человеко-читаемое имя машины (делаем это ДО append)
            real_name = next(
                (t.get("название") or t.get("name")
                 for t in tariffs
                 if (t.get("тег") == transport_type or t.get("tag") == transport_type)),
                transport_type
            )

            shipment_details.append({
                "товар": f"{p['category']} ({p['subtype']})",
                "завод": f["name"],
                "машина": real_name,
                "tag": transport_type,
                "реальное_имя_машины": real_name,
                "кол-во": item.quantity,
                "вес_тонн": round(p["weight_ton"] * item.quantity, 2),
                "расстояние_км": round(dist, 2),
                "стоимость_материала": mat_cost,
                "стоимость_доставки": round(del_cost_per_trip, 2),
                "тариф": tariff_info,
                "итого": round(total, 2),
            })
    # Пересчёт общего веса по реально выбранным позициям (чтобы точно не было дублей)
    total_weight = sum(d["вес_тонн"] for d in shipment_details)

    # --- Ввод недостающих переменных ---
    # Средняя дистанция по всем товарам (используем для расчёта тарифов)
    if shipment_details:
        distance_km = sum(d["расстояние_км"] for d in shipment_details) / len(shipment_details)
    else:
        distance_km = 0.0

    # Манипулятор всегда участвует в переборе.
    # Галочка +1 лишь гарантирует, что в финале будет хотя бы один манипулятор.
    allow_mani = True


    # Общая сумма материалов
    material_sum = sum(d["стоимость_материала"] for d in shipment_details)

    # === Новый блок расчёта рейсов на основе compute_best_plan ===
    print("🧩 DEBUG:", total_weight, distance_km, len(tariffs), allow_mani)

    selected_tag = "special" if req.selected_special and req.selected_special != "Не выбирать" else None
    
    # === Определяем тип транспорта, заданный пользователем ===
    # "auto" — значит система сама подбирает (оба типа участвуют)
    selected_by_type = None
    if req.transport_type in ("manipulator", "long_haul"):
        selected_by_type = req.transport_type
    best_cost, plan_pack = compute_best_plan(
        total_weight,
        distance_km,
        calc_tariffs,
        allow_mani,
        selected_tag=selected_by_type,
        require_one_mani=req.add_manipulator
    )


    # === Синхронизация итоговой таблицы "Результаты" ===
    trips_list = (plan_pack or {}).get("транспорт_детали", {}).get("доп", [])
    trip_desc_str = " + ".join(
        (t.get("описание") or t.get("реальное_имя") or "").strip()
        for t in trips_list
    )

    if trips_list and best_cost is not None and total_weight > 0:
        for row in shipment_details:
            # доля веса конкретной строки в общем объёме
            share = (row.get("вес_тонн", 0.0) or 0.0) / total_weight
            # распределяем стоимость доставки пропорционально весу
            row["стоимость_доставки"] = round(best_cost * share, 2)
            # выводим состав транспорта и описание тарифа
            row["машина"] = plan_pack.get("транспорт") or row.get("машина")
            row["тариф"] = trip_desc_str
            # финальное итого
            row["итого"] = round(row["стоимость_материала"] + row["стоимость_доставки"], 2)


    # --- формируем строки для сводной таблицы рейсов ---
    trips_rows = []
    for p in trips_list:
        title = p.get("реальное_имя") or (
            "Манипулятор" if p.get("тип") == "manipulator"
            else "Длинномер" if p.get("тип") == "long_haul"
            else "Спецтранспорт"
        )
        trips_rows.append({
            "machine": title,
            "distance_km": round(distance_km, 2),
            "load_t": round(float(p.get("вес_перевезено", 0) or 0), 2),
            "price": round(float(p.get("стоимость", 0) or 0), 2),
            "trips": int(p.get("рейсы", 0) or 0),
        })

    # 🧩 Группировка рейсов по машине и заводу
    grouped = {}
    for row in trips_rows:
        # ищем завод в shipment_details по совпадению машины
        factory_name = None
        for s in shipment_details:
            if s.get("машина") == row["machine"]:
                factory_name = s.get("завод")
                break

        key = f"{row['machine']}_{factory_name or 'Неизвестный завод'}"
        if key not in grouped:
            grouped[key] = {
                "machine": row["machine"],
                "factory": factory_name or "Неизвестный завод",
                "distance_km": row["distance_km"],
                "load_t": row["load_t"],
                "price": row["price"],
                "trips": row["trips"],
            }
        else:
            grouped[key]["load_t"] += row["load_t"]
            grouped[key]["price"] += row["price"]
            grouped[key]["trips"] += row["trips"]

    # заменяем старый список новым, сгруппированным
    trips_rows = list(grouped.values())

    # --- итоговый ответ ---
    response = {
        "transport": plan_pack.get("транспорт"),
        "транспорт": plan_pack.get("транспорт"),
        "транспорт_детали": plan_pack.get("транспорт_детали"),

        "общий_вес": round(total_weight, 2),
        "количество_рейсов": sum(row["trips"] for row in trips_rows),
        "итого": round(best_cost + material_sum, 2),

        "детали": shipment_details,   # <- именно эти данные нужны таблице на фронте
    }

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
