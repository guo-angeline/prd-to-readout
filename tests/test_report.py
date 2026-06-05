from prd_to_readout.agents.report_agent import _fmt, assemble, recommend
from prd_to_readout.core.provenance import RunContext
from prd_to_readout.core.stats import StatResult


def _ctx(**kw):
    base = dict(
        source_kind="file", n_control=2000, n_treatment=2000, required_n=1000,
        alpha=0.05, mde=0.05, multiple_comparison="Holm-Bonferroni", generated_at="2026-06-03",
    )
    base.update(kw)
    return RunContext(**base)


def test_fmt_never_scientific_notation():
    assert _fmt("rate", 0.4193) == "41.93%"
    assert _fmt("count", 2.038) == "2.04"
    big = _fmt("mean", 12345.6)
    assert "e" not in big.lower()
    assert big == "12,345.60"


def _result(name, is_primary, direction, abs_diff, rel_lift, p, mde=0.05):
    return StatResult(
        metric_name=name, metric_type="rate", direction=direction, is_primary=is_primary,
        control_value=0.30, treatment_value=0.30 + abs_diff, abs_diff=abs_diff,
        relative_lift=rel_lift, p_value=p, ci_low=0.0, ci_high=0.1,
        n_control=1000, n_treatment=1000, mde=mde,
    )


def test_recommend_ship(blueprint):
    results = [
        _result("cart_conversion_rate", True, "increase", 0.05, 0.16, 0.001),
        _result("order_cancellation_rate", False, "decrease", 0.0, 0.0, 0.9),
    ]
    verdict, _ = recommend(blueprint, results)
    assert verdict == "SHIP"


def test_recommend_kill_on_wrong_direction(blueprint):
    results = [_result("cart_conversion_rate", True, "increase", -0.04, -0.13, 0.001)]
    verdict, _ = recommend(blueprint, results)
    assert verdict == "KILL"


def test_recommend_iterate_below_mde(blueprint):
    results = [_result("cart_conversion_rate", True, "increase", 0.005, 0.016, 0.01, mde=0.05)]
    verdict, _ = recommend(blueprint, results)
    assert verdict == "ITERATE"


def test_recommend_iterate_when_primary_inconclusive(blueprint):
    # Primary not significant at all: the terminal "keep collecting" ITERATE branch.
    results = [_result("cart_conversion_rate", True, "increase", 0.002, 0.006, 0.5)]
    verdict, reason = recommend(blueprint, results)
    assert verdict == "ITERATE"
    assert "conclusive" in reason.lower()


def test_recommend_iterate_when_guardrail_harmed(blueprint):
    results = [
        _result("cart_conversion_rate", True, "increase", 0.05, 0.16, 0.001),
        _result("order_cancellation_rate", False, "decrease", 0.03, 0.6, 0.001),
    ]
    verdict, reason = recommend(blueprint, results)
    assert verdict == "ITERATE"
    assert "guardrail" in reason.lower()


def test_adoption_metric_does_not_gate_verdict(blueprint):
    # An adoption metric moving the wrong way is informational; it must NOT block SHIP.
    primary = _result("cart_conversion_rate", True, "increase", 0.05, 0.16, 0.001)
    adoption = _result("take_rate", False, "increase", -0.04, -0.13, 0.001)
    adoption.role = "adoption"
    verdict, _ = recommend(blueprint, [primary, adoption])
    assert verdict == "SHIP"


def test_assemble_contains_table_and_verdict(blueprint):
    results = [_result("cart_conversion_rate", True, "increase", 0.05, 0.16, 0.001)]
    md = assemble(blueprint, results, "chart-here", "narrative body")
    assert "## Metrics" in md
    assert "cart_conversion_rate" in md
    assert "Verdict" in md
    assert "chart-here" in md
    assert "—" not in md  # house style: no em dashes


def test_simulated_ctx_forces_preview_verdict(blueprint):
    results = [_result("cart_conversion_rate", True, "increase", 0.05, 0.16, 0.001)]
    verdict, _ = recommend(blueprint, results, _ctx(source_kind="simulated"))
    assert verdict == "PREVIEW"


def test_underpowered_ctx_forces_preview(blueprint):
    results = [_result("cart_conversion_rate", True, "increase", 0.05, 0.16, 0.001)]
    verdict, _ = recommend(blueprint, results, _ctx(n_control=50, n_treatment=50, required_n=1000))
    assert verdict == "PREVIEW"


def test_real_powered_ctx_allows_hard_verdict(blueprint):
    results = [_result("cart_conversion_rate", True, "increase", 0.05, 0.16, 0.001)]
    verdict, _ = recommend(blueprint, results, _ctx())
    assert verdict == "SHIP"


def test_assemble_simulated_banner_and_methodology(blueprint):
    results = [_result("cart_conversion_rate", True, "increase", 0.05, 0.16, 0.001)]
    md = assemble(blueprint, results, "chart", "body", _ctx(source_kind="simulated"))
    assert "SIMULATED PREVIEW" in md
    assert "Methodology & Assumptions" in md
    assert "Holm" in md
