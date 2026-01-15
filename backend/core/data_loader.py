import os
import json
from typing import Dict, List, Tuple
from sqlalchemy.orm import Session
from backend.core.logger import get_logger
from backend.service.factories_parser import parse_google_sheet
from backend.models.db_models import Category, Factory, Product, Tariff

__all__ = [
    "load_factories_from_google",
    "load_tariffs_from_google",
    "rebuild_factories_and_tariffs_from_google",
    "load_factories_and_tariffs",
    "load_factories_and_tariffs_from_db",
]

log = get_logger("data_loader")

# Папка и имена файлов в storage (для обратной совместимости)
STORAGE_PATH = os.path.join("backend", "storage")
FACTORIES_FILE = os.path.join(STORAGE_PATH, "factories_products.json")
TARIFFS_FILE = os.path.join(STORAGE_PATH, "tariffs.json")

def _ensure_storage_dir() -> None:
    os.makedirs(STORAGE_PATH, exist_ok=True)


def _save_factories(factories_products: dict) -> None:
    """Сохранение в JSON (для обратной совместимости)"""
    _ensure_storage_dir()
    with open(FACTORIES_FILE, "w", encoding="utf-8") as f:
        json.dump(factories_products, f, ensure_ascii=False, indent=2)


def _save_tariffs(tariffs: list) -> None:
    """Сохранение в JSON (для обратной совместимости)"""
    _ensure_storage_dir()
    with open(TARIFFS_FILE, "w", encoding="utf-8") as f:
        json.dump(tariffs, f, ensure_ascii=False, indent=2)


def _save_factories_to_db(db: Session, factories_products: dict) -> None:
    """Сохранение заводов и товаров в БД"""
    # Очищаем существующие данные
    db.query(Product).delete()
    db.query(Factory).delete()
    db.commit()
    
    factory_map = {}
    category_map = {}
    
    for category, items in factories_products.items():
        if not isinstance(items, list):
            continue

        # Создаём/получаем категорию
        if category not in category_map:
            cat_obj = db.query(Category).filter(Category.name == category).first()
            if not cat_obj:
                cat_obj = Category(name=category)
                db.add(cat_obj)
                db.flush()
            category_map[category] = cat_obj
        cat_obj = category_map[category]
        
        for item in items:
            factory_data = item.get("factory", {})
            if not factory_data.get("name"):
                continue
            
            factory_name = factory_data["name"]
            
            # Создаём или получаем завод
            if factory_name not in factory_map:
                factory = Factory(
                    name=factory_name,
                    lat=factory_data.get("lat"),
                    lon=factory_data.get("lon"),
                    contact=factory_data.get("contact")
                )
                db.add(factory)
                db.flush()
                factory_map[factory_name] = factory
            else:
                factory = factory_map[factory_name]
            
            # Создаём товар
            product = Product(
                category=category,
                subtype=item.get("subtype", ""),
                weight_per_item=item.get("weight_per_item", 0.0),
                special_threshold=item.get("special_threshold", 0.0),
                max_per_trip=item.get("max_per_trip", 0.0),
                price=factory_data.get("price", 0.0),
                factory_id=factory.id,
                category_id=cat_obj.id,
            )
            db.add(product)
    
    db.commit()
    log.info(f"✅ Сохранено в БД: {len(factory_map)} заводов, {sum(len(items) for items in factories_products.values() if isinstance(items, list))} товаров")


def _save_tariffs_to_db(db: Session, tariffs: list) -> None:
    """Сохранение тарифов в БД"""
    # Очищаем существующие данные
    db.query(Tariff).delete()
    db.commit()
    
    for tariff_data in tariffs:
        tariff = Tariff(
            name=tariff_data.get("название", ""),
            capacity=tariff_data.get("грузоподъёмность", 0.0),
            tag=tariff_data.get("tag", ""),
            weight_if=tariff_data.get("weight_if", "any"),
            min_distance=tariff_data.get("min_distance", 0.0),
            max_distance=tariff_data.get("max_distance", 0.0),
            base=tariff_data.get("base", 0.0),
            per_km=tariff_data.get("per_km", 0.0),
            description=tariff_data.get("описание", ""),
            notes=tariff_data.get("заметки", "")
        )
        db.add(tariff)
    
    db.commit()
    log.info(f"✅ Сохранено в БД: {len(tariffs)} тарифов")


def load_factories_from_google(db: Session = None):
    """Загружает товары+заводы из Google Sheets и сохраняет их в БД и JSON."""
    result = parse_google_sheet()
    factories_products = result.get("products", {})

    # Сохраняем в БД, если сессия предоставлена
    if db:
        _save_factories_to_db(db, factories_products)
    
    # Также сохраняем в JSON для обратной совместимости
    _save_factories(factories_products)
    log.info(
        "✅ Обновлены factories_products из Google Sheets (%s записей)",
        len(factories_products),
    )

    return factories_products


def load_tariffs_from_google(db: Session = None):
    """Загружает тарифы из Google Sheets и сохраняет их в БД и JSON."""
    result = parse_google_sheet()
    tariffs = result.get("tariffs", [])

    # Сохраняем в БД, если сессия предоставлена
    if db:
        _save_tariffs_to_db(db, tariffs)
    
    # Также сохраняем в JSON для обратной совместимости
    _save_tariffs(tariffs)
    log.info("✅ Обновлены tariffs из Google Sheets (%s тарифов)", len(tariffs))

    return tariffs



def rebuild_factories_and_tariffs_from_google(google_sheet_id: str, db: Session = None) -> None:
    """
    Пересоздаёт factories_products и tariffs из Google Sheets в БД и JSON.
    google_sheet_id сюда пробрасываем только для логов — фактически
    вся логика подключения и чтения сидит внутри factories_parser.parse_google_sheet().
    """
    try:
        log.info(
            "📦 Пересоздаём factories_products и tariffs из Google Sheets "
            f"(GOOGLE_SHEET_ID={google_sheet_id})"
        )

        # Парсим таблицу
        result = parse_google_sheet()
        factories_products = result.get("products", {})
        tariffs = result.get("tariffs", [])

        # Сохраняем в БД, если сессия предоставлена
        if db:
            _save_factories_to_db(db, factories_products)
            _save_tariffs_to_db(db, tariffs)

        # Также сохраняем в JSON для обратной совместимости
        os.makedirs(STORAGE_PATH, exist_ok=True)
        with open(FACTORIES_FILE, "w", encoding="utf-8") as f:
            json.dump(factories_products, f, ensure_ascii=False, indent=2)
        with open(TARIFFS_FILE, "w", encoding="utf-8") as f:
            json.dump(tariffs, f, ensure_ascii=False, indent=2)

        log.info(
            f"✅ Успешно обновлены данные: "
            f"{len(factories_products)} категорий товаров, {len(tariffs)} тарифов."
        )

    except Exception as e:
        log.error(f"❌ Ошибка при инициализации данных: {e}")


def load_factories_and_tariffs_from_db(db: Session) -> Tuple[Dict, List]:
    """
    Загружает factories и tariffs из PostgreSQL.
    Возвращает кортеж: (factories_products, tariffs) в формате, совместимом со старым API.
    """
    # Загружаем товары с заводами
    products = db.query(Product).all()
    factories_products = {}
    
    for product in products:
        category = (product.category_rel.name if getattr(product, "category_rel", None) else None) or product.category or ""
        if category not in factories_products:
            factories_products[category] = []
        
        factories_products[category].append({
            "category": category,
            "subtype": product.subtype,
            "weight_per_item": product.weight_per_item,
            "special_threshold": product.special_threshold,
            "max_per_trip": product.max_per_trip,
            "factory": {
                "name": product.factory.name,
                "lat": product.factory.lat,
                "lon": product.factory.lon,
                "price": product.price,
                "contact": product.factory.contact
            }
        })
    
    # Загружаем тарифы
    tariffs_db = db.query(Tariff).all()
    tariffs = []
    
    for tariff in tariffs_db:
        tariffs.append({
            "название": tariff.name,
            "грузоподъёмность": tariff.capacity,
            "tag": tariff.tag,
            "weight_if": tariff.weight_if,
            "min_distance": tariff.min_distance,
            "max_distance": tariff.max_distance,
            "base": tariff.base,
            "per_km": tariff.per_km,
            "описание": tariff.description or "",
            "заметки": tariff.notes or ""
        })
    
    return factories_products, tariffs


def load_factories_and_tariffs(db: Session = None):
    """
    Загружает factories_products и tariffs из БД (приоритет) или JSON (fallback).
    Возвращает кортеж: (factories_products, tariffs)
    """
    # Пытаемся загрузить из БД
    if db:
        try:
            factories_products, tariffs = load_factories_and_tariffs_from_db(db)
            if factories_products and tariffs:
                log.info(f"✅ Загружено из БД: {len(factories_products)} категорий, {len(tariffs)} тарифов")
                return factories_products, tariffs
        except Exception as e:
            log.warning(f"⚠️ Не удалось загрузить из БД: {e}, пробуем JSON")
    
    # Fallback на JSON
    factories_products = {}
    tariffs = []

    # Загружаем товары+заводы
    if os.path.exists(FACTORIES_FILE):
        try:
            with open(FACTORIES_FILE, "r", encoding="utf-8") as f:
                factories_products = json.load(f)
        except Exception as e:
            log.error(f"❌ Ошибка при чтении {FACTORIES_FILE}: {e}")
            factories_products = {}
    else:
        log.warning(f"⚠️ Файл {FACTORIES_FILE} не найден — товаров пока нет.")

    # Загружаем тарифы
    if os.path.exists(TARIFFS_FILE):
        try:
            with open(TARIFFS_FILE, "r", encoding="utf-8") as f:
                tariffs = json.load(f)
        except Exception as e:
            log.error(f"❌ Ошибка при чтении {TARIFFS_FILE}: {e}")
            tariffs = []
    else:
        log.warning(f"⚠️ Файл {TARIFFS_FILE} не найден — тарифов пока нет.")

    return factories_products, tariffs
