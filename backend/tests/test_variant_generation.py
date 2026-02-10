from types import SimpleNamespace

from backend.service import transport_calc


def _make_tariffs() -> list[dict]:
    return [
        {
            "id": 1,
            "name": "Long Haul",
            "tag": "long_haul",
            "service_type": "delivery",
            "weight_condition": "any",
            "weight_threshold": None,
            "min_distance": 0,
            "max_distance": 100,
            "base": 1000,
            "per_km": 0,
            "грузоподъёмность": 20,
            "is_active": True,
        },
        {
            "id": 2,
            "name": "Flatbed",
            "tag": "flatbed",
            "service_type": "delivery",
            "weight_condition": "any",
            "weight_threshold": None,
            "min_distance": 0,
            "max_distance": 100,
            "base": 1200,
            "per_km": 0,
            "грузоподъёмность": 20,
            "is_active": True,
        },
    ]


def _make_request() -> SimpleNamespace:
    return SimpleNamespace(
        upload_lat=55.0,
        upload_lon=37.0,
        transport_type="auto",
        add_manipulator=False,
        delivery_transport_tag="auto",
        unloading_transport_tag="none",
        allowed_delivery_tags=["long_haul", "flatbed"],
        allowed_unloading_tags=[],
        forbidden_delivery_tags=[],
        forbidden_unloading_tags=[],
        forbidden_types=[],
    )


def test_single_plan_multiple_vehicle_variants(monkeypatch) -> None:
    monkeypatch.setattr(transport_calc, "get_osrm_distance_km", lambda *args, **kwargs: 10.0)
    scenario = {
        "scenario_id": 1,
        "factories": {
            "Factory A": [
                {
                    "factory": {"name": "Factory A", "lat": 55.0, "lon": 37.0},
                    "category": "A",
                    "subtype": "X",
                    "weight_total": 5,
                    "weight_per_item": 5,
                    "quantity": 1,
                    "price_per_item": 100,
                }
            ]
        },
    }
    variants = transport_calc.evaluate_scenario_transport_variants(
        scenario,
        _make_request(),
        _make_tariffs(),
        max_vehicle_combos_per_plan=10,
        max_variants=10,
    )

    assert len(variants) == 2
    transport_names = {v["transport_name"] for v in variants}
    assert "Long Haul" in transport_names
    assert "Flatbed" in transport_names


def test_multiple_plans_multiply_vehicle_variants(monkeypatch) -> None:
    monkeypatch.setattr(transport_calc, "get_osrm_distance_km", lambda *args, **kwargs: 10.0)
    scenario = {
        "scenario_id": 2,
        "factories": {
            "Factory A": [
                {
                    "factory": {"name": "Factory A", "lat": 55.0, "lon": 37.0},
                    "category": "A",
                    "subtype": "X",
                    "weight_total": 5,
                    "weight_per_item": 5,
                    "quantity": 1,
                    "price_per_item": 100,
                }
            ],
            "Factory B": [
                {
                    "factory": {"name": "Factory B", "lat": 56.0, "lon": 38.0},
                    "category": "B",
                    "subtype": "Y",
                    "weight_total": 5,
                    "weight_per_item": 5,
                    "quantity": 1,
                    "price_per_item": 100,
                }
            ],
        },
    }
    variants = transport_calc.evaluate_scenario_transport_variants(
        scenario,
        _make_request(),
        _make_tariffs(),
        max_vehicle_combos_per_plan=10,
        max_variants=10,
    )

    assert len(variants) == 4


def _make_manipulator_tariffs(*, unloading_included: bool) -> list[dict]:
    return [
        {
            "id": 10,
            "name": "Манипулятор Фикс",
            "tag": "manipulator",
            "service_type": "delivery",
            "weight_condition": "any",
            "weight_threshold": None,
            "min_distance": 0,
            "max_distance": 100,
            "base": 40000,
            "per_km": 0,
            "грузоподъёмность": 20,
            "unloading_included": unloading_included,
            "is_active": True,
        },
        {
            "id": 11,
            "name": "Манипулятор Фикс",
            "tag": "manipulator",
            "service_type": "unloading",
            "weight_condition": "any",
            "weight_threshold": None,
            "min_distance": 0,
            "max_distance": 0,
            "base": 24000,
            "per_km": 0,
            "грузоподъёмность": 20,
            "is_active": True,
        },
    ]


def _make_manipulator_request() -> SimpleNamespace:
    return SimpleNamespace(
        upload_lat=55.0,
        upload_lon=37.0,
        transport_type="auto",
        add_manipulator=False,
        delivery_transport_tag="auto",
        unloading_transport_tag="auto",
        allowed_delivery_tags=["manipulator"],
        allowed_unloading_tags=["manipulator"],
        forbidden_delivery_tags=[],
        forbidden_unloading_tags=[],
        forbidden_types=[],
    )


def _make_single_factory_scenario() -> dict:
    return {
        "scenario_id": 3,
        "factories": {
            "Factory A": [
                {
                    "factory": {"name": "Factory A", "lat": 55.0, "lon": 37.0},
                    "category": "A",
                    "subtype": "X",
                    "weight_total": 5,
                    "weight_per_item": 5,
                    "quantity": 1,
                    "price_per_item": 100,
                }
            ]
        },
    }


def test_manipulator_unloading_is_separate_by_default(monkeypatch) -> None:
    monkeypatch.setattr(transport_calc, "get_osrm_distance_km", lambda *args, **kwargs: 10.0)
    variants = transport_calc.evaluate_scenario_transport_variants(
        _make_single_factory_scenario(),
        _make_manipulator_request(),
        _make_manipulator_tariffs(unloading_included=False),
        max_vehicle_combos_per_plan=10,
        max_variants=10,
    )

    assert variants
    best = variants[0]
    assert best["delivery_cost"] == 40000
    assert best["unloading_cost"] == 24000
    assert best["total_cost"] == best["material_sum"] + 64000


def test_manipulator_unloading_can_be_included_in_delivery(monkeypatch) -> None:
    monkeypatch.setattr(transport_calc, "get_osrm_distance_km", lambda *args, **kwargs: 10.0)
    variants = transport_calc.evaluate_scenario_transport_variants(
        _make_single_factory_scenario(),
        _make_manipulator_request(),
        _make_manipulator_tariffs(unloading_included=True),
        max_vehicle_combos_per_plan=10,
        max_variants=10,
    )

    assert variants
    best = variants[0]
    assert best["delivery_cost"] == 40000
    assert best["unloading_cost"] == 0
    assert best["unloading"] is None
    assert best["total_cost"] == best["material_sum"] + 40000