import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from backend.core.data_loader import (
    rebuild_factories_and_tariffs_from_google,
    load_factories_and_tariffs
)
from backend.core.logger import get_logger
from backend.app.routes_quote import router as quote_router

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

    # Пересоздание данных из Google Sheets
    rebuild_factories_and_tariffs_from_google(GOOGLE_SHEET_ID)

    # Проверим, что файлы теперь точно есть
    factories, tariffs = load_factories_and_tariffs()
    log.info(f"✅ factories_products.json загружен ({len(factories)} записей)")
    log.info(f"✅ tariffs.json загружен ({len(tariffs)} тарифов)")

# === РОУТЫ ===
app.include_router(quote_router, prefix="/api")
