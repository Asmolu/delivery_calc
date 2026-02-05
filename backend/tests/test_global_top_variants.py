from types import SimpleNamespace

from backend.service import transport_calc


def _make_request(
    *,
    allowed_delivery_tags,
    forbidden_delivery_tags=None,
) -> SimpleNamespace:
    return SimpleNamespace(
        upload_lat=55.0,
        upload_lon=37.0,
        transport_type="auto",
        add_manipulator=False,
        delivery_transport_tag="auto",
        unloading_transport_tag="none",
        allowed_delivery_tags=allowed_delivery_tags,
        allowed_unloading_tags=[],
        forbidden_delivery_tags=forbidden_delivery_tags or [],
        forbidden_unloading_tags=[],
        forbidden_types=[],
    )


def _make_scenario(weight_total: float) -> dict:
    return {
        "scenario_id": 10,
        "factories": {
            "Factory A": [
                {
                    "factory": {"name": "Factory A", "lat": 55.0, "lon": 37.0},
                    "category": "A",
                    "subtype": "X",
                    "weight_total": weight_total,
                    "weight_per_item": weight_total / 2,
                    "quantity": 2,
                    "price_per_item": 0,
                }
            ]
        },
    }


def test_global_ordering_across_vehicle_types(monkeypatch) -> None:
    monkeypatch.setattr(transport_calc, "get_osrm_distance_km", lambda *args, **kwargs: 10.0)

    tariffs = [
        {
            "id": 10,
            "name": "Shalanda A",
            "tag": "long_haul",
            "service_type": "delivery",
            "weight_condition": "any",
            "weight_threshold": None,
            "min_distance": 0,
            "max_distance": 100,
            "base": 131_750,
            "per_km": 0,
            "грузоподъёмность": 25,
            "is_active": True,
        },
        {
            "id": 11,
            "name": "Shalanda B",
            "tag": "long_haul",
            "service_type": "delivery",
            "weight_condition": "any",
            "weight_threshold": None,
            "min_distance": 0,
            "max_distance": 100,
            "base": 139_250,
            "per_km": 0,
            "грузоподъёмность": 25,
            "is_active": True,
        },
        {
            "id": 12,
            "name": "Container A",
            "tag": "container_carrier",
            "service_type": "delivery",
            "weight_condition": "any",
            "weight_threshold": None,
            "min_distance": 0,
            "max_distance": 100,
            "base": 0,
            "per_km": 0,
            "грузоподъёмность": 60,
            "base_transport_name": "Shalanda A",
            "base_transport_tag": "long_haul",
            "is_active": True,
        },
        {
            "id": 13,
            "name": "Container B",
            "tag": "container_carrier",
            "service_type": "delivery",
            "weight_condition": "any",
            "weight_threshold": None,
            "min_distance": 0,
            "max_distance": 100,
            "base": 0,
            "per_km": 0,
            "грузоподъёмность": 60,
            "base_transport_name": "Shalanda B",
            "base_transport_tag": "long_haul",
            "is_active": True,
        },
        {
            "id": 14,
            "name": "Manipulator",
            "tag": "manipulator",
            "service_type": "delivery",
            "weight_condition": "any",
            "weight_threshold": None,
            "min_distance": 0,
            "max_distance": 100,
            "base": 274_500,
            "per_km": 0,
            "грузоподъёмность": 60,
            "is_active": True,
        },
    ]

    variants = transport_calc.evaluate_scenario_transport_variants(
        _make_scenario(50),
        _make_request(allowed_delivery_tags=["container_carrier", "manipulator"]),
        tariffs,
        max_vehicle_combos_per_plan=10,
        max_variants=50,
    )

    totals = [round(v["total_cost"]) for v in variants[:3]]
    assert totals == [263_500, 274_500, 278_500]


def test_delivery_candidates_not_pruned_to_one(monkeypatch) -> None:
    monkeypatch.setattr(transport_calc, "get_osrm_distance_km", lambda *args, **kwargs: 10.0)

    tariffs = [
        {
            "id": 20,
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
            "id": 21,
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
        {
            "id": 22,
            "name": "Manipulator",
            "tag": "manipulator",
            "service_type": "delivery",
            "weight_condition": "any",
            "weight_threshold": None,
            "min_distance": 0,
            "max_distance": 100,
            "base": 1500,
            "per_km": 0,
            "грузоподъёмность": 20,
            "is_active": True,
        },
    ]

    variants = transport_calc.evaluate_scenario_transport_variants(
        _make_scenario(5),
        _make_request(allowed_delivery_tags=["long_haul", "flatbed", "manipulator"]),
        tariffs,
        max_vehicle_combos_per_plan=1,
        max_variants=10,
    )

    transport_names = {v["transport_name"] for v in variants}
    assert len(transport_names) > 1

def test_global_ranking_can_include_middle_long_haul(monkeypatch) -> None:
    monkeypatch.setattr(transport_calc, "get_osrm_distance_km", lambda *args, **kwargs: 10.0)

    tariffs = [
        {
            "id": 40,
            "name": "Shalanda A",
            "tag": "container_base",
            "service_type": "delivery",
            "weight_condition": "any",
            "weight_threshold": None,
            "min_distance": 0,
            "max_distance": 100,
            "base": 131_750,
            "per_km": 0,
            "грузоподъёмность": 25,
            "is_active": True,
        },
        {
            "id": 41,
            "name": "Shalanda B",
            "tag": "container_base",
            "service_type": "delivery",
            "weight_condition": "any",
            "weight_threshold": None,
            "min_distance": 0,
            "max_distance": 100,
            "base": 139_250,
            "per_km": 0,
            "грузоподъёмность": 25,
            "is_active": True,
        },
        {
            "id": 42,
            "name": "Container A",
            "tag": "container_carrier",
            "service_type": "delivery",
            "weight_condition": "any",
            "weight_threshold": None,
            "min_distance": 0,
            "max_distance": 100,
            "base": 0,
            "per_km": 0,
            "грузоподъёмность": 60,
            "base_transport_name": "Shalanda A",
            "base_transport_tag": "container_base",
            "is_active": True,
        },
        {
            "id": 43,
            "name": "Container B",
            "tag": "container_carrier",
            "service_type": "delivery",
            "weight_condition": "any",
            "weight_threshold": None,
            "min_distance": 0,
            "max_distance": 100,
            "base": 0,
            "per_km": 0,
            "грузоподъёмность": 60,
            "base_transport_name": "Shalanda B",
            "base_transport_tag": "container_base",
            "is_active": True,
        },
        {
            "id": 44,
            "name": "Long Haul Direct",
            "tag": "long_haul",
            "service_type": "delivery",
            "weight_condition": "any",
            "weight_threshold": None,
            "min_distance": 0,
            "max_distance": 100,
            "base": 274_500,
            "per_km": 0,
            "грузоподъёмность": 60,
            "is_active": True,
        },
    ]

    variants = transport_calc.evaluate_scenario_transport_variants(
        _make_scenario(50),
        _make_request(allowed_delivery_tags=["container_carrier", "long_haul"]),
        tariffs,
        max_vehicle_combos_per_plan=7,
        max_variants=50,
    )

    totals = [round(v["total_cost"]) for v in variants[:3]]
    assert totals == [263_500, 274_500, 278_500]


def test_forbidden_container_still_global_ranking(monkeypatch) -> None:
    monkeypatch.setattr(transport_calc, "get_osrm_distance_km", lambda *args, **kwargs: 10.0)

    tariffs = [
        {
            "id": 30,
            "name": "Container",
            "tag": "container_carrier",
            "service_type": "delivery",
            "weight_condition": "any",
            "weight_threshold": None,
            "min_distance": 0,
            "max_distance": 100,
            "base": 0,
            "per_km": 0,
            "грузоподъёмность": 60,
            "base_transport_name": "Shalanda",
            "base_transport_tag": "long_haul",
            "is_active": True,
        },
        {
            "id": 31,
            "name": "Shalanda",
            "tag": "long_haul",
            "service_type": "delivery",
            "weight_condition": "any",
            "weight_threshold": None,
            "min_distance": 0,
            "max_distance": 100,
            "base": 2000,
            "per_km": 0,
            "грузоподъёмность": 25,
            "is_active": True,
        },
        {
            "id": 32,
            "name": "Flatbed",
            "tag": "flatbed",
            "service_type": "delivery",
            "weight_condition": "any",
            "weight_threshold": None,
            "min_distance": 0,
            "max_distance": 100,
            "base": 2500,
            "per_km": 0,
            "грузоподъёмность": 25,
            "is_active": True,
        },
    ]

    variants = transport_calc.evaluate_scenario_transport_variants(
        _make_scenario(50),
        _make_request(
            allowed_delivery_tags=["container_carrier", "long_haul", "flatbed"],
            forbidden_delivery_tags=["container_carrier"],
        ),
        tariffs,
        max_vehicle_combos_per_plan=10,
        max_variants=10,
    )

    transport_names = {v["transport_name"] for v in variants}
    assert all("Container" not in name for name in transport_names)
