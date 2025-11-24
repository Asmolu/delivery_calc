from pathlib import Path
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..core.logger import get_logger
from ..core.data_loader import load_json, save_json, FACTORIES_FILE, TARIFFS_FILE

router = APIRouter()
log = get_logger("routes.info")


class Product(BaseModel):
    category: str
    subtype: str
    quantity: int


class Factory(BaseModel):
    name: str
    lat: float | None = None
    lon: float | None = None
    products: list[Product] = []


class Vehicle(BaseModel):
    name: str
    capacity_ton: float
    tag: str
    distance_min: float
    distance_max: float
    price: float
    per_km: float | None = None


# ===== API: Производства =====
@router.get("/api/factories")
async def get_factories():
    try:
        factories = load_json(FACTORIES_FILE)
        if not factories:
            raise Exception("Не удалось загрузить данные из factories.json")
        return factories
    except Exception as e:
        log.error("Ошибка при загрузке данных о производствах: %s", e)
        raise HTTPException(
            status_code=500,
            detail="Ошибка при загрузке данных о производствах",
        )


@router.post("/api/factories")
async def add_factory(factory: Factory):
    # Добавление заводов идёт только через Google Sheets – заглушка
    return JSONResponse(
        status_code=400,
        content={"detail": "Добавление заводов возможно только через Google Sheets"},
    )


@router.delete("/api/factories/{factory_name}")
async def delete_factory(factory_name: str):
    try:
        factories = load_json(FACTORIES_FILE)
        updated = [f for f in factories if f.get("name") != factory_name]
        if len(updated) == len(factories):
            return JSONResponse(
                status_code=404,
                content={"detail": f"Производство {factory_name} не найдено"},
            )
        save_json(FACTORIES_FILE, updated)
        return {"message": f"Производство {factory_name} удалено"}
    except Exception as e:
        log.error("Ошибка при удалении производства: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ===== API: Тарифы =====
@router.get("/api/tariffs")
async def get_tariffs():
    path = Path(TARIFFS_FILE)

    if not path.exists():
        raise HTTPException(status_code=404, detail="Файл tariffs.json не найден")

    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            content = f.read().strip()

        if not content:
            raise HTTPException(status_code=500, detail="Файл tariffs.json пустой")

        raw = json.loads(content)

        normalized = []
        for t in raw:
            normalized.append(
                {
                    "name": t.get("название") or t.get("name"),
                    "capacity_ton": t.get("грузоподъёмность") or t.get("capacity_ton"),
                    "tag": t.get("тег") or t.get("tag"),
                    "distance_min": t.get("дистанция_мин") or t.get("distance_min"),
                    "distance_max": t.get("дистанция_макс") or t.get("distance_max"),
                    "price": t.get("цена") or t.get("price"),
                    "per_km": t.get("за_км") or t.get("per_km"),
                }
            )

        log.info("API /api/tariffs: отправлено %s тарифов (нормализовано)", len(normalized))
        return normalized

    except json.JSONDecodeError as e:
        log.error("Ошибка в структуре tariffs.json: %s", e)
        raise HTTPException(
            status_code=500, detail=f"Ошибка в структуре tariffs.json: {e}"
        )
    except Exception as e:
        log.error("Ошибка при чтении tariffs.json: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ===== API: Категории =====
@router.get("/api/categories")
async def get_categories():
    try:
        factories = load_json(FACTORIES_FILE)
        categories: dict[str, set[str]] = {}

        for f in factories:
            if not f.get("valid_coords", False):
                continue

            for p in f.get("products", []):
                cat = p.get("category")
                sub = p.get("subtype")
                if not cat or not sub:
                    continue
                categories.setdefault(cat, set()).add(sub)

        return {cat: sorted(list(subs)) for cat, subs in categories.items()}
    except Exception as e:
        log.error("Ошибка при генерации категорий: %s", e)
        return {"detail": f"Ошибка при генерации категорий: {e}"}
