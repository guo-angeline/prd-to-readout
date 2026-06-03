import numpy as np

from prd_to_readout.core import mockgen, stats
from prd_to_readout.core.duckdb_runner import DuckDBRunner


def test_two_proportion_matches_known_value():
    # 60/100 vs 50/100: classic z-test, z ≈ 1.43, p ≈ 0.152.
    out = stats._two_proportion(50, 100, 60, 100, mde=0.05)
    assert abs(out["abs_diff"] - 0.10) < 1e-9
    assert 0.14 < out["p_value"] < 0.17


def test_welch_detects_clear_difference():
    a = np.full(200, 10.0) + np.linspace(-1, 1, 200)
    b = np.full(200, 14.0) + np.linspace(-1, 1, 200)
    out = stats._welch(a, b)
    assert out["abs_diff"] > 3.5
    assert out["p_value"] < 1e-6


def _mk(name, p, primary=False):
    return stats.StatResult(
        metric_name=name, metric_type="rate", direction="increase", is_primary=primary,
        control_value=0.3, treatment_value=0.31, abs_diff=0.01, relative_lift=0.03,
        p_value=p, ci_low=0, ci_high=0, n_control=1000, n_treatment=1000, mde=0.05,
    )


def test_holm_monotonic_and_corrects():
    results = [_mk("primary", 0.03, primary=True), _mk("guard", 0.04)]
    stats.apply_holm(results, alpha=0.05)
    adj = sorted(r.p_adjusted for r in results)
    assert adj[0] <= adj[1]  # monotonic
    # primary p=0.03 -> 2*0.03 = 0.06 > 0.05: no longer significant after correction
    primary = next(r for r in results if r.is_primary)
    assert primary.p_adjusted > 0.05
    assert not primary.significant


def test_required_sample_size_scales_with_mde():
    big_mde = stats.required_sample_size_rate(0.3, 0.20)
    small_mde = stats.required_sample_size_rate(0.3, 0.05)
    assert 0 < big_mde < small_mde  # smaller effect needs more samples


def test_evaluate_recovers_significant_primary_lift(blueprint, tracking):
    events = mockgen.generate_events(blueprint, tracking, seed=42, effect=0.30)
    runner = DuckDBRunner(":memory:")
    runner.load_raw_events(events)
    results = {r.metric_name: r for r in stats.evaluate_all(runner, blueprint, tracking)}

    primary = results["cart_conversion_rate"]
    assert primary.is_primary
    assert primary.treatment_value > primary.control_value
    assert primary.significant
    assert primary.moved_favorably

    guard = results["order_cancellation_rate"]
    assert not guard.significant  # flat guardrail
    runner.close()
