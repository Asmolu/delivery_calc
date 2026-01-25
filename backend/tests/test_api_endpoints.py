import importlib.util

import pytest
from fastapi import FastAPI

from backend.app import routes_fibonacci, routes_quote
from backend.core import auth, database

HTTPX_AVAILABLE = importlib.util.find_spec("httpx") is not None


@pytest.fixture()
def client(monkeypatch):
    if not HTTPX_AVAILABLE:
        pytest.skip("httpx is required for API-level tests")

    from fastapi.testclient import TestClient

    factories_products = {
        "Concrete": [
            {
                "factory": {
                    "id": 1,
                    "name": "Factory A",
                    "lat": 55.75,
                    "lon": 37.61,
                    "contact": "+7-000-000-00-00",
                    "price": 1200,
                },
                "subtype": "Subtype A",
                "weight_per_item": 10,
                "special_threshold": 5,
                "max_per_trip": 3,
            }
        ]
    }
    tariffs = [{"name": "Tariff A", "price": 100}]

    def fake_load_factories_and_tariffs(_db):
        return factories_products, tariffs

    def fake_build_factory_scenarios_v2(_factories, _items):
        return [{"scenario_id": 1}]

    def fake_evaluate_scenario_transport(_scenario, _req, _tariffs):
        return {
            "scenario": {
                "scenario_id": 1,
                "total_weight": 10,
                "factories": {
                    "factory-a": [
                        {
                            "factory": {"id": 1, "name": "Factory A"},
                        }
                    ]
                },
            },
            "total_cost": 150,
            "material_sum": 100,
            "delivery_cost": 50,
            "unloading_cost": 0,
            "factory_plans": [],
            "trip_count": 1,
            "transport_name": "Truck A",
        }

    def fake_get_db():
        yield object()

    monkeypatch.setattr(
        routes_quote,
        "load_factories_and_tariffs",
        fake_load_factories_and_tariffs,
    )
    monkeypatch.setattr(
        routes_quote,
        "build_factory_scenarios_v2",
        fake_build_factory_scenarios_v2,
    )
    monkeypatch.setattr(
        routes_quote,
        "evaluate_scenario_transport",
        fake_evaluate_scenario_transport,
    )

    app = FastAPI()
    app.include_router(routes_quote.router, prefix="/api")
    app.include_router(routes_fibonacci.router, prefix="/api")
    app.dependency_overrides[database.get_db] = fake_get_db
    app.dependency_overrides[auth.get_current_user_optional] = lambda: None

    return TestClient(app)


def test_factories_endpoint_returns_flat_list(client) -> None:
    response = client.get("/api/factories")

    assert response.status_code == 200
    data = response.json()
    assert data == [
        {
            "name": "Factory A",
            "lat": 55.75,
            "lon": 37.61,
            "contact": "+7-000-000-00-00",
            "category": "Concrete",
            "subtype": "Subtype A",
            "weight_per_item": 10,
            "special_threshold": 5,
            "max_per_trip": 3,
            "price": 1200,
        }
    ]


def test_tariffs_endpoint_returns_payload(client) -> None:
    response = client.get("/api/tariffs")

    assert response.status_code == 200
    assert response.json() == [{"name": "Tariff A", "price": 100}]


def test_categories_endpoint_returns_unique_subtypes(client) -> None:
    response = client.get("/api/categories")

    assert response.status_code == 200
    assert response.json() == {"Concrete": ["Subtype A"]}


def test_quote_endpoint_returns_variants(client) -> None:
    payload = {
        "upload_lat": 55.75,
        "upload_lon": 37.61,
        "transport_type": "auto",
        "items": [
            {"category": "Concrete", "subtype": "Subtype A", "quantity": 2},
        ],
    }

    response = client.post("/api/quote", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["variants"]