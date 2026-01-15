"""
Скрипт для миграции данных из JSON файлов в PostgreSQL
"""
import json
import os
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session
from backend.core.database import SessionLocal, init_db
from backend.models.db_models import Category, Factory, Product, Tariff, TariffChangeLog
from backend.core.logger import get_logger

log = get_logger("db_migration")

STORAGE_PATH = os.path.join("backend", "storage")
FACTORIES_FILE = os.path.join(STORAGE_PATH, "factories_products.json")
TARIFFS_FILE = os.path.join(STORAGE_PATH, "tariffs.json")


def migrate_factories_and_products(db: Session):
    """Миграция заводов и товаров из JSON в БД"""
    if not os.path.exists(FACTORIES_FILE):
        log.warning(f"Файл {FACTORIES_FILE} не найден, пропускаем миграцию")
        return
    
    log.info("Начинаем миграцию factories и products...")
    
    with open(FACTORIES_FILE, "r", encoding="utf-8") as f:
        factories_products = json.load(f)
    
    # Очищаем существующие данные
    db.query(Product).delete()
    db.query(Factory).delete()
    db.commit()
    
    factory_map = {}  # Для отслеживания уже созданных заводов
    category_map = {}  # Для отслеживания уже созданных категорий
    products_count = 0
    
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
                db.flush()  # Получаем ID
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
            products_count += 1
    
    db.commit()
    log.info(f"✅ Мигрировано {len(factory_map)} заводов и {products_count} товаров")


def migrate_tariffs(db: Session):
    """Миграция тарифов из JSON в БД"""
    if not os.path.exists(TARIFFS_FILE):
        log.warning(f"Файл {TARIFFS_FILE} не найден, пропускаем миграцию")
        return
    
    log.info("Начинаем миграцию tariffs...")
    
    with open(TARIFFS_FILE, "r", encoding="utf-8") as f:
        tariffs = json.load(f)
    
    # Очищаем существующие данные
    db.query(Tariff).delete()
    db.commit()
    
    for tariff_data in tariffs:
        # legacy weight_if parsing: "≤20", ">20", "any"
        weight_if = tariff_data.get("weight_if", "any") or "any"
        weight_condition = (tariff_data.get("weight_condition") or "").strip().lower()
        weight_threshold = tariff_data.get("weight_threshold", None)
        if not weight_condition:
            s = str(weight_if).strip().lower().replace(" ", "")
            if s in ("", "any", "все", "любая", "-"):
                weight_condition, weight_threshold = "any", None
            elif s.startswith(("≤", "<=")):
                weight_condition = "le"
                try:
                    weight_threshold = float(s.replace("≤", "").replace("<=", "") or 0) or None
                except Exception:
                    weight_threshold = None
            elif s.startswith((">",)):
                weight_condition = "gt"
                try:
                    weight_threshold = float(s.replace(">", "") or 0) or None
                except Exception:
                    weight_threshold = None
            else:
                weight_condition, weight_threshold = "any", None

        tariff = Tariff(
            name=tariff_data.get("название", ""),
            capacity=tariff_data.get("грузоподъёмность", 0.0),
            tag=tariff_data.get("tag", ""),
            weight_if=weight_if,
            weight_condition=weight_condition or "any",
            weight_threshold=weight_threshold,
            min_distance=tariff_data.get("min_distance", 0.0),
            max_distance=tariff_data.get("max_distance", 0.0),
            base=tariff_data.get("base", 0.0),
            per_km=tariff_data.get("per_km", 0.0),
            radius_limit_km=tariff_data.get("radius_limit_km", None),
            service_type=(tariff_data.get("service_type") or "delivery"),
            self_loading=bool(tariff_data.get("self_loading", False)),
            unload_capability=(tariff_data.get("unload_capability") or "none"),
            is_active=bool(tariff_data.get("is_active", True)),
            description=tariff_data.get("описание", ""),
            notes=tariff_data.get("заметки", "")
        )
        db.add(tariff)
    
    db.commit()
    log.info(f"✅ Мигрировано {len(tariffs)} тарифов")


def create_default_admin(db: Session):
    """Создание администратора по умолчанию"""
    from backend.models.db_models import User, UserRole
    from backend.core.auth import get_password_hash
    
    admin_username = os.getenv("ADMIN_USERNAME", "admin")
    admin_password = os.getenv("ADMIN_PASSWORD", "admin")
    
    existing_admin = db.query(User).filter(User.username == admin_username).first()
    if existing_admin:
        # В dev окружении удобно синхронизировать пароль из ENV
        existing_admin.hashed_password = get_password_hash(admin_password)
        existing_admin.role = UserRole.ADMIN
        existing_admin.is_active = True
        db.commit()
        log.info(f"✅ Пароль администратора {admin_username} обновлён из ENV")
        return
    
    admin = User(
        username=admin_username,
        hashed_password=get_password_hash(admin_password),
        role=UserRole.ADMIN,
        is_active=True
    )
    db.add(admin)
    db.commit()
    log.info(f"✅ Создан администратор: {admin_username} / {admin_password}")


def run_migration():
    """Запуск полной миграции"""
    log.info("🚀 Запуск миграции данных в PostgreSQL...")
    
    # Инициализируем БД
    init_db()
    
    db = SessionLocal()
    try:
        ensure_catalog_normalization(db)
        ensure_tariffs_schema(db)
        
        # Создаём администратора
        create_default_admin(db)
        
        # Мигрируем данные
        migrate_factories_and_products(db)
        migrate_tariffs(db)
        
        log.info("✅ Миграция завершена успешно")
    except Exception as e:
        log.error(f"❌ Ошибка при миграции: {e}")
        db.rollback()
        raise
    finally:
        db.close()


def ensure_catalog_normalization(db: Session) -> None:
    """Простейшая миграция схемы под нормализацию categories/products.

    В проекте нет Alembic, поэтому делаем идемпотентные SQL-операции:
    - создаём таблицу categories при отсутствии
    - добавляем products.category_id при отсутствии
    - переносим данные из products.category -> categories + products.category_id
    - создаём индексы для уникальности/поиска
    """

    bind = db.get_bind()
    insp = inspect(bind)

    # 1) categories
    if not insp.has_table("categories"):
        log.info("🧱 Создаём таблицу categories...")
        Category.__table__.create(bind=bind, checkfirst=True)

    # 2) products.category_id
    if insp.has_table("products"):
        cols = {c["name"] for c in insp.get_columns("products")}
        if "category_id" not in cols:
            log.info("🧱 Добавляем products.category_id...")
            db.execute(text("ALTER TABLE products ADD COLUMN category_id INTEGER"))
            db.commit()

        # 3) наполняем categories из products.category и проставляем FK
        # (актуально при переходе со старой схемы, где category была строкой)
        try:
            db.execute(
                text(
                    """
                    INSERT INTO categories (name)
                    SELECT DISTINCT category
                    FROM products
                    WHERE category IS NOT NULL AND category <> ''
                    ON CONFLICT (name) DO NOTHING
                    """
                )
            )
            db.execute(
                text(
                    """
                    UPDATE products p
                    SET category_id = c.id
                    FROM categories c
                    WHERE p.category_id IS NULL
                      AND p.category IS NOT NULL
                      AND p.category = c.name
                    """
                )
            )
            db.commit()
        except Exception as e:
            db.rollback()
            log.warning("⚠️ Не удалось перенести category->category_id: %s", e)

        # 4) индексы (безопасно, если уже есть)
        # Уникальность: factory_id + category_id + subtype
        try:
            db.execute(
                text(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS uq_products_factory_category_subtype_idx
                    ON products (factory_id, category_id, subtype)
                    """
                )
            )
            db.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_products_category_id_subtype
                    ON products (category_id, subtype)
                    """
                )
            )
            db.commit()
        except Exception as e:
            db.rollback()
            log.warning("⚠️ Не удалось создать индексы products: %s", e)


def ensure_tariffs_schema(db: Session) -> None:
    """Идемпотентное расширение схемы tariffs под новые поля админки.

    В проекте нет Alembic, поэтому добавляем колонки через ALTER TABLE IF NEEDED.
    """

    bind = db.get_bind()
    insp = inspect(bind)

    if not insp.has_table("tariffs"):
        # Таблица создастся через Base.metadata.create_all(), но на всякий случай:
        log.info("🧱 Таблица tariffs отсутствует — создаём...")
        Tariff.__table__.create(bind=bind, checkfirst=True)
        return

    cols = {c["name"] for c in insp.get_columns("tariffs")}

    def _add_col(sql: str) -> None:
        try:
            db.execute(text(sql))
            db.commit()
        except Exception as e:
            db.rollback()
            log.warning("⚠️ Не удалось выполнить миграцию tariffs: %s (%s)", sql, e)

    # Новые поля веса
    if "weight_condition" not in cols:
        _add_col("ALTER TABLE tariffs ADD COLUMN weight_condition VARCHAR(10) NOT NULL DEFAULT 'any'")
    if "weight_threshold" not in cols:
        _add_col("ALTER TABLE tariffs ADD COLUMN weight_threshold DOUBLE PRECISION NULL")

    # Радиус / ограничения
    if "radius_limit_km" not in cols:
        _add_col("ALTER TABLE tariffs ADD COLUMN radius_limit_km DOUBLE PRECISION NULL")
    if "radius_center_lat" not in cols:
        _add_col("ALTER TABLE tariffs ADD COLUMN radius_center_lat DOUBLE PRECISION NULL")
    if "radius_center_lon" not in cols:
        _add_col("ALTER TABLE tariffs ADD COLUMN radius_center_lon DOUBLE PRECISION NULL")

    # Разделение по назначению (доставка/разгрузка)
    if "service_type" not in cols:
        _add_col("ALTER TABLE tariffs ADD COLUMN service_type VARCHAR(20) NOT NULL DEFAULT 'delivery'")

    # Самозагрузка / разгрузка
    if "self_loading" not in cols:
        _add_col("ALTER TABLE tariffs ADD COLUMN self_loading BOOLEAN NOT NULL DEFAULT FALSE")
    if "unload_capability" not in cols:
        _add_col("ALTER TABLE tariffs ADD COLUMN unload_capability VARCHAR(20) NOT NULL DEFAULT 'none'")
    if "unload_tags" not in cols:
        # Postgres: JSONB предпочтительнее, но если тип недоступен — логируем и продолжаем
        _add_col("ALTER TABLE tariffs ADD COLUMN unload_tags JSONB NULL")

    # Флаг активности
    if "is_active" not in cols:
        _add_col("ALTER TABLE tariffs ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT TRUE")

    # Аудит (кто/когда)
    if "created_by_user_id" not in cols:
        _add_col("ALTER TABLE tariffs ADD COLUMN created_by_user_id INTEGER NULL")
    if "updated_by_user_id" not in cols:
        _add_col("ALTER TABLE tariffs ADD COLUMN updated_by_user_id INTEGER NULL")

    # Таблица истории изменений (если отсутствует)
    if not insp.has_table("tariff_change_logs"):
        log.info("🧱 Создаём таблицу tariff_change_logs...")
        TariffChangeLog.__table__.create(bind=bind, checkfirst=True)


if __name__ == "__main__":
    run_migration()
