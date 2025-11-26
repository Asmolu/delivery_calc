import os
import json
from backend.service.factories_parser import parse_google_sheet
from backend.core.logger import get_logger

log = get_logger("data_loader")

# Путь к каталогу хранения
STORAGE_DIR = os.path.join(os.path.dirname(__file__), "..", "storage")
STORAGE_PATH = os.path.join(STORAGE_DIR, "factories_products.json")

# Разрешённые листы
ALLOWED_SHEETS = {"Дорожные ПЛИТЫ/ПАГИ", "ФБС БЛОКИ", "Vehicles"}


def load_factories_products(force_reload: bool = False):
    """
    Загружает или парсит объединённые данные (товары + заводы + тарифы).
    """
    try:
        # Проверяем, нужен ли пересозданный файл
        if force_reload or not os.path.exists(STORAGE_PATH):
            log.info("📦 Пересоздаём factories_products.json из Google Sheets")

            all_data = parse_google_sheet()

            # Пропускаем строки-заголовки в листе Vehicles
            if "vehicles" in all_data:
                vehicles = all_data["vehicles"]
                if vehicles and isinstance(vehicles[0], list):
                    # если первая строка содержит текст, а не числа
                    if any(isinstance(x, str) and not x.replace('.', '', 1).isdigit() for x in vehicles[0]):
                        vehicles = vehicles[1:]
                all_data["vehicles"] = vehicles

            # сохраняем объединённые данные
            os.makedirs(STORAGE_DIR, exist_ok=True)
            with open(STORAGE_PATH, "w", encoding="utf-8") as f:
                json.dump(all_data, f, ensure_ascii=False, indent=2)

            log.info(f"✅ factories_products.json сохранён — {len(all_data)} записей.")
        else:
            log.info("📁 Используем существующий factories_products.json")

        # Загружаем готовые данные
        with open(STORAGE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        log.info(f"✅ Загружено factories_products.json — {len(data)} позиций.")

        # --- Дополнительно сохраняем тарифы отдельно ---
        vehicles = data.get("vehicles")
        if vehicles:
            tariffs_path = os.path.join(STORAGE_DIR, "tariffs.json")
            with open(tariffs_path, "w", encoding="utf-8") as tf:
                json.dump(vehicles, tf, ensure_ascii=False, indent=2)
            log.info(f"🚛 Отдельный tariffs.json сохранён — {len(vehicles)} тарифов.")

        return data

    except Exception as e:
        log.error(f"❌ Ошибка при инициализации данных: {e}")
        return []
