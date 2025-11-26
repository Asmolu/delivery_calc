import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from backend.service.factories_service import init_factories_cache
from backend.app.routes_quote import router as quote_router
from backend.core.logger import get_logger

log = get_logger("main")

# === Настройка приложения ===
app = FastAPI(title="Delivery Backend")

# === CORS ===
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === ENV ===
load_dotenv()
log.info("🚀 Backend has started")
log.info(f"ENV GOOGLE_SHEET_ID: {os.getenv('GOOGLE_SHEET_ID')}")
log.info(f"ENV GOOGLE_APPLICATION_CREDENTIALS: {os.getenv('GOOGLE_APPLICATION_CREDENTIALS')}")

# === Инициализация данных ===
@app.on_event("startup")
async def startup_event():
    try:
        init_factories_cache(force_reload=False)
        log.info("✅ factories_products.json загружен и кэширован.")
    except Exception as e:
        log.error(f"❌ Ошибка при инициализации данных: {e}")

# === Роуты ===
app.include_router(quote_router, prefix="/quote", tags=["Quote"])
