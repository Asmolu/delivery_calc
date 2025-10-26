from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import json
import math
import os

app = FastAPI()

# Разрешаем запросы из любого источника (чтобы HTML мог обращаться к API)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def get_delivery_cost(transport_type: str, distance_km: float) -> float:
    """
    Возвращает стоимость перевозки за 1 рейс
    на основе типа машины и расстояния.
    """

    # Тарифы для манипулятора (пример — из таблицы)
    manipulator_tariffs = [
        (30, 16000),
        (60, 18000),
        (80, 20000),
        (100, 22000),
        (120, 24000),
    ]
    manipulator_per_km = 200  # после 120 км

    # Тарифы для длинномера MAN / DAF
    long_haul_tariffs = [
        (30, 19000),
        (60, 22000),
        (80, 24000),
        (100, 25000),
        (120, 28000),
    ]
    long_haul_per_km = 230  # после 120 км

    if "манипулятор" in transport_type.lower():
        for limit, price in manipulator_tariffs:
            if distance_km <= limit:
                return price
        # дальше 120 км
        return manipulator_tariffs[-1][1] + (distance_km - 120) * manipulator_per_km

    elif "man" in transport_type.lower() or "daf" in transport_type.lower() or "long" in transport_type.lower():
        for limit, price in long_haul_tariffs:
            if distance_km <= limit:
                return price
        return long_haul_tariffs[-1][1] + (distance_km - 120) * long_haul_per_km

    # По умолчанию — как манипулятор
    for limit, price in manipulator_tariffs:
        if distance_km <= limit:
            return price
    return manipulator_tariffs[-1][1] + (distance_km - 120) * manipulator_per_km

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

    # ===== 3. Определяем тип транспорта =====
    if req.transport_type == "auto":
        # получаем список тегов всех машин
        available_tags = {v.get("tag") for v in vehicles}

        # если вес ≤ 20 т и есть манипулятор — выбираем его
        if total_weight <= 20 and "manipulator" in available_tags:
            transport_type = "manipulator"

        # если вес > 20 т и есть длинномер — выбираем его
        elif total_weight > 20 and "long_haul" in available_tags:
            transport_type = "long_haul"

        # если нет машин нужного типа — выбираем максимальную грузоподъёмность
        else:
            largest_vehicle = max(vehicles, key=lambda v: v.get("capacity_ton", 0))
            transport_type = largest_vehicle.get("tag", "long_haul")
    else:
        # пользователь выбрал вручную
        transport_type = req.transport_type


    # ===== 3. Собираем детали перевозок =====
    shipment_details = []
    for item in req.items:
        best = None
        for f in factories:
            for p in f.get("products", []):
                if p["category"] == item.category and p["subtype"] == item.subtype:
                    dist = calculate_distance(f["lat"], f["lon"], req.upload_lat, req.upload_lon)
                    mat_cost = p["price"] * item.quantity
                    del_cost = get_delivery_cost(transport_type, dist)
                    total = mat_cost + del_cost
                    if (best is None) or (total < best[0]):
                        best = (total, f, p, dist, mat_cost, del_cost)

        if best:
            total, f, p, dist, mat_cost, del_cost = best
            shipment_details.append({
                "товар": f"{p['category']} ({p['subtype']})",
                "завод": f["name"],
                "машина": transport_type,
                "кол-во": item.quantity,
                "вес_тонн": round(p["weight_ton"] * item.quantity, 2),
                "расстояние_км": round(dist, 2),
                "стоимость_материала": mat_cost,
                "стоимость_доставки": round(del_cost, 2),
                "итого": round(total, 2),
            })

    # ===== 4. Определяем грузоподъёмность по тегу =====
    def type_capacity(t: str) -> float:
        """
        Возвращает максимальную грузоподъёмность среди машин заданного типа.
        Тип берётся из поля 'tag' (manipulator / long_haul).
        """
        caps = []

        for v in vehicles:
            tag = v.get("tag")
            if tag == t:
                caps.append(v.get("capacity_ton", v.get("capacity", 0)))

        # если машин такого типа нет — берём максимальную среди всех
        if not caps:
            return max(v.get("capacity_ton", v.get("capacity", 0)) for v in vehicles)

        return max(caps)

    cap = type_capacity(transport_type)

    factory_ship = {}
    for d in shipment_details:
        f = d["завод"]
        factory_ship.setdefault(f, {"weight": 0.0, "trips": 0})
        factory_ship[f]["weight"] += d["вес_тонн"]

    total_trips = 0
    for f, info in factory_ship.items():
        trips = math.ceil(info["weight"] / cap) if cap > 0 else 0
        factory_ship[f]["trips"] = trips
        total_trips += trips

    # ===== 6. Пересчитываем доставку с учётом рейсов =====
    for d in shipment_details:
        factory_name = d["завод"]
        trips = factory_ship.get(factory_name, {}).get("trips", 1)
        d["стоимость_доставки"] = round(d["стоимость_доставки"] * trips, 2)
        d["итого"] = round(d["стоимость_материала"] + d["стоимость_доставки"], 2)

    # ===== 7. Итоговые суммы =====
    total_material_cost = sum(d["стоимость_материала"] for d in shipment_details)
    total_delivery_cost = sum(d["стоимость_доставки"] for d in shipment_details)

    # ===== 8. Ответ =====
    return {
        "детали": shipment_details,
        "общий_вес": round(total_weight, 2),
        "тип_транспорта": transport_type,
        "количество_рейсов": total_trips,
        "общая_стоимость_материала": round(total_material_cost, 2),
        "общая_стоимость_доставки": round(total_delivery_cost, 2),
        "итого": round(total_material_cost + total_delivery_cost, 2),
        "factories_info": {
            f: {
                "вес_тонн": round(info["weight"], 2),
                "рейсы": info["trips"]
            }
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
