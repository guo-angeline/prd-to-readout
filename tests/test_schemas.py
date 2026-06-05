import pytest
from pydantic import ValidationError

from prd_to_readout.core.schemas import AnalyticsBlueprint, MetricBinding


def test_blueprint_yaml_roundtrip(blueprint):
    restored = AnalyticsBlueprint.from_yaml(blueprint.to_yaml())
    assert restored == blueprint
    assert restored.primary_metric.name == "cart_conversion_rate"


def test_all_metrics_includes_primary_first(blueprint):
    metrics = blueprint.all_metrics()
    assert metrics[0].name == blueprint.primary_metric.name
    assert len(metrics) == 1 + len(blueprint.guardrail_metrics)


def test_all_metrics_orders_primary_adoption_guardrails(blueprint):
    from prd_to_readout.core.schemas import Metric

    adoption = Metric(name="take_rate", description="d", type="rate", formula="f")
    bp = blueprint.model_copy(update={"adoption_metrics": [adoption]})
    names = [m.name for m in bp.all_metrics()]
    assert names == ["cart_conversion_rate", "take_rate", "order_cancellation_rate"]
    assert bp.role_of("cart_conversion_rate") == "primary"
    assert bp.role_of("take_rate") == "adoption"
    assert bp.role_of("order_cancellation_rate") == "guardrail"


def test_rejects_duplicate_metric_names(blueprint):
    data = blueprint.model_dump()
    # An adoption metric reusing the primary's name should be rejected.
    data["adoption_metrics"] = [blueprint.primary_metric.model_dump()]
    with pytest.raises(ValidationError, match="unique"):
        AnalyticsBlueprint.model_validate(data)


def test_good_looks_like_phrasing():
    from prd_to_readout.core.schemas import Metric

    rate = Metric(name="r", description="d", type="rate", formula="f", baseline=0.3, target=0.36)
    assert rate.good_looks_like() == "30.0% -> 36.0%"
    bare = Metric(name="r", description="d", type="rate", formula="f", direction="decrease")
    assert bare.good_looks_like() == "lower is better"


def test_good_looks_like_mean_and_count():
    from prd_to_readout.core.schemas import Metric

    # mean: not a percentage; the unit is appended via :g formatting.
    mean = Metric(name="m", description="d", type="mean", formula="f",
                  baseline=120, target=90, unit="s")
    assert mean.good_looks_like() == "120s -> 90s"
    # count: no unit, integral values render without a trailing zero.
    count = Metric(name="c", description="d", type="count", formula="f",
                   baseline=2.0, target=3.0)
    assert count.good_looks_like() == "2 -> 3"
    # target only / baseline only branches keep the unit.
    target_only = Metric(name="t", description="d", type="mean", formula="f",
                         target=4.5, unit="min")
    assert target_only.good_looks_like() == "reach 4.5min"
    baseline_only = Metric(name="b", description="d", type="count", formula="f", baseline=3.0)
    assert baseline_only.good_looks_like() == "move from 3 in the right direction"


def test_rejects_bad_split():
    with pytest.raises(ValidationError):
        AnalyticsBlueprint.model_validate(
            {
                "feature_name": "x",
                "summary": "y",
                "primary_metric": {
                    "name": "m", "description": "d", "type": "rate", "formula": "f",
                },
                "hypotheses": {"null": "n", "alternative": "a"},
                "experiment": {"treatment_split": 1.5},  # out of bounds
            }
        )


def test_rejects_sql_unsafe_identifiers():
    from prd_to_readout.core.schemas import EventSpec, Metric, MetricBinding, PropertySpec

    # These names get interpolated into SQL, so non-identifier names must be rejected.
    with pytest.raises(ValidationError, match="identifier"):
        Metric(name="bad-name", description="d", type="rate", formula="f")
    with pytest.raises(ValidationError, match="identifier"):
        EventSpec(name="order'; DROP TABLE x", description="d")
    with pytest.raises(ValidationError, match="identifier"):
        PropertySpec(name="2leading_digit", type="number")
    with pytest.raises(ValidationError, match="identifier"):
        MetricBinding(metric_name="m", event_name="has space", kind="event_count", base_value=1.0)
    with pytest.raises(ValidationError, match="identifier"):
        MetricBinding(metric_name="m", event_name="ev", kind="numeric_mean",
                      value_property="a-b", base_value=1.0)


def test_numeric_mean_binding_requires_value_property():
    with pytest.raises(ValidationError):
        MetricBinding(
            metric_name="session_length", event_name="session_end",
            kind="numeric_mean", base_value=120.0,  # missing value_property
        )
    ok = MetricBinding(
        metric_name="session_length", event_name="session_end",
        kind="numeric_mean", base_value=120.0, value_property="seconds",
    )
    assert ok.value_property == "seconds"


def test_rejects_unknown_metric_type():
    with pytest.raises(ValidationError):
        AnalyticsBlueprint.model_validate(
            {
                "feature_name": "x",
                "summary": "y",
                "primary_metric": {
                    "name": "m", "description": "d", "type": "ratio", "formula": "f",
                },
                "hypotheses": {"null": "n", "alternative": "a"},
            }
        )
