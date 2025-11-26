import os
import json
from backend.service.factories_parser import parse_google_sheet
from backend.core.logger import get_logger

log = get_logger("data_loader")

STORAGE_PATH = "backend/storage/factories_products.json"


def load_factories_products(force_reload: bool = False):
    """
    Загружает или парсит объединённые данные (товары + заводы).
    """
    if force_reload or not os.path.exists(STORAGE_PATH):
        log.info("📦 Пересоздаём factories_products.json из Google Sheets")
        parse_google_sheet()

    try:
        with open(STORAGE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        log.info(f"✅ Загружено factories_products.json — {len(data)} позиций.")
        return data
    except Exception as e:
        log.error(f"❌ Ошибка при загрузке {STORAGE_PATH}: {e}")
        return []
