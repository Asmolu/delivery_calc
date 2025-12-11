import importlib.util

import pytest
from fastapi import FastAPI

from backend.app.routes_fibonacci import router
from backend.service.fibonacci_service import fibonacci_sequence

HTTPX_AVAILABLE = importlib.util.find_spec("httpx") is not None


@pytest.fixture()
def client():
    if not HTTPX_AVAILABLE:
        pytest.skip("httpx is required for API-level tests")

    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


def test_fibonacci_sequence_endpoint_returns_expected_numbers(client) -> None:
    response = client.get("/api/fibonacci", params={"count": 7})

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 7
    assert body["sequence"] == [0, 1, 1, 2, 3, 5, 8]
    assert body["last"] == 8


def test_fibonacci_sequence_endpoint_validates_count_range(client) -> None:
    response = client.get("/api/fibonacci", params={"count": 0})

    assert response.status_code == 422
    assert "count" in response.text


def test_fibonacci_service_handles_larger_sequences() -> None:
    sequence = fibonacci_sequence(20)

    assert len(sequence) == 20
    assert sequence[:5] == [0, 1, 1, 2, 3]
    assert sequence[-1] == 4181