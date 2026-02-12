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
    # Синхронизация с первоисточником (Google Sheets):
    # - upsert новых/изменённых строк
    # - удаление из БД записей, которых больше нет в Google Sheets

    factory_map: dict[str, Factory] = {}
    category_map: dict[str, Category] = {}

    seen_factory_names: set[str] = set()
    seen_product_keys: set[tuple[str, str, str]] = set()

    # кешируем текущие сущности (для быстрого upsert)
    existing_factories = {f.name: f for f in db.query(Factory).all()}

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

            factory_name = str(factory_data["name"]).strip()
            if not factory_name:
                continue
            seen_factory_names.add(factory_name)

            # upsert factory (preserve is_active)
            factory = factory_map.get(factory_name) or existing_factories.get(factory_name)
            if not factory:
                factory = Factory(
                    name=factory_name,
                    lat=factory_data.get("lat"),
                    lon=factory_data.get("lon"),
                    contact=factory_data.get("contact"),
                    update_date=factory_data.get("update_date"),
                    is_active=True,
                )
                db.add(factory)
                db.flush()
                existing_factories[factory_name] = factory
            else:
                # обновляем координаты/контакт, но не трогаем is_active
                factory.lat = factory_data.get("lat")
                factory.lon = factory_data.get("lon")
                factory.contact = factory_data.get("contact")
                factory.update_date = factory_data.get("update_date")
                db.add(factory)
            factory_map[factory_name] = factory

            subtype = str(item.get("subtype", "") or "").strip()
            if not subtype:
                continue

            seen_product_keys.add((factory_name, category, subtype))

            # upsert product (preserve is_active)
            existing_product = (
                db.query(Product)
                .filter(
                    Product.factory_id == factory.id,
                    Product.category_id == cat_obj.id,
                    Product.subtype == subtype,
                )
                .first()
            )
            if not existing_product:
                existing_product = Product(
                    category=category,  # legacy (for debug/backward compat)
                    subtype=subtype,
                    weight_per_item=item.get("weight_per_item", 0.0),
                    special_threshold=item.get("special_threshold", 0.0),
                    max_per_trip=item.get("max_per_trip", 0.0),
                    price=factory_data.get("price", 0.0),
                    factory_id=factory.id,
                    category_id=cat_obj.id,
                    is_active=True,
                )
                db.add(existing_product)
            else:
                existing_product.category = category
                existing_product.weight_per_item = item.get("weight_per_item", 0.0)
                existing_product.special_threshold = item.get("special_threshold", 0.0)
                existing_product.max_per_trip = item.get("max_per_trip", 0.0)
                existing_product.price = factory_data.get("price", 0.0)
                db.add(existing_product)

    if not seen_factory_names and not seen_product_keys:
        raise ValueError("Google Sheets вернул пустой набор заводов/товаров; синхронизация остановлена")

    # Удаляем товары, отсутствующие в первоисточнике
    removed_products = 0
    existing_products = (
        db.query(Product, Factory, Category)
        .join(Factory, Product.factory_id == Factory.id)
        .join(Category, Product.category_id == Category.id)
        .all()
    )
    for p, f, c in existing_products:
        key = (str(f.name or "").strip(), str(c.name or "").strip(), str(p.subtype or "").strip())
        if key in seen_product_keys:
            continue
        db.delete(p)
        removed_products += 1

    db.flush()

    # Удаляем заводы, которых больше нет в Google Sheets
    removed_factories = 0
    for f in db.query(Factory).all():
        fname = str(f.name or "").strip()
        if fname in seen_factory_names:
            continue
        db.delete(f)
        removed_factories += 1

    db.commit()
    log.info(
        "✅ Синхронизировано из Google Sheets: %s заводов, %s категорий, удалено товаров=%s, удалено заводов=%s",
        len(factory_map),
        len(category_map),
        removed_products,
        removed_factories,
    )


def _save_tariffs_to_db(db: Session, tariffs: list) -> None:
    """Сохранение тарифов в БД"""
    # Очищаем существующие данные
    db.query(Tariff).delete()
    db.commit()
    
    for tariff_data in tariffs:
        weight_condition = (tariff_data.get("weight_condition") or "any").strip().lower()
        weight_threshold = tariff_data.get("weight_threshold", None)
        if weight_condition not in ("any", "le", "gt"):
            # legacy fallback
            weight_condition = "any"
            weight_threshold = None

        tariff = Tariff(
            name=tariff_data.get("название", ""),
            capacity=tariff_data.get("грузоподъёмность", 0.0),
            tag=tariff_data.get("tag", ""),
            weight_if=tariff_data.get("weight_if", "any"),
            weight_condition=weight_condition,
            weight_threshold=weight_threshold,
            min_distance=tariff_data.get("min_distance", 0.0),
            max_distance=tariff_data.get("max_distance", 0.0),
            base=tariff_data.get("base", 0.0),
            per_km=tariff_data.get("per_km", 0.0),
            load_zone=tariff_data.get("load_zone", None),
            unload_zone=tariff_data.get("unload_zone", None),
            service_type=(tariff_data.get("service_type") or "delivery"),
            self_loading=bool(tariff_data.get("self_loading", False)),
            unload_capability=(tariff_data.get("unload_capability") or "none"),
            is_active=bool(tariff_data.get("is_active", True)),
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
    """DEPRECATED: тарифы больше не загружаются из Google Sheets.

    Тарифы (машины) теперь создаются/редактируются через админку сайта.
    """
    log.warning("⚠️ load_tariffs_from_google вызван, но тарифы из Google Sheets больше не поддерживаются")
    return []



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

        # Парсим таблицу (ВАЖНО: Vehicles больше не трогаем)
        result = parse_google_sheet()
        factories_products = result.get("products", {})

        # Сохраняем в БД, если сессия предоставлена
        if db:
            _save_factories_to_db(db, factories_products)

        # Также сохраняем в JSON для обратной совместимости
        os.makedirs(STORAGE_PATH, exist_ok=True)
        with open(FACTORIES_FILE, "w", encoding="utf-8") as f:
            json.dump(factories_products, f, ensure_ascii=False, indent=2)
        log.info(
            f"✅ Успешно обновлены данные: "
            f"{len(factories_products)} категорий товаров."
        )

    except Exception as e:
        log.error(f"❌ Ошибка при инициализации данных: {e}")


def load_factories_and_tariffs_from_db(db: Session) -> Tuple[Dict, List]:
    """
    Загружает factories и tariffs из PostgreSQL.
    Возвращает кортеж: (factories_products, tariffs) в формате, совместимом со старым API.
    """
    # Загружаем только активные товары активных заводов (чтобы “отрезание” влияло на расчёт)
    products = (
        db.query(Product)
        .join(Factory, Product.factory_id == Factory.id)
        .filter(Factory.is_active.is_(True), Product.is_active.is_(True))
        .all()
    )
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
                "id": product.factory.id,
                "name": product.factory.name,
                "lat": product.factory.lat,
                "lon": product.factory.lon,
                "price": product.price,
                "contact": product.factory.contact,
                "update_date": getattr(product.factory, "update_date", None),
            }
        })
    
    # Загружаем тарифы
    tariffs_db = db.query(Tariff).all()
    tariffs = []
    
    for tariff in tariffs_db:
        tariffs.append({
            "id": tariff.id,
            "название": tariff.name,
            "грузоподъёмность": tariff.capacity,
            "tag": tariff.tag,
            "weight_if": tariff.weight_if,
            "weight_condition": getattr(tariff, "weight_condition", "any") or "any",
            "weight_threshold": getattr(tariff, "weight_threshold", None),
            "min_distance": tariff.min_distance,
            "max_distance": tariff.max_distance,
            "base": tariff.base,
            "per_km": tariff.per_km,
            "load_zone": getattr(tariff, "load_zone", None),
            "unload_zone": getattr(tariff, "unload_zone", None),
            "service_type": getattr(tariff, "service_type", "delivery") or "delivery",
            "self_loading": bool(getattr(tariff, "self_loading", False)),
            "unload_capability": getattr(tariff, "unload_capability", "none") or "none",
            "unload_tags": getattr(tariff, "unload_tags", None),
            "base_transport_name": getattr(tariff, "base_transport_name", None),
            "base_transport_tag": getattr(tariff, "base_transport_tag", None),
            "is_active": bool(getattr(tariff, "is_active", True)),
            "unloading_included": bool(getattr(tariff, "unloading_included", False)),
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
            # В новом этапе тарифы могут быть пустыми (их создают в админке),
            # поэтому не требуем, чтобы оба набора были непустыми.
            if factories_products or tariffs:
                log.info(
                    f"✅ Загружено из БД: {len(factories_products)} категорий, {len(tariffs)} тарифов"
                )
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
