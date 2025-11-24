from fastapi import FastAPI
from dotenv import load_dotenv
from pathlib import Path
import os

# ===== LOAD .env ======
BASE_DIR = Path(__file__).resolve().parents[2]
env_path = BASE_DIR / ".env"
if env_path.exists():
    load_dotenv(env_path)

print("Loaded ENV from:", env_path)
print("ENV GOOGLE_SHEET_ID:", os.getenv("GOOGLE_SHEET_ID"))
print("ENV GOOGLE_APPLICATION_CREDENTIALS:", os.getenv("GOOGLE_APPLICATION_CREDENTIALS"))

# ===== CORRECT ABSOLUTE IMPORTS =====
from backend.core.logger import get_logger
from backend.app.routes_quote import router as quote_router
from backend.app.routes_info import router as info_router
from backend.app.routes_admin import router as admin_router


from fastapi.middleware.cors import CORSMiddleware

import os

from backend.core.data_loader import fetch_all_product_specs

GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")


app = FastAPI()

app.include_router(quote_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


log = get_logger("app.main")


@app.on_event("startup")
async def startup():
    log.info("🚀 Backend has started")

@app.on_event("startup")
async def startup():
    log.info("🚀 Backend has started")

    GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
    if GOOGLE_SHEET_ID:
        fetch_all_product_specs(
            sheet_id=GOOGLE_SHEET_ID,
            sheet_names=[
                "Дорожные ПЛИТЫ/ПАГИ",
                "ФБС БЛОКИ",
            ]
        )

# ------------------------
# 4) РОУТЫ
# ------------------------
app.include_router(quote_router)
app.include_router(info_router)
app.include_router(admin_router)
