from prd_to_readout.core import mockgen


def _rate(events, arm, event_name, total_users):
    converters = {e["user_id"] for e in events if e["arm"] == arm and e["event_name"] == event_name}
    return len(converters) / total_users


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


def test_everyone_is_exposed(blueprint, tracking):
    events = mockgen.generate_events(blueprint, tracking, seed=7, effect=0.1)
    exposed = {e["user_id"] for e in events if e["event_name"] == mockgen.EXPOSURE_EVENT}
    assert len(exposed) == 2 * blueprint.experiment.users_per_arm
