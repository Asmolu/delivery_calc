from backend.service import transport_calc


def _plan(tag: str, cost: float, *, tariff_name: str = "T1", trips: int = 1) -> dict:
    trip_list = [
        {
            "tag": tag,
            "tariff_name": tariff_name,
        }
        for _ in range(trips)
    ]
    return {
        "transport_cost": cost,
        "trips": trip_list,
    }


def test_diversity_trim_keeps_multiple_tags() -> None:
    container_plans = [_plan("container_carrier", float(idx), tariff_name=f"C{idx}") for idx in range(10)]
    long_haul_plans = [
        _plan("long_haul", 20.0, tariff_name="L1"),
        _plan("long_haul", 21.0, tariff_name="L2"),
    ]
    plans = container_plans + long_haul_plans

    trimmed, info = transport_calc._diversity_trim_plans(plans, max_total=7, k_per_tag=3)
    tags = [transport_calc._primary_delivery_tag(p["trips"]) for p in trimmed]

    assert "long_haul" in tags
    assert "container_carrier" in tags
    assert len(trimmed) <= 7
    assert info["kept_by_tag"]["long_haul"] >= 1


def test_determinism_ties() -> None:
    plan_fast = _plan("long_haul", 100.0, tariff_name="A", trips=1)
    plan_slow = _plan("long_haul", 100.0, tariff_name="B", trips=2)
    plan_sig_a = _plan("flatbed", 100.0, tariff_name="A", trips=1)
    plan_sig_b = _plan("flatbed", 100.0, tariff_name="B", trips=1)

    trimmed, _ = transport_calc._diversity_trim_plans(
        [plan_slow, plan_fast, plan_sig_b, plan_sig_a],
        max_total=10,
        k_per_tag=10,
    )

    assert trimmed.index(plan_fast) < trimmed.index(plan_slow)
    assert trimmed.index(plan_sig_a) < trimmed.index(plan_sig_b)
