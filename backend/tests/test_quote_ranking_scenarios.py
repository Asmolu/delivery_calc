import importlib.util

import pytest
from fastapi import FastAPI

from backend.app import routes_quote
from backend.core import auth, database

HTTPX_AVAILABLE = importlib.util.find_spec("httpx") is not None


class _DummyDB:
    def __init__(self):
        self._id = 1000

    def add(self, _obj):
        return None

    def commit(self):
        return None

    def refresh(self, obj):
        self._id += 1
        setattr(obj, "id", self._id)


def _variant(
    *,
    total_cost: float,
    transport_name: str,
    factory_id: int | None,
    factory_name: str,
    delivery_tag: str,
    unloading_tag: str = "none",
    trip_count: int = 1,
) -> dict:
    unloading = None if unloading_tag == "none" else {"tag": unloading_tag, "cost": 5000}
    return {
        "scenario": {
            "scenario_id": hash((transport_name, total_cost, factory_name, factory_id)),
            "total_weight": 10,
            "factories": {
                factory_name: [
                    {
                        "factory": {
                            "id": factory_id,
                            "name": factory_name,
                            "lat": 55.75,
                            "lon": 37.61,
                        }
                    }
                ]
            },
        },
        "total_cost": total_cost,
        "material_sum": 100,
        "delivery_cost": total_cost - 100,
        "unloading_cost": 0 if unloading is None else 5000,
        "unloading": unloading,
        "factory_plans": [
            {
                "factory_name": factory_name,
                "trips": [{"tag": delivery_tag, "tariff_name": delivery_tag}],
            }
        ],
        "trip_count": trip_count,
        "transport_name": transport_name,
    }


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
            }
        ]
    }
    tariffs = [{"name": "Tariff A", "price": 100}]

    def fake_load_factories_and_tariffs(_db):
        return factories_products, tariffs

    def fake_build_factory_scenarios_v2(_factories, _items):
        return [{"scenario_id": 1, "factories": {}}]

    def fake_get_db():
        yield _DummyDB()

    monkeypatch.setattr(routes_quote, "load_factories_and_tariffs", fake_load_factories_and_tariffs)
    monkeypatch.setattr(routes_quote, "build_factory_scenarios_v2", fake_build_factory_scenarios_v2)

    app = FastAPI()
    app.include_router(routes_quote.router, prefix="/api")
    app.dependency_overrides[database.get_db] = fake_get_db
    app.dependency_overrides[auth.get_current_user_optional] = lambda: None
    return TestClient(app)


def _post_quote(client, monkeypatch, variants: list[dict]) -> dict:
    def fake_eval(_scenario, _req, _tariffs):
        return variants

    monkeypatch.setattr(routes_quote, "evaluate_scenario_transport_variants", fake_eval)

    payload = {
        "upload_lat": 55.75,
        "upload_lon": 37.61,
        "transport_type": "auto",
        "items": [{"category": "Concrete", "subtype": "Subtype A", "quantity": 2}],
    }
    response = client.post("/api/quote", json=payload)
    assert response.status_code == 200
    return response.json()


def test_top3_positions_are_standard_even_if_alternatives_are_cheaper(client, monkeypatch) -> None:
    body = _post_quote(
        client,
        monkeypatch,
        variants=[
            _variant(total_cost=90, transport_name="Container Cheap", factory_id=10, factory_name="F1", delivery_tag="container_carrier"),
            _variant(total_cost=95, transport_name="Crane Cheap", factory_id=11, factory_name="F2", delivery_tag="long_haul", unloading_tag="crane"),
            _variant(total_cost=120, transport_name="Long Haul", factory_id=1, factory_name="A", delivery_tag="long_haul"),
            _variant(total_cost=130, transport_name="Manipulator", factory_id=2, factory_name="B", delivery_tag="manipulator"),
            _variant(total_cost=140, transport_name="Flatbed", factory_id=3, factory_name="C", delivery_tag="flatbed"),
        ],
    )

    names = [v["transportName"] for v in body["variants"]]
    markers = [v.get("scenarioMarker") for v in body["variants"]]
    assert names[:3] == ["Long Haul", "Manipulator", "Flatbed"]
    assert names[3:] == ["Container Cheap", "Crane Cheap"]
    assert markers[:3] == ["S", "S", "S"]
    assert markers[3:] == ["A", "A"]


def test_signature_uses_factory_id_when_available(client, monkeypatch) -> None:
    body = _post_quote(
        client,
        monkeypatch,
        variants=[
            _variant(total_cost=120, transport_name="Std A", factory_id=77, factory_name="Factory Alpha", delivery_tag="long_haul"),
            _variant(total_cost=121, transport_name="Std B", factory_id=77, factory_name="Factory Beta", delivery_tag="long_haul"),
            _variant(total_cost=150, transport_name="Std C", factory_id=88, factory_name="Factory C", delivery_tag="flatbed"),
        ],
    )

    names = [v["transportName"] for v in body["variants"]]
    assert "Std A" in names
    assert "Std B" not in names


def test_signature_falls_back_to_factory_name_without_id(client, monkeypatch) -> None:
    body = _post_quote(
        client,
        monkeypatch,
        variants=[
            _variant(total_cost=120, transport_name="Std A", factory_id=None, factory_name="Same Name", delivery_tag="long_haul"),
            _variant(total_cost=121, transport_name="Std B", factory_id=None, factory_name="Same Name", delivery_tag="long_haul"),
            _variant(total_cost=122, transport_name="Std C", factory_id=None, factory_name="Other Name", delivery_tag="long_haul"),
        ],
    )

    names = [v["transportName"] for v in body["variants"]]
    assert "Std A" in names
    assert "Std B" not in names


def test_manipulator_is_standard_not_alternative(client, monkeypatch) -> None:
    body = _post_quote(
        client,
        monkeypatch,
        variants=[
            _variant(total_cost=90, transport_name="Container", factory_id=10, factory_name="F1", delivery_tag="container_carrier"),
            _variant(total_cost=100, transport_name="Manipulator", factory_id=20, factory_name="F2", delivery_tag="manipulator"),
            _variant(total_cost=110, transport_name="Long Haul", factory_id=30, factory_name="F3", delivery_tag="long_haul"),
            _variant(total_cost=120, transport_name="Flatbed", factory_id=40, factory_name="F4", delivery_tag="flatbed"),
        ],
    )

    names = [v["transportName"] for v in body["variants"]]
    assert names[:3] == ["Manipulator", "Long Haul", "Flatbed"]
    assert [v.get("scenarioMarker") for v in body["variants"][:3]] == ["S", "S", "S"]