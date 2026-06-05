from prd_to_readout.core import mockgen
from prd_to_readout.core.schemas import EventSpec, Metric, MetricBinding


def _rate(events, arm, event_name, total_users):
    converters = {e["user_id"] for e in events if e["arm"] == arm and e["event_name"] == event_name}
    return len(converters) / total_users


def _with_adoption(blueprint, tracking):
    """A blueprint+schema that also carries one bound adoption metric."""
    bp = blueprint.model_copy(update={
        "adoption_metrics": [Metric(name="feature_take_rate", description="Used the feature.",
                                    type="rate", formula="users who use / exposed")],
    })
    tr = tracking.model_copy(update={
        "events": [*tracking.events, EventSpec(name="feature_used", description="Used feature.")],
        "bindings": [*tracking.bindings,
                     MetricBinding(metric_name="feature_take_rate", event_name="feature_used",
                                   kind="unique_user_conversion", base_value=0.40)],
    })
    return bp, tr


def test_deterministic_under_seed(blueprint, tracking):
    a = mockgen.generate_events(blueprint, tracking, seed=42, effect=0.15)
    b = mockgen.generate_events(blueprint, tracking, seed=42, effect=0.15)
    assert a == b


def test_different_seeds_differ(blueprint, tracking):
    a = mockgen.generate_events(blueprint, tracking, seed=1, effect=0.15)
    b = mockgen.generate_events(blueprint, tracking, seed=2, effect=0.15)
    assert a != b


def test_planted_lift_recoverable_on_primary(blueprint, tracking):
    effect = 0.25
    events = mockgen.generate_events(blueprint, tracking, seed=42, effect=effect)
    n = blueprint.experiment.users_per_arm
    ctrl = _rate(events, "control", "order_completed", n)
    treat = _rate(events, "treatment", "order_completed", n)
    # Treatment conversion should be roughly base*(1+effect); allow sampling slack.
    assert treat > ctrl
    assert abs((treat / ctrl) - (1 + effect)) < 0.12


def test_guardrail_stays_flat(blueprint, tracking):
    events = mockgen.generate_events(blueprint, tracking, seed=42, effect=0.25)
    n = blueprint.experiment.users_per_arm
    ctrl = _rate(events, "control", "order_cancelled", n)
    treat = _rate(events, "treatment", "order_cancelled", n)
    # No effect planted on the guardrail; arms should be close.
    assert abs(treat - ctrl) < 0.04


def test_adoption_effect_defaults_flat_and_preserves_stream(blueprint, tracking):
    # Default adoption_effect=0.0 must not perturb the existing event stream...
    bp, tr = _with_adoption(blueprint, tracking)
    base = mockgen.generate_events(bp, tr, seed=42, effect=0.2)
    same = mockgen.generate_events(bp, tr, seed=42, effect=0.2, adoption_effect=0.0)
    assert base == same
    # ...and adoption stays flat across arms.
    n = bp.experiment.users_per_arm
    ctrl = _rate(base, "control", "feature_used", n)
    treat = _rate(base, "treatment", "feature_used", n)
    assert abs(treat - ctrl) < 0.05


def test_adoption_effect_plants_recoverable_lift(blueprint, tracking):
    bp, tr = _with_adoption(blueprint, tracking)
    effect, adoption = 0.2, 0.4
    events = mockgen.generate_events(bp, tr, seed=42, effect=effect, adoption_effect=adoption)
    n = bp.experiment.users_per_arm
    a_ctrl = _rate(events, "control", "feature_used", n)
    a_treat = _rate(events, "treatment", "feature_used", n)
    assert a_treat > a_ctrl
    assert abs((a_treat / a_ctrl) - (1 + adoption)) < 0.12
    # Primary still lifts; guardrail still flat.
    assert _rate(events, "treatment", "order_completed", n) > _rate(events, "control", "order_completed", n)
    g = abs(_rate(events, "treatment", "order_cancelled", n) - _rate(events, "control", "order_cancelled", n))
    assert g < 0.04


def test_everyone_is_exposed(blueprint, tracking):
    events = mockgen.generate_events(blueprint, tracking, seed=7, effect=0.1)
    exposed = {e["user_id"] for e in events if e["event_name"] == mockgen.EXPOSURE_EVENT}
    assert len(exposed) == 2 * blueprint.experiment.users_per_arm
