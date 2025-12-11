from fastapi import APIRouter, Query

from backend.service.fibonacci_service import fibonacci_sequence

router = APIRouter(prefix="/fibonacci", tags=["fibonacci"])


@router.get("")
def get_fibonacci_sequence(count: int = Query(..., ge=1, le=1000, description="Количество чисел Фибоначчи")):
    """Возвращает последовательность чисел Фибоначчи длиной ``count``."""
    sequence = fibonacci_sequence(count)
    return {
        "count": count,
        "sequence": sequence,
        "last": sequence[-1],
    }