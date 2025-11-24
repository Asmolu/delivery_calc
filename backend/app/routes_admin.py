import json

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..core.logger import get_logger
from ..core.data_loader import (
    load_factories_from_google,
    load_tariffs_from_google,
)

router = APIRouter()
log = get_logger("routes.admin")


@router.post("/admin/reload")
async def admin_reload():
    """
    🔄 Перезагрузка и factories, и tariffs.
    """
    try:
        log.info("Запуск полного обновления данных из Google Sheets...")
        factories = load_factories_from_google()
        tariffs_result = load_tariffs_from_google()

        return JSONResponse(
            content={
                "factories_count": len(factories),
                "tariffs": tariffs_result,
            }
        )
    except Exception as e:
        import traceback

        traceback.print_exc()
        log.error("Ошибка при обновлении данных: %s", e)
        return JSONResponse(
            status_code=500,
            content={"detail": f"Ошибка при обновлении данных: {e}"},
        )


@router.post("/admin/reload/factories")
async def admin_reload_factories():
    try:
        log.info("Обновление factories из Google Sheets...")
        factories = load_factories_from_google()
        return JSONResponse(
            content={"status": "ok", "factories_count": len(factories)}
        )
    except Exception as e:
        import traceback

        traceback.print_exc()
        log.error("Ошибка при обновлении factories: %s", e)
        return JSONResponse(
            status_code=500,
            content={"detail": f"Ошибка при обновлении factories: {e}"},
        )


@router.post("/admin/reload/tariffs")
async def admin_reload_tariffs():
    try:
        log.info("Обновление tariffs из Google Sheets...")
        result = load_tariffs_from_google()
        return JSONResponse(content=result)
    except Exception as e:
        import traceback

        traceback.print_exc()
        log.error("Ошибка при обновлении tariffs: %s", e)
        return JSONResponse(
            status_code=500,
            content={"detail": f"Ошибка при обновлении тарифов: {e}"},
        )
