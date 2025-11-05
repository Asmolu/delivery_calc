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

app = FastAPI()

# Разрешаем запросы с фронтенда (можно указать конкретно адрес)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # или ["http://localhost:5173"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

load_dotenv(dotenv_path="/root/delivery_calc/.env")

load_dotenv(dotenv_path="C:\Project\delivery_calc\.env")

# Список API доступов
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

GOOGLE_SHEET_ID = "1TECrfLG4qGJDo3l9MQava7SMJpPKnhK3RId8wcnEgm8"  # твой ID таблицы
SHEET_NAME = "Factories"  # название листа

app = FastAPI()

# Разрешаем запросы из любого источника (чтобы HTML мог обращаться к API)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключаем папку static для HTML файлов
app.mount("/static", StaticFiles(directory="static"), name="static")

# Пути к JSON файлам
FACTORIES_FILE = "factories.json"
VEHICLES_FILE = "vehicles.json"

import threading, time

# --- Загрузка из Google Sheets ---
def load_factories_from_google() -> list[dict]:
    """
    Загружает все производства и их номенклатуру из Google Sheets.
    """
    try:
        import os, json, gspread
        from google.oauth2.service_account import Credentials

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
            else:
                raise RuntimeError("Не удалось найти ключ Google (нет GOOGLE_CREDENTIALS или GOOGLE_APPLICATION_CREDENTIALS)")

        creds = load_credentials()
        client = gspread.authorize(creds)
        sheet = client.open_by_key(GOOGLE_SHEET_ID).worksheet(SHEET_NAME)
        rows = sheet.get_all_records()
        def cell(row: dict, *names: str):
            for n in names:
                if n in row:
                    return row[n]
                for k in row.keys():
                    if k.strip().lower() == n.strip().lower():
                        return row[k]
            return None

        def to_float(x):
            if x is None or x == "":
                return 0.0
            return float(str(x).replace(",", ".").strip())

        factories_map: dict[str, dict] = {}

        current_factory: str | None = None
        current_coords: str | None = None
        current_category: str | None = None

        for row in rows:
            name = cell(row, "название")
            coords = cell(row, "координаты")
            category = cell(row, "категория")
            subtype = cell(row, "подтип")
            weight = cell(row, "вес")
            price = cell(row, "цена", "Цена")

            if isinstance(name, str) and name.strip():
                current_factory = name.strip()
            if isinstance(coords, str) and coords.strip():
                current_coords = coords.strip()
            if isinstance(category, str) and category.strip():
                current_category = category.strip()

            if not subtype or not current_factory or not current_category:
                continue

            if current_factory not in factories_map:
                try:
                    lat_str, lon_str = (current_coords or "0,0").split(",")
                    lat, lon = float(lat_str), float(lon_str)
                except Exception:
                    lat, lon = 0.0, 0.0

                factories_map[current_factory] = {
                    "name": current_factory,
                    "lat": lat,
                    "lon": lon,
                    "products": []
                }

            factories_map[current_factory]["products"].append({
                "category": current_category,
                "subtype": str(subtype).strip(),
                "weight_ton": to_float(weight),
                "price": to_float(price),
            })

    
        # --- Сохраняем локально, чтобы админка могла использовать ---
        factories_data = list(factories_map.values())
        try:
            with open(FACTORIES_FILE, "w", encoding="utf-8-sig") as f:
                json.dump(factories_data, f, ensure_ascii=False, indent=2)
            print(f"💾 factories.json обновлён ({len(factories_data)} записей)")
        except Exception as e:
            print("⚠️ Не удалось сохранить factories.json:", e)

        return factories_data


    except Exception as e:
        import traceback
        print("⚠️ Ошибка при загрузке таблицы:")
        traceback.print_exc()
        return []
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


@app.post("/admin/reload")
async def admin_reload():
    """
    🔄 Ручная перезагрузка данных из Google Sheets.
    Возвращает количество загруженных производств и статус.
    """
    global factories
    try:
        new_factories = load_factories_from_google()
        if not new_factories:
            return JSONResponse(
                status_code=500,
                content={"detail": "Не удалось загрузить данные из Google Sheets"}
            )

        factories = new_factories
        # сохраняем локально (чтобы API мог использовать их при следующем старте)
        with open(FACTORIES_FILE, "w", encoding="utf-8-sig") as f:
            json.dump(factories, f, ensure_ascii=False, indent=2)

        print("✅ Заводы обновлены вручную через /admin/reload")
        return {"status": "ok", "count": len(factories), "message": "Заводы успешно обновлены"}

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"detail": f"Ошибка при обновлении: {e}"})
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



def save_json(filename, data):
    with open(filename, "w", encoding="utf-8-sig") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ===== Загрузка данных =====
vehicles = load_json(VEHICLES_FILE)


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

# ======== КАТЕГОРИИ (categories) ========
@app.get("/api/categories")
def get_categories():
    try:
        factories = load_json(FACTORIES_FILE)
        categories = {}
        for f in factories:
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

# ======== МАШИНЫ (vehicles) ========

@app.get("/api/vehicles")
def get_vehicles():
    try:
        vehicles = load_json(VEHICLES_FILE)
        if not vehicles:
            raise Exception("Не удалось загрузить данные из vehicles.json")
        return vehicles
    except Exception as e:
        print(f"⚠️ Ошибка при загрузке данных о машинах: {e}")
        raise HTTPException(status_code=500, detail="Ошибка при загрузке данных о машинах")
    

@app.post("/api/vehicles")
async def add_vehicle(request: Request):
    """Добавляет новую машину с тегом"""
    data = await request.json()
    name = data.get("name")
    capacity = data.get("capacity_ton") or data.get("capacity")
    tag = data.get("tag")

    if not name or not capacity:
        return JSONResponse(status_code=400, content={"detail": "Укажите название и грузоподъёмность"})
    if tag not in ["manipulator", "long_haul"]:
        return JSONResponse(status_code=400, content={"detail": "Неверный тег. Допустимо: manipulator / long_haul"})

    vehicles = load_json(VEHICLES_FILE)
    if any(v["name"].lower() == name.lower() for v in vehicles):
        return JSONResponse(status_code=400, content={"detail": "Такая машина уже существует"})

    vehicles.append({
        "name": name,
        "capacity_ton": float(capacity),
        "tag": tag
    })
    save_json(VEHICLES_FILE, vehicles)

    return {"message": f"Машина '{name}' добавлена с тегом '{tag}'"}

@app.delete("/api/vehicles/{name}")
def delete_vehicle(name: str):
    """Удаляет машину по названию"""
    vehicles = load_json(VEHICLES_FILE)
    new_list = [v for v in vehicles if v["name"].lower() != name.lower()]

    if len(new_list) == len(vehicles):
        return JSONResponse(status_code=404, content={"detail": "Машина не найдена"})

    save_json(VEHICLES_FILE, new_list)
    return {"message": f"Машина '{name}' удалена."}


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



def get_delivery_cost(transport_type: str, distance_km: float, weight_ton: float = 0) -> tuple[float, str]:
    """
    Возвращает (стоимость_за_1_рейс, описание_тарифа)
    """
    if transport_type == "manipulator":
        if distance_km <= 30:
            return 16000, "0–30 км / Манипулятор"
        elif distance_km <= 60:
            return 18000, "30–60 км / Манипулятор"
        elif distance_km <= 80:
            return 20000, "60–80 км / Манипулятор"
        elif distance_km <= 100:
            return 22000, "80–100 км / Манипулятор"
        elif distance_km <= 120:
            return 24000, "100–120 км / Манипулятор"
        else:
            cost = 24000 + (distance_km - 120) * 200
            return cost, f"{distance_km:.0f} км / Манипулятор (+200₽/км)"

    if transport_type == "long_haul":
        if weight_ton < 20:
            if distance_km <= 30:
                return 19000, "0–30 км / ≤20т / Длинномер"
            elif distance_km <= 60:
                return 22000, "30–60 км / ≤20т / Длинномер"
            elif distance_km <= 80:
                return 24000, "60–80 км / ≤20т / Длинномер"
            elif distance_km <= 100:
                return 25000, "80–100 км / ≤20т / Длинномер"
            elif distance_km <= 120:
                return 28000, "100–120 км / ≤20т / Длинномер"
            else:
                cost = 28000 + (distance_km - 120) * 200
                return cost, f"{distance_km:.0f} км / ≤20т / Длинномер (+200₽/км)"
        else:
            if distance_km <= 30:
                return 23000, "0–30 км / >20т / Длинномер"
            elif distance_km <= 60:
                return 26000, "30–60 км / >20т / Длинномер"
            elif distance_km <= 80:
                return 28000, "60–80 км / >20т / Длинномер"
            elif distance_km <= 100:
                return 30000, "80–100 км / >20т / Длинномер"
            elif distance_km <= 120:
                return 33000, "100–120 км / >20т / Длинномер"
            else:
                cost = 33000 + (distance_km - 120) * 230
                return cost, f"{distance_km:.0f} км / >20т / Длинномер (+230₽/км)"

    base = 18000 + distance_km * 150
    return base, "Стандартный расчёт"
# ===== Калькулятор стоимости доставки =====
class QuoteItem(BaseModel):
    category: str
    subtype: str
    quantity: int


class QuoteRequest(BaseModel):
    upload_lat: float
    upload_lon: float
    transport_type: str  # "auto" | "manipulator" | "long_haul"
    forbidden_types: list[str] = []
    items: list[QuoteItem]


@app.post("/quote")
async def quote(req: QuoteRequest):
    factories = load_json(FACTORIES_FILE)
    vehicles = load_json(VEHICLES_FILE)

    if not factories:
        return JSONResponse(status_code=400, content={"detail": "Нет данных о производствах"})
    if not vehicles:
        return JSONResponse(status_code=400, content={"detail": "Нет данных о машинах"})

    # === 1. Общий вес ===
    total_weight = 0.0
    for item in req.items:
        for f in factories:
            for p in f.get("products", []):
                if p["category"] == item.category and p["subtype"] == item.subtype:
                    total_weight += p["weight_ton"] * item.quantity

    # === 2. Максимальная грузоподъёмность по тегу ===
    def type_capacity(tag: str) -> float:
        caps = [v.get("capacity_ton", v.get("capacity", 0)) for v in vehicles if v.get("tag") == tag]
        if not caps:
            return max(v.get("capacity_ton", v.get("capacity", 0)) for v in vehicles)
        return max(caps)

    # === 3. Определяем тип транспорта ===
    if req.transport_type == "auto":
        possible_types = sorted({v.get("tag") for v in vehicles if v.get("tag") in ("manipulator", "long_haul")})
        if not possible_types:
            largest = max(vehicles, key=lambda v: v.get("capacity_ton", 0))
            transport_type = largest.get("tag", "long_haul")
        else:
            best_type, best_total_delivery = None, float("inf")
            first_factory = factories[0]
            sample_dist = get_cached_distance(first_factory["lat"], first_factory["lon"],
                                              req.upload_lat, req.upload_lon)
            for t in possible_types:
                cap = type_capacity(t)
                if cap <= 0:
                    continue
                cost_per_trip, _ = get_delivery_cost(t, sample_dist, total_weight)
                trips = math.ceil(total_weight / cap)
                total_delivery = cost_per_trip * trips
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
                if p["category"] == item.category and p["subtype"] == item.subtype:
                    dist = get_cached_distance(f["lat"], f["lon"], req.upload_lat, req.upload_lon)
                    mat_cost = p["price"] * item.quantity
                    weight_here = p["weight_ton"] * item.quantity
                    del_cost_per_trip, tariff_info = get_delivery_cost(transport_type, dist, weight_here)
                    total = mat_cost + del_cost_per_trip
                    if best is None or total < best[0]:
                        best = (total, f, p, dist, mat_cost, del_cost_per_trip, tariff_info)

        if best:
            total, f, p, dist, mat_cost, del_cost_per_trip, tariff_info = best
            shipment_details.append({
                "товар": f"{p['category']} ({p['subtype']})",
                "завод": f["name"],
                "машина": transport_type,
                "кол-во": item.quantity,
                "вес_тонн": round(p["weight_ton"] * item.quantity, 2),
                "расстояние_км": round(dist, 2),
                "стоимость_материала": mat_cost,
                "стоимость_доставки": round(del_cost_per_trip, 2),
                "тариф": tariff_info,
                "итого": round(total, 2),
            })

    # === 5. Расчёт количества рейсов по каждому заводу ===
    cap = type_capacity(transport_type)
    factory_ship = {}
    for d in shipment_details:
        f = d["завод"]
        factory_ship.setdefault(f, {"weight": 0.0, "trips": 0})
        factory_ship[f]["weight"] += d["вес_тонн"]

    total_trips = 0
    for f, info in factory_ship.items():
        trips = math.ceil(info["weight"] / cap) if cap > 0 else 0
        info["trips"] = trips
        total_trips += trips

    # === 6. Пересчёт доставки с учётом количества рейсов ===
    for d in shipment_details:
        trips = factory_ship.get(d["завод"], {}).get("trips", 1)
        d["стоимость_доставки"] = round(d["стоимость_доставки"] * trips, 2)
        d["итого"] = round(d["стоимость_материала"] + d["стоимость_доставки"], 2)

    total_material_cost = sum(d["стоимость_материала"] for d in shipment_details)
    total_delivery_cost = sum(d["стоимость_доставки"] for d in shipment_details)

    return {
        "детали": shipment_details,
        "общий_вес": round(total_weight, 2),
        "тип_транспорта": transport_type,
        "количество_рейсов": total_trips,
        "общая_стоимость_материала": round(total_material_cost, 2),
        "общая_стоимость_доставки": round(total_delivery_cost, 2),
        "итого": round(total_material_cost + total_delivery_cost, 2),
        "factories_info": {
            f: {"вес_тонн": round(info["weight"], 2), "рейсы": info["trips"]}
            for f, info in factory_ship.items()
        }
    }


# ===== HTML маршруты =====
@app.get("/")
def index():
    return FileResponse("static/index.html")

@app.get("/admin")
def admin_page():
    return FileResponse("static/admin.html")

@app.get("/calculator")
def calculator_page():
    return FileResponse("static/calculator.html")


# ===== Локальный запуск =====
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
