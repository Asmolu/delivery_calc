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


# ===== Вспомогательные функции =====
def load_json(filename):
    if not os.path.exists(filename):
        return []
    with open(filename, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []


def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ===== Загрузка данных =====
factories = load_json(FACTORIES_FILE)
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
    return load_json(FACTORIES_FILE)


@app.post("/api/factories")
async def add_factory(factory: Factory):
    factories = load_json(FACTORIES_FILE)
    if any(f["name"] == factory.name for f in factories):
        return JSONResponse(status_code=400, content={"detail": "Такое производство уже существует"})
    factories.append(factory.dict() | {"products": []})
    save_json(FACTORIES_FILE, factories)
    return {"message": f"Производство {factory.name} добавлено"}


@app.delete("/api/factories/{factory_name}")
async def delete_factory(factory_name: str):
    factories = load_json(FACTORIES_FILE)
    updated = [f for f in factories if f["name"] != factory_name]
    if len(updated) == len(factories):
        return JSONResponse(status_code=404, content={"detail": "Производство не найдено"})
    save_json(FACTORIES_FILE, updated)
    return {"message": f"Производство {factory_name} удалено"}


# ======== МАШИНЫ (vehicles) ========

@app.get("/api/vehicles")
def get_vehicles():
    """Возвращает список всех машин"""
    return load_json(VEHICLES_FILE)

@app.get("/api/categories")
def get_categories():
    factories = load_json(FACTORIES_FILE)
    categories = {}

    for f in factories:
        for p in f.get("products", []):
            cat = p["category"]
            sub = p["subtype"]
            if cat not in categories:
                categories[cat] = set()
            categories[cat].add(sub)

    # Преобразуем множества в списки
    result = {cat: sorted(list(subs)) for cat, subs in categories.items()}
    return result


@app.post("/api/vehicles")
async def add_vehicle(request: Request):
    """Добавляет новую машину с тегом"""
    data = await request.json()
    name = data.get("name")
    capacity = data.get("capacity_ton") or data.get("capacity")
    tag = data.get("tag")  # может быть "manipulator" или "long_haul"

    if not name or not capacity:
        return JSONResponse(status_code=400, content={"detail": "Укажите название и грузоподъёмность"})
    if tag not in ["manipulator", "long_haul"]:
        return JSONResponse(status_code=400, content={"detail": "Неверный тег. Допустимо: manipulator / long_haul"})

    vehicles = load_json(VEHICLES_FILE)
    # проверяем на дубликат
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

# ===== API: Товары производства =====
@app.post("/api/factories/{factory_name}/product")
async def add_product(factory_name: str, product: Product):
    factories = load_json(FACTORIES_FILE)
    for f in factories:
        if f["name"] == factory_name:
            f["products"].append(product.dict())
            save_json(FACTORIES_FILE, factories)
            return {"message": f"Товар добавлен к {factory_name}"}
    return JSONResponse(status_code=404, content={"detail": "Производство не найдено"})


@app.delete("/api/factories/{factory_name}/product/{subtype}")
async def delete_product(factory_name: str, subtype: str):
    factories = load_json(FACTORIES_FILE)
    for f in factories:
        if f["name"] == factory_name:
            f["products"] = [p for p in f.get("products", []) if p["subtype"] != subtype]
            save_json(FACTORIES_FILE, factories)
            return {"message": f"Товар {subtype} удалён из {factory_name}"}
    return JSONResponse(status_code=404, content={"detail": "Производство не найдено"})
# ===== Геометрия: расстояние по координатам (Haversine) =====
import math
import requests

# 🔑 Твой персональный API-ключ OpenRouteService
ORS_API_KEY = "eyJvcmciOiI1YjNjZTM1OTc4NTExMTAwMDFjZjYyNDgiLCJpZCI6IjZmNDMwM2U5NWY1NDQ1N2ZiMmZkZGY5YmUyNWFkZDAyIiwiaCI6Im11cm11cjY0In0="

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
    с использованием OpenRouteService.
    Если API недоступен, возвращает Haversine-дистанцию.
    """
    try:
        url = "https://api.openrouteservice.org/v2/directions/driving-car"
        headers = {
            "Authorization": ORS_API_KEY,
            "Content-Type": "application/json",
        }
        body = {
            "coordinates": [[lon1, lat1], [lon2, lat2]]
        }

        response = requests.post(url, json=body, headers=headers, timeout=10)
        print("🔍 Ответ ORS:", response.text)  # для проверки
        if response.status_code == 200:
            data = response.json()
            # 🔧 Новая структура
            if "routes" in data and len(data["routes"]) > 0:
                dist_m = data["routes"][0]["segments"][0]["distance"]
                return round(dist_m / 1000, 2)
            else:
                print("⚠️ Неожиданная структура ответа ORS")
                return calculate_distance(lat1, lon1, lat2, lon2)
        else:
            print("⚠️ Ошибка OpenRouteService:", response.text)
            return calculate_distance(lat1, lon1, lat2, lon2)
    except Exception as e:
        print("⚠️ Ошибка при обращении к ORS:", e)
        return calculate_distance(lat1, lon1, lat2, lon2)


def get_delivery_cost(transport_type: str, distance_km: float, weight_ton: float = 0) -> tuple[float, str]:
    """
    Возвращает (стоимость_за_1_рейс, описание_тарифа)
    transport_type: "manipulator" | "long_haul"
    """
    # === Манипулятор ===
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

    # === Длинномер ===
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

    # fallback (если вдруг пришёл другой тег)
    base = 18000 + distance_km * 150
    return base, "Стандартный расчёт"


# ===== Калькулятор =====
class QuoteItem(BaseModel):
    category: str
    subtype: str
    quantity: int


class QuoteRequest(BaseModel):
    upload_lat: float
    upload_lon: float
    transport_type: str  # "auto" | "manipulator" | "truck"
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

    # ===== 1. Считаем общий вес =====
    total_weight = 0.0
    for item in req.items:
        for f in factories:
            for p in f.get("products", []):
                if p["category"] == item.category and p["subtype"] == item.subtype:
                    total_weight += p["weight_ton"] * item.quantity


    # ===== вспомогательная: максимальная грузоподъёмность по тегу =====
    def type_capacity(t: str) -> float:
        caps = [v.get("capacity_ton", v.get("capacity", 0)) for v in vehicles if v.get("tag") == t]
        if not caps:
            return max(v.get("capacity_ton", v.get("capacity", 0)) for v in vehicles)
        return max(caps)

    # ===== 3. Определяем тип транспорта =====
    if req.transport_type == "auto":
        possible_types = sorted({v.get("tag") for v in vehicles if v.get("tag") in ("manipulator", "long_haul")})
        if not possible_types:
            largest = max(vehicles, key=lambda v: v.get("capacity_ton", 0))
            transport_type = largest.get("tag", "long_haul")
        else:
            best_type, best_total_delivery = None, float("inf")
            # возьмём первую фабрику для прикидки дистанции
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

    # ===== 4. Выбираем лучший завод по каждой позиции (стоимость 1 рейса) =====
    shipment_details = []
    for item in req.items:
        best = None  # (total, factory, prod, dist, mat_cost, del_cost, tariff)
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
                "стоимость_доставки": round(del_cost_per_trip, 2),  # пока за 1 рейс
                "тариф": tariff_info,
                "итого": round(total, 2),
            })

    # ===== 5. Рейсы по заводам (по грузоподъёмности выбранного типа) =====
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

    # ===== 6. Пересчёт доставки и итогов с учётом числа рейсов =====
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



# Корень
@app.get("/")
def root():
    return {"message": "Сервис расчёта цены работает!"}


# Локальный запуск
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)

from fastapi.staticfiles import StaticFiles

app.mount("/", StaticFiles(directory="static", html=True), name="static")
