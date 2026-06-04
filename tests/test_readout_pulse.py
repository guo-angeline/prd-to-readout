from prd_to_readout.agents import pulse_agent
from prd_to_readout.agents.readout_agent import ReadoutSections, assemble_readout
from prd_to_readout.core.health import HealthAlert
from prd_to_readout.core.provenance import RunContext
from prd_to_readout.core.stats import StatResult


def _result(name, is_primary, direction, rel_lift, p):
    return StatResult(
        metric_name=name, metric_type="rate", direction=direction, is_primary=is_primary,
        control_value=0.30, treatment_value=0.35, abs_diff=0.05, relative_lift=rel_lift,
        p_value=p, ci_low=0, ci_high=0.1, n_control=2000, n_treatment=2000, mde=0.05,
    )


def _ctx(**kw):
    base = dict(source_kind="file", n_control=2000, n_treatment=2000, required_n=1000,
                alpha=0.05, mde=0.05, multiple_comparison="Holm-Bonferroni", generated_at="2026-06-17")
    base.update(kw)
    return RunContext(**base)


_SECTIONS = ReadoutSections(
    tldr_outcome="Conversion rose with no guardrail harm.",
    next_steps=["Roll out to 100%", "Deprecate legacy flow"],
    deep_dives=["No segmentation computed."],
    rationale="Primary beat the MDE and guardrails held.",
    monitoring_plan="Watch renewals for 30 days.",
)


def test_readout_fills_template_sections(blueprint):
    results = [_result("cart_conversion_rate", True, "increase", 0.16, 0.001),
              _result("order_cancellation_rate", False, "decrease", -0.01, 0.8)]
    md = assemble_readout(blueprint, results, _ctx(), _SECTIONS,
                          date_label="2026-06-17", window_label="2026-06-03 to 2026-06-17",
                          stakeholders="pm, ds")
    for section in ["Launch Readout", "TL;DR", "Context & Problem Statement", "What's Shipped",
                    "Hypothesis", "Metrics & Results", "Guardrail & Counter-Metrics",
                    "Final Recommendation"]:
        assert section in md, section
    assert "**SHIP**" in md
    assert "cart_conversion_rate" in md
    assert "—" not in md  # house style


def test_readout_shows_success_definition(blueprint):
    bp = blueprint.model_copy(update={
        "success_quantitative": "Conversion up 4 points, cancellations flat.",
        "success_qualitative": "Checkout feels instant for repeat buyers.",
    })
    results = [_result("cart_conversion_rate", True, "increase", 0.16, 0.001)]
    md = assemble_readout(bp, results, _ctx(), _SECTIONS,
                          date_label="d", window_label="w", stakeholders="s")
    assert "What Success Looks Like" in md
    assert "Conversion up 4 points" in md
    assert "Checkout feels instant" in md


def test_readout_simulated_is_preview(blueprint):
    results = [_result("cart_conversion_rate", True, "increase", 0.16, 0.001)]
    md = assemble_readout(blueprint, results, _ctx(source_kind="simulated"), _SECTIONS,
                          date_label="d", window_label="w", stakeholders="s")
    assert "Decision Status:** PREVIEW" in md
    assert "SIMULATED PREVIEW" in md


def test_pulse_flags_regression_and_makes_no_decision(blueprint):
    results = [_result("cart_conversion_rate", True, "increase", 0.16, 0.001)]
    alerts = [
        HealthAlert("p95_latency_ms", "latency", "ms", "regression", 380.0, 250.0, 150.0),
        HealthAlert("crash_rate", "crash_rate", "%", "ok", 0.6, 1.0, 0.6),
    ]
    md = pulse_agent.generate_pulse(blueprint, results, alerts, "chart", _ctx(), generated_at="2026-06-10")
    assert "Adoption & Engagement" in md
    assert "Health & Regressions" in md
    assert "REGRESSION" in md
    assert "p95_latency_ms" in md
    # Monitoring never decides:
    assert "SHIP" not in md and "Final Recommendation" not in md


def test_pulse_healthy_when_no_alerts(blueprint):
    results = [_result("cart_conversion_rate", True, "increase", 0.16, 0.001)]
    md = pulse_agent.generate_pulse(blueprint, results, [], "chart", _ctx(), generated_at="2026-06-10")
    assert "🟢 Status: HEALTHY" in md
