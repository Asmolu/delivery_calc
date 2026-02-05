import pytest


from backend.service.transport_calc import (
    _build_group_max_distance,
    _container_trip_cost,
    _select_tariff_for_load,
)


def _make_shalanda_tariffs(*, capacity: float, base_le: float, base_gt: float):
    return [
        {
            "id": 1,
            "name": "Shalanda",
            "tag": "long_haul",
            "service_type": "delivery",
            "weight_condition": "le",
            "weight_threshold": 22,
            "min_distance": 60,
            "max_distance": 80,
            "base": base_le,
            "per_km": 0,
            "грузоподъёмность": capacity,
            "is_active": True,
        },
        {
            "id": 2,
            "name": "Shalanda",
            "tag": "long_haul",
            "service_type": "delivery",
            "weight_condition": "gt",
            "weight_threshold": 22,
            "min_distance": 60,
            "max_distance": 80,
            "base": base_gt,
            "per_km": 0,
            "грузоподъёмность": capacity,
            "is_active": True,
        },
    ]


def test_weight_tier_selection_prefers_gt_for_heavy_weight() -> None:
    tariffs = _make_shalanda_tariffs(capacity=44, base_le=24000, base_gt=28000)
    group_max_distance = _build_group_max_distance(tariffs)

    chosen = _select_tariff_for_load(
        tariffs,
        "long_haul",
        distance_km=70,
        load_ton=44,
        group_max_distance=group_max_distance,
        pickup_points=None,
        dropoff_point=None,
    )

    assert chosen is not None
    assert chosen["weight_condition"] == "gt"
    assert chosen["base"] == 28000


def test_container_trip_cost_uses_shalanda_weight_tier() -> None:
    tariffs = _make_shalanda_tariffs(capacity=44, base_le=24000, base_gt=28000)
    container_tariff = {
        "name": "Container",
        "tag": "container_carrier",
        "service_type": "delivery",
        "base_transport_name": "Shalanda",
        "base_transport_tag": "long_haul",
    }
    group_max_distance = _build_group_max_distance(tariffs + [container_tariff])

    cost, _ = _container_trip_cost(
        container_tariff,
        qty_rows=[{"qty": 1, "weight_per_item": 44}],
        real_weight=44,
        tariffs=tariffs,
        distance_km=70,
        group_max_distance=group_max_distance,
        pickup_points=None,
        dropoff_point=None,
    )

    assert cost == pytest.approx(28000)


def test_weight_tier_selection_regression_for_light_weight() -> None:
    tariffs = _make_shalanda_tariffs(capacity=20, base_le=24000, base_gt=28000)
    container_tariff = {
        "name": "Container",
        "tag": "container_carrier",
        "service_type": "delivery",
        "base_transport_name": "Shalanda",
        "base_transport_tag": "long_haul",
    }
    group_max_distance = _build_group_max_distance(tariffs + [container_tariff])

    chosen = _select_tariff_for_load(
        tariffs,
        "long_haul",
        distance_km=70,
        load_ton=20,
        group_max_distance=group_max_distance,
        pickup_points=None,
        dropoff_point=None,
    )
    assert chosen is not None
    assert chosen["weight_condition"] == "le"
    assert chosen["base"] == 24000

    cost, _ = _container_trip_cost(
        container_tariff,
        qty_rows=[{"qty": 1, "weight_per_item": 20}],
        real_weight=20,
        tariffs=tariffs,
        distance_km=70,
        group_max_distance=group_max_distance,
        pickup_points=None,
        dropoff_point=None,
    )

    assert cost == pytest.approx(24000)
