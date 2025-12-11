"""Вычисление чисел Фибоначчи для вспомогательных эндпоинтов."""
from __future__ import annotations

from typing import List


def fibonacci_sequence(count: int) -> List[int]:
    """Возвращает последовательность Фибоначчи длиной ``count``.

    Используется итеративный подход, чтобы избежать переполнения стека и
    обеспечить предсказуемое время выполнения даже для больших ``count``.
    Значение ``count`` должно быть положительным.
    """

    if count <= 0:
        raise ValueError("Количество чисел должно быть положительным")

    sequence = [0]
    if count == 1:
        return sequence

    sequence.append(1)
    for _ in range(2, count):
        sequence.append(sequence[-1] + sequence[-2])

    return sequence