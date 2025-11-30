import os
import json
from backend.core.logger import get_logger
from backend.service.factories_parser import parse_google_sheet

__all__ = [
    "load_factories_from_google",
    "load_tariffs_from_google",
    "rebuild_factories_and_tariffs_from_google",
    "load_factories_and_tariffs",
]

log = get_logger("data_loader")

# Папка и имена файлов в storage
STORAGE_PATH = os.path.join("backend", "storage")
FACTORIES_FILE = os.path.join(STORAGE_PATH, "factories_products.json")
TARIFFS_FILE = os.path.join(STORAGE_PATH, "tariffs.json")

def _ensure_storage_dir() -> None:
    os.makedirs(STORAGE_PATH, exist_ok=True)


def _save_factories(factories_products: dict) -> None:
    _ensure_storage_dir()
    with open(FACTORIES_FILE, "w", encoding="utf-8") as f:
        json.dump(factories_products, f, ensure_ascii=False, indent=2)


def _save_tariffs(tariffs: list) -> None:
    _ensure_storage_dir()
    with open(TARIFFS_FILE, "w", encoding="utf-8") as f:
        json.dump(tariffs, f, ensure_ascii=False, indent=2)


def load_factories_from_google():
    """Загружает товары+заводы из Google Sheets и сохраняет их в storage."""
    result = parse_google_sheet()
    factories_products = result.get("products", {})

    _save_factories(factories_products)
    log.info(
        "✅ Обновлены factories_products.json из Google Sheets (%s записей)",
        len(factories_products),
    )

    return factories_products


def load_tariffs_from_google():
    """Загружает тарифы из Google Sheets и сохраняет их в storage."""
    result = parse_google_sheet()
    tariffs = result.get("tariffs", [])

    _save_tariffs(tariffs)
    log.info("✅ Обновлены tariffs.json из Google Sheets (%s тарифов)", len(tariffs))

    return tariffs



def rebuild_factories_and_tariffs_from_google(google_sheet_id: str) -> None:
    """
    Пересоздаёт factories_products.json и tariffs.json из Google Sheets.
    google_sheet_id сюда пробрасываем только для логов — фактически
    вся логика подключения и чтения сидит внутри factories_parser.parse_google_sheet().
    """
    try:
        log.info(
            "📦 Пересоздаём factories_products.json и tariffs.json из Google Sheets "
            f"(GOOGLE_SHEET_ID={google_sheet_id})"
        )

        # Парсим таблицу. Функция САМА сохраняет factories_products.json и tariffs.json,
        # и возвращает структуру {"products": parsed_products, "tariffs": parsed_tariffs}
        result = parse_google_sheet()
        factories_products = result.get("products", {})
        tariffs = result.get("tariffs", [])

        # На всякий случай создаём папку storage (если вдруг её нет)
        os.makedirs(STORAGE_PATH, exist_ok=True)

        # Дополнительно дублируем сохранение, чтобы быть уверенными,
        # что файлы лежат именно там, где ждут остальные части бэка.
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


def load_factories_and_tariffs():
    """
    Загружает factories_products.json и tariffs.json (если существуют).
    Возвращает кортеж: (factories_products, tariffs)
    """
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
