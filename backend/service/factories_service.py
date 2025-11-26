from __future__ import annotations
from typing import List, Dict, Any, Optional, Tuple
from backend.core.data_loader import load_factories_products
from backend.core.logger import get_logger
import math
log = get_logger("factories_service")

# Кэш данных
_FACTORIES_DATA: List[Dict[str, Any]] = []

# ==== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =============================================

def _norm_str(s):
    """Нормализует строки для поиска и сопоставления (убирает пробелы, регистр и неразрывные пробелы)."""
    if s is None:
        return ""
    return str(s).replace("\xa0", " ").strip().lower()


def _to_float(x):
    """Преобразует значения к float с защитой от мусора."""
    if x is None or x == "":
        return 0.0
    try:
        return float(str(x).replace(" ", "").replace(",", "."))
    except Exception:
        return 0.0


def init_factories_cache(force_reload: bool = False):
    """
    Инициализация данных о товарах и заводах.
    """
    global _FACTORIES_DATA
    _FACTORIES_DATA = load_factories_products(force_reload)
    log.info(f"📦 Инициализировано {len(_FACTORIES_DATA)} товаров (объединённые данные).")


def get_all_factories() -> List[Dict[str, Any]]:
    """
    Возвращает список всех заводов (уникальные).
    """
    seen = {}
    for item in _FACTORIES_DATA:
        for fac in item.get("factories", []):
            name = fac.get("name")
            if name and name not in seen:
                seen[name] = fac
    return list(seen.values())


def get_all_products() -> List[Dict[str, Any]]:
    """
    Возвращает все товары (с вложенными заводами).
    """
    return _FACTORIES_DATA


def find_product(category: str, subtype: str) -> Optional[Dict[str, Any]]:
    """
    Ищет конкретный товар по категории и подтипу.
    """
    for p in _FACTORIES_DATA:
        if (
            p.get("category", "").strip().lower() == category.strip().lower()
            and p.get("subtype", "").strip().lower() == subtype.strip().lower()
        ):
            return p
    return None

# ==== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ ПЛАНИРОВАНИЯ =============================

def _detect_standard_for_factory_items(items):
    """
    Определяет, применима ли стандартная схема для завода.
    Пока возвращает None — логика отключена (всё идёт через compute_best_plan).
    """
    return None


def _plan_special_single_heavy_long_haul(factory_info, std_info, req, usable_tariffs):
    """
    Заглушка для планирования одиночного тяжёлого рейса.
    Пока возвращает (None, None), чтобы передавать управление compute_best_plan.
    """
    return None, None
