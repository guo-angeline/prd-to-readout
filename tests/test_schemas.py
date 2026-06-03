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
