import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from backend.core.data_loader import (
    load_factories_and_tariffs,
    load_factories_from_google,
)
from backend.core.logger import get_logger

# === ЛОГГЕР ===
log = get_logger("main")

# === ЗАГРУЗКА ENV ===
load_dotenv()

app = FastAPI(title="Delivery Calculator")

# === CORS ===
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === GOOGLE ENV ===
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_CREDS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")


@app.on_event("startup")
async def startup_event():
    log.info("🚀 Backend has started")
    log.info(f"ENV GOOGLE_SHEET_ID: {GOOGLE_SHEET_ID}")
    log.info(f"ENV GOOGLE_APPLICATION_CREDENTIALS: {GOOGLE_CREDS}")

    # Инициализация БД
    from backend.core.database import init_db, SessionLocal
    from backend.models import db_models  # Импортируем модели для создания таблиц
    init_db()
    log.info("✅ Database initialized")

    # Создание администратора по умолчанию
    from backend.core.db_migration import (
        create_default_admin,
        ensure_catalog_normalization,
        ensure_tariffs_schema,
        migrate_tariffs,
    )
    db = SessionLocal()
    try:
        ensure_catalog_normalization(db)
        ensure_tariffs_schema(db)
        create_default_admin(db)
    finally:
        db.close()

    # Пересоздание товаров/заводов из Google Sheets в БД
    db = SessionLocal()
    try:
        ensure_catalog_normalization(db)
        ensure_tariffs_schema(db)

        # ВАЖНО: тарифы (машины) больше НЕ читаем из Google Sheets.
        # Обновляем только factories/products.
        load_factories_from_google(db)

        # Если тарифов ещё нет в БД — подтянем стартовый набор из backend/storage/tariffs.json (если есть).
        # Это не Google Sheets и нужно только для первого запуска.
        from backend.models.db_models import Tariff
        if (db.query(Tariff).count() or 0) == 0:
            try:
                migrate_tariffs(db)
            except Exception as e:
                log.warning("⚠️ Не удалось импортировать tariffs из JSON: %s", e)

        # Проверим, что данные загружены
        factories, tariffs = load_factories_and_tariffs(db)
        log.info(f"✅ Данные загружены: {len(factories)} категорий товаров, {len(tariffs)} тарифов")
    except Exception as e:
        log.error(f"❌ Ошибка при загрузке данных: {e}")
    finally:
        db.close()


# === РОУТЫ ===
from backend.app.routes_admin import router as admin_router
from backend.app.routes_fibonacci import router as fibonacci_router
from backend.app.routes_quote import router as quote_router
from backend.app.routes_auth import router as auth_router
app.include_router(quote_router, prefix="/api")
app.include_router(fibonacci_router, prefix="/api")
app.include_router(admin_router)
app.include_router(auth_router)