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


def test_included_manipulator_unloads_only_itself_other_trips_are_paid(monkeypatch) -> None:
    def fake_generate_plans(*args, **kwargs):
        return (
            [
                {"plan_id": "Factory A", "distance_km": 20.0, "material_cost": 1000.0},
                {"plan_id": "Factory B", "distance_km": 30.0, "material_cost": 2000.0},
            ],
            {
                "total_material": 3000.0,
                "factory_distances": {"Factory A": 20.0, "Factory B": 30.0},
                "pickup_points_all": [],
                "plans_generated": 2,
            },
        )

    def fake_generate_delivery_candidates(req, *, plan, **kwargs):
        if plan.get("plan_id") == "Factory A":
            # Длинномер без включённой разгрузки.
            return (
                [
                    {
                        "transport_cost": 26000.0,
                        "trips": [
                            {
                                "tag": "long_haul",
                                "tariff_name": "Длинномер 44",
                                "load_ton": 14.2,
                                "unloading_included": False,
                            }
                        ],
                    }
                ],
                {},
            )
        # Манипулятор с включённой разгрузкой (бесплатно только для своего рейса).
        return (
            [
                {
                    "transport_cost": 22000.0,
                    "trips": [
                        {
                            "tag": "manipulator",
                            "tariff_name": "Манипулятор 5т",
                            "capacity_ton": 5.0,
                            "load_ton": 2.27,
                            "unloading_included": True,
                        }
                    ],
                }
            ],
            {},
        )

    def fake_generate_unload_candidates(*args, **kwargs):
        return (
            [
                {
                    "unloading": {
                        "service_type": "unloading",
                        "tag": "manipulator",
                        "tariff_name": "Манипулятор 5т",
                        "tariff_label": "Манипулятор 5т",
                        "cost": 22000.0,
                    },
                    "cost": 22000.0,
                }
            ],
            {},
        )

    monkeypatch.setattr(transport_calc, "generate_plans", fake_generate_plans)
    monkeypatch.setattr(transport_calc, "generate_delivery_candidates", fake_generate_delivery_candidates)
    monkeypatch.setattr(transport_calc, "generate_unload_candidates", fake_generate_unload_candidates)

    req = SimpleNamespace(
        upload_lat=55.0,
        upload_lon=37.0,
        transport_type="auto",
        add_manipulator=False,
        delivery_transport_tag="auto",
        unloading_transport_tag="auto",
        allowed_delivery_tags=[],
        allowed_unloading_tags=[],
        forbidden_delivery_tags=[],
        forbidden_unloading_tags=[],
        forbidden_types=[],
    )
    scenario = {
        "scenario_id": 42,
        "factories": {
            "Factory A": [{"weight_total": 14.2, "weight_per_item": 14.2, "quantity": 1}],
            "Factory B": [{"weight_total": 2.27, "weight_per_item": 2.27, "quantity": 1}],
        },
    }
    tariffs = [
        {
            "id": 501,
            "name": "Манипулятор 5т",
            "tag": "manipulator",
            "service_type": "unloading",
            "weight_condition": "any",
            "weight_threshold": None,
            "min_distance": 0,
            "max_distance": 0,
            "base": 22000.0,
            "per_km": 0.0,
            "is_active": True,
        }
    ]

    variants = transport_calc.evaluate_scenario_transport_variants(
        scenario,
        req,
        tariffs,
        max_vehicle_combos_per_plan=10,
        max_variants=10,
    )

    assert variants
    best = variants[0]
    assert best["delivery_cost"] == 48000.0
    assert best["unloading_cost"] == 22000.0
    assert best["total_cost"] == best["material_sum"] + 70000.0
    

def test_included_manipulator_charges_once_for_all_other_trucks(monkeypatch) -> None:
    def fake_generate_plans(*args, **kwargs):
        return (
            [
                {"plan_id": "Factory A", "distance_km": 20.0, "material_cost": 1000.0},
                {"plan_id": "Factory B", "distance_km": 30.0, "material_cost": 2000.0},
            ],
            {
                "total_material": 3000.0,
                "factory_distances": {"Factory A": 20.0, "Factory B": 30.0},
                "pickup_points_all": [],
                "plans_generated": 2,
            },
        )

    def fake_generate_delivery_candidates(req, *, plan, **kwargs):
        if plan.get("plan_id") == "Factory A":
            # Два длинномера без включённой разгрузки.
            return (
                [
                    {
                        "transport_cost": 52000.0,
                        "trips": [
                            {
                                "tag": "long_haul",
                                "tariff_name": "Длинномер 44",
                                "load_ton": 10.0,
                                "unloading_included": False,
                            },
                            {
                                "tag": "long_haul",
                                "tariff_name": "Длинномер 44",
                                "load_ton": 8.0,
                                "unloading_included": False,
                            },
                        ],
                    }
                ],
                {},
            )
        return (
            [
                {
                    "transport_cost": 22000.0,
                    "trips": [
                        {
                            "tag": "manipulator",
                            "tariff_name": "Манипулятор 5т",
                            "capacity_ton": 5.0,
                            "load_ton": 2.0,
                            "unloading_included": True,
                        }
                    ],
                }
            ],
            {},
        )

    def fake_generate_unload_candidates(*args, **kwargs):
        return (
            [
                {
                    "unloading": {
                        "service_type": "unloading",
                        "tag": "manipulator",
                        "tariff_name": "Манипулятор 5т",
                        "tariff_label": "Манипулятор 5т",
                        "cost": 22000.0,
                    },
                    "cost": 22000.0,
                }
            ],
            {},
        )

    monkeypatch.setattr(transport_calc, "generate_plans", fake_generate_plans)
    monkeypatch.setattr(transport_calc, "generate_delivery_candidates", fake_generate_delivery_candidates)
    monkeypatch.setattr(transport_calc, "generate_unload_candidates", fake_generate_unload_candidates)

    req = SimpleNamespace(
        upload_lat=55.0,
        upload_lon=37.0,
        transport_type="auto",
        add_manipulator=False,
        delivery_transport_tag="auto",
        unloading_transport_tag="auto",
        allowed_delivery_tags=[],
        allowed_unloading_tags=[],
        forbidden_delivery_tags=[],
        forbidden_unloading_tags=[],
        forbidden_types=[],
    )
    scenario = {
        "scenario_id": 43,
        "factories": {
            "Factory A": [{"weight_total": 18.0, "weight_per_item": 18.0, "quantity": 1}],
            "Factory B": [{"weight_total": 2.0, "weight_per_item": 2.0, "quantity": 1}],
        },
    }
    tariffs = [
        {
            "id": 502,
            "name": "Манипулятор 5т",
            "tag": "manipulator",
            "service_type": "unloading",
            "weight_condition": "any",
            "weight_threshold": None,
            "min_distance": 0,
            "max_distance": 0,
            "base": 22000.0,
            "per_km": 0.0,
            "is_active": True,
        }
    ]

    variants = transport_calc.evaluate_scenario_transport_variants(
        scenario,
        req,
        tariffs,
        max_vehicle_combos_per_plan=10,
        max_variants=10,
    )

    assert variants
    best = variants[0]
    assert best["delivery_cost"] == 74000.0
    # За два длинномера берём один фиксированный тариф разгрузки манипулятора.
    assert best["unloading_cost"] == 22000.0
    assert best["total_cost"] == best["material_sum"] + 96000.0