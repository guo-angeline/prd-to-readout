from prd_to_readout.agents.hypothesis_agent import _power_lines, render_blueprint_doc
from prd_to_readout.core.schemas import CausalDesign, Metric


def _with_experiment(blueprint, **updates):
    exp = blueprint.experiment.model_copy(update=updates)
    return blueprint.model_copy(update={"experiment": exp})


def test_power_lines_no_baseline_is_just_the_mde(blueprint):
    # Fixture has no baseline_conversion and no primary-metric baseline: only the
    # MDE line should render, with no sample-size math.
    lines = _power_lines(blueprint)
    assert lines == ["- **Minimum detectable effect:** 5% relative lift, "
                     "80% power, two-tailed at α=0.05."]


def test_power_lines_baseline_flags_underpowered(blueprint):
    # Fixture plans 400 users/arm; detecting a 5% lift on a 30% rate needs far more.
    lines = _power_lines(_with_experiment(blueprint, baseline_conversion=0.30))
    text = "\n".join(lines)
    assert "**Baseline conversion:** 30.0%." in text
    assert "**Required sample size:**" in text
    assert "underpowered" in text


def test_power_lines_baseline_powered_has_no_warning(blueprint):
    lines = _power_lines(_with_experiment(blueprint, baseline_conversion=0.30,
                                          users_per_arm=1_000_000))
    text = "\n".join(lines)
    assert "**Required sample size:**" in text
    assert "underpowered" not in text


def test_power_lines_falls_back_to_primary_rate_baseline(blueprint):
    # With no explicit baseline_conversion, a rate primary metric's baseline is used.
    bp = blueprint.model_copy(update={
        "primary_metric": blueprint.primary_metric.model_copy(update={"baseline": 0.30}),
    })
    text = "\n".join(_power_lines(bp))
    assert "**Baseline conversion:** 30.0%." in text


def test_power_lines_includes_bias_mitigation(blueprint):
    lines = _power_lines(_with_experiment(blueprint, bias_mitigation="Fixed-horizon, SRM checks"))
    assert any("Bias & variance control:** Fixed-horizon, SRM checks" in line for line in lines)


def test_blueprint_doc_has_friendly_sections(blueprint):
    md = render_blueprint_doc(blueprint)
    for section in ["# Metric Plan:", "The bet", "Primary metric",
                    "Guardrails", "Health to watch", "How we will test it"]:
        assert section in md, section
    # readable content, not raw yaml keys
    assert blueprint.primary_metric.name in md
    assert "If we" in md and "Because" in md
    assert "—" not in md  # house style


def test_blueprint_doc_points_at_yaml_source(blueprint):
    md = render_blueprint_doc(blueprint)
    assert "metric_plan.yaml" in md


def _enrich(blueprint):
    """A template-complete blueprint: baselines/targets, success, adoption, power, causal."""
    exp = blueprint.experiment.model_copy(update={
        "baseline_conversion": 0.30, "mde": 0.05,
        "bias_mitigation": "Fixed-horizon, SRM checks",
        "causal": CausalDesign(method="difference_in_differences",
                               challenge="Marketplace network effects break user-level A/B",
                               treatment_units="Austin, Seattle", control_units="Denver, Phoenix"),
    })
    return blueprint.model_copy(update={
        "success_qualitative": "Users feel checkout is instant.",
        "success_quantitative": "Sustained conversion lift, flat cancellations.",
        "primary_metric": blueprint.primary_metric.model_copy(update={"baseline": 0.30, "target": 0.33}),
        "adoption_metrics": [Metric(name="feature_take_rate", description="Share who use it.",
                                    type="rate", formula="users who use / exposed",
                                    direction="increase", target=0.4)],
        "experiment": exp,
    })


def test_blueprint_doc_renders_template_sections(blueprint):
    md = render_blueprint_doc(_enrich(blueprint))
    for section in ["What we are building", "What success looks like",
                    "Adoption & engagement", "What good looks like",
                    "Baseline conversion", "Required sample size",
                    "Bias & variance control", "cannot run a clean A/B"]:
        assert section in md, section
    assert "30.0% -> 33.0%" in md           # primary baseline -> target
    assert "feature_take_rate" in md         # adoption metric surfaced
    assert "difference_in_differences" in md  # causal fallback
    assert "—" not in md  # house style
