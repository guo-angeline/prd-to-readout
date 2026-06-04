"""Pydantic models that pin down what each agent must produce.

These are the shared contract: the hypothesis agent emits an
:class:`AnalyticsBlueprint`, the logging agent emits a :class:`TrackingSchema`
(including :class:`MetricBinding` rows so the mock generator and the SQL agent
agree on what the raw events mean), and everything downstream reads them back.
"""

from __future__ import annotations

from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

MetricType = Literal["rate", "mean", "count"]
Direction = Literal["increase", "decrease"]
PropertyType = Literal["string", "number", "boolean", "timestamp"]


class Metric(BaseModel):
    name: str = Field(..., description="snake_case identifier, unique within the blueprint")
    description: str
    type: MetricType = Field(..., description="rate = proportion 0-1, mean = continuous, count = per-user events")
    formula: str = Field(..., description="plain-language definition of how it's computed")
    direction: Direction = Field("increase", description="which direction is a good outcome")
    unit: str | None = None


class Hypotheses(BaseModel):
    null: str = Field(..., description="H0, the no-effect statement")
    alternative: str = Field(..., description="H1, the effect we hope to see")
    # "If we X, then we'll observe Y, because Z" framing for the launch readout.
    if_we: str = Field("", description="the product intervention / what changed")
    then_observe: str = Field("", description="the expected behavioral outcome")
    because: str = Field("", description="the reasoning (user psychology, data insight)")


class Approvers(BaseModel):
    """GitHub handles of the humans who clear each gate (declared in the PRD).

    Roles map to gates: product clears the hypothesis, engineering confirms the
    logging, data_science reviews QA and the SQL.
    """

    product: str = Field("", description="GitHub handle, e.g. octocat (no @)")
    engineering: str = ""
    data_science: str = ""


class HealthMetric(BaseModel):
    """An operational/stability metric to monitor post-launch (not a success metric).

    These power the ongoing DAILY_PULSE health watch (latency spikes, crash/ANR
    increases), separate from the decision metrics in the launch readout.
    """

    name: str = Field(..., description="snake_case, e.g. p95_latency_ms, crash_rate")
    kind: Literal["latency", "crash_rate", "anr_rate", "error_rate"]
    unit: str = Field("", description="e.g. ms, %")
    threshold: float = Field(..., description="regression threshold: value above this is an alert")


class ExperimentDesign(BaseModel):
    control_arm: str = "control"
    treatment_arm: str = "treatment"
    treatment_split: float = Field(0.5, ge=0.05, le=0.95)
    horizon_days: int = Field(14, ge=1, le=365)
    users_per_arm: int = Field(2000, ge=50, le=1_000_000)
    mde: float = Field(0.05, gt=0, description="minimum detectable effect, relative")


class AnalyticsBlueprint(BaseModel):
    feature_name: str
    summary: str = Field(..., description="one-line statement of the feature's intent")
    # Decision-framing context for the launch readout (optional; derived from the PRD).
    problem: str = Field("", description="user friction / business deficiency, with baseline if known")
    strategic_alignment: str = Field("", description="how this maps to team goals / OKRs")
    whats_shipped: str = Field("", description="objective description of the treatment/variant")
    scope_audience: str = Field("", description="who saw the change (platforms, markets, split)")
    primary_metric: Metric
    guardrail_metrics: list[Metric] = Field(default_factory=list)
    health_metrics: list[HealthMetric] = Field(default_factory=list)
    approvers: Approvers = Field(default_factory=Approvers)
    hypotheses: Hypotheses
    experiment: ExperimentDesign = Field(default_factory=ExperimentDesign)

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.model_dump(), sort_keys=False, allow_unicode=True)

    @classmethod
    def from_yaml(cls, text: str) -> AnalyticsBlueprint:
        return cls.model_validate(yaml.safe_load(text))

    def all_metrics(self) -> list[Metric]:
        return [self.primary_metric, *self.guardrail_metrics]


class PropertySpec(BaseModel):
    name: str
    type: PropertyType
    required: bool = True
    description: str = ""


class EventSpec(BaseModel):
    name: str = Field(..., description="snake_case event name, e.g. checkout_completed")
    description: str
    properties: list[PropertySpec] = Field(default_factory=list)


class MetricBinding(BaseModel):
    """Tells the mock generator how to fabricate events that imply a metric.

    The SQL agent independently re-derives the metric from raw events; the
    binding only exists so the simulation produces data with a known, plantable
    signal (and so the recovered numbers are realistic).
    """

    metric_name: str = Field(..., description="must match a metric in the blueprint")
    event_name: str = Field(..., description="must match an event in this schema")
    kind: Literal["unique_user_conversion", "event_count", "numeric_mean"]
    value_property: str | None = Field(
        None, description="for numeric_mean: which numeric property carries the value"
    )
    base_value: float = Field(
        ..., description="control-arm baseline: probability (rate), mean count, or mean value"
    )

    @model_validator(mode="after")
    def _require_value_property(self) -> MetricBinding:
        if self.kind == "numeric_mean" and not self.value_property:
            raise ValueError(
                f"binding for '{self.metric_name}' is numeric_mean but has no value_property; "
                "name the numeric event property that carries the value"
            )
        return self


class TrackingSchema(BaseModel):
    events: list[EventSpec]
    bindings: list[MetricBinding]

    def event(self, name: str) -> EventSpec | None:
        return next((e for e in self.events if e.name == name), None)

    def binding_for(self, metric_name: str) -> MetricBinding | None:
        return next((b for b in self.bindings if b.metric_name == metric_name), None)
