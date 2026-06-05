from prd_to_readout.core.provenance import RunContext, build_run_context
from prd_to_readout.core.stats import StatResult


def _mean_primary(n, control_std=15.0):
    return StatResult(
        metric_name="avg_order_value", metric_type="mean", direction="increase",
        is_primary=True, control_value=50.0, treatment_value=52.0, abs_diff=2.0,
        relative_lift=0.04, p_value=0.2, ci_low=0, ci_high=0,
        n_control=n, n_treatment=n, mde=0.05, control_std=control_std,
    )


def _ctx(**kw):
    base = dict(
        source_kind="file", n_control=2000, n_treatment=2000, required_n=1000,
        alpha=0.05, mde=0.05, multiple_comparison="Holm-Bonferroni", generated_at="2026-06-03",
    )
    base.update(kw)
    return RunContext(**base)


def test_simulated_is_never_trustworthy():
    ctx = _ctx(source_kind="simulated")
    assert ctx.is_simulated
    assert not ctx.trustworthy_verdict


def test_real_and_powered_is_trustworthy():
    assert _ctx().trustworthy_verdict


def test_underpowered_not_trustworthy():
    ctx = _ctx(n_control=100, n_treatment=100, required_n=1000)
    assert not ctx.powered
    assert not ctx.trustworthy_verdict


def test_no_required_n_counts_as_powered():
    assert _ctx(required_n=0).powered


def test_mean_primary_is_power_gated(blueprint):
    # A mean primary now gets a real required_n, so it can be flagged underpowered
    # instead of always counting as powered (required_n=0).
    small = build_run_context({"kind": "file"}, [_mean_primary(n=20)], blueprint,
                              generated_at="2026-06-03")
    assert small.required_n > 0
    assert not small.powered
    big = build_run_context({"kind": "file"}, [_mean_primary(n=10_000)], blueprint,
                            generated_at="2026-06-03")
    assert big.powered
