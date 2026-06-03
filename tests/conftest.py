"""Shared fixtures + a stub LLM so the suite never needs an API key."""

from __future__ import annotations

import json

import pytest

from prd_to_readout.core.schemas import (
    AnalyticsBlueprint,
    EventSpec,
    ExperimentDesign,
    HealthMetric,
    Hypotheses,
    Metric,
    MetricBinding,
    PropertySpec,
    TrackingSchema,
)


class StubLLM:
    """Returns canned responses in order. Records the prompts it received."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str, **kw) -> str:
        self.calls.append((system, user))
        return self._responses.pop(0)

    def complete_json(self, system: str, user: str, schema, **kw):
        self.calls.append((system, user))
        return schema.model_validate(json.loads(self._responses.pop(0)))


@pytest.fixture
def blueprint() -> AnalyticsBlueprint:
    return AnalyticsBlueprint(
        feature_name="One-Tap Checkout",
        summary="Let returning users check out in a single tap.",
        primary_metric=Metric(
            name="cart_conversion_rate",
            description="Share of carts that become paid orders.",
            type="rate",
            formula="distinct converting users / distinct exposed users",
            direction="increase",
        ),
        guardrail_metrics=[
            Metric(
                name="order_cancellation_rate",
                description="Share of users who cancel an order.",
                type="rate",
                formula="distinct cancelling users / distinct exposed users",
                direction="decrease",
            ),
        ],
        health_metrics=[
            HealthMetric(name="p95_latency_ms", kind="latency", unit="ms", threshold=250.0),
            HealthMetric(name="crash_rate", kind="crash_rate", unit="%", threshold=1.0),
        ],
        hypotheses=Hypotheses(
            null="One-Tap Checkout has no effect on cart conversion.",
            alternative="One-Tap Checkout increases cart conversion.",
            if_we="add a one-tap checkout button for returning users",
            then_observe="cart conversion rises without more cancellations",
            because="we remove friction for users who already have payment on file",
        ),
        experiment=ExperimentDesign(
            horizon_days=5, users_per_arm=400, mde=0.05
        ),
    )


@pytest.fixture
def tracking() -> TrackingSchema:
    return TrackingSchema(
        events=[
            EventSpec(name="order_completed", description="Order paid.",
                      properties=[PropertySpec(name="amount", type="number")]),
            EventSpec(name="order_cancelled", description="Order cancelled.", properties=[]),
        ],
        bindings=[
            MetricBinding(metric_name="cart_conversion_rate", event_name="order_completed",
                          kind="unique_user_conversion", base_value=0.30),
            MetricBinding(metric_name="order_cancellation_rate", event_name="order_cancelled",
                          kind="unique_user_conversion", base_value=0.05),
        ],
    )
