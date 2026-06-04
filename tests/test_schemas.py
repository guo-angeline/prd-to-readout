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


def test_good_looks_like_phrasing():
    from prd_to_readout.core.schemas import Metric

    rate = Metric(name="r", description="d", type="rate", formula="f", baseline=0.3, target=0.36)
    assert rate.good_looks_like() == "30.0% -> 36.0%"
    bare = Metric(name="r", description="d", type="rate", formula="f", direction="decrease")
    assert bare.good_looks_like() == "lower is better"


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
