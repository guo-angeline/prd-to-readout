"""Seeded two-arm event-stream simulator.

Fabricates a realistic raw event log for a control/treatment experiment, with a
known lift planted on the primary metric only (guardrails stay flat). Seeded, so
the demo and tests are reproducible. The SQL agent and the stats layer then have
to *recover* the planted signal from the raw events.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import numpy as np

from .schemas import AnalyticsBlueprint, EventSpec, MetricBinding, TrackingSchema

# Fixed epoch so output never depends on wall-clock time.
START = datetime(2026, 1, 1)
EXPOSURE_EVENT = "experiment_exposed"


def _dummy_prop(ptype: str, rng: np.random.Generator) -> Any:
    if ptype == "number":
        return round(float(rng.uniform(1, 100)), 2)
    if ptype == "boolean":
        return bool(rng.integers(0, 2))
    if ptype == "timestamp":
        return None
    return "value"


def _make_event(
    name: str,
    uid: str,
    arm: str,
    ts: datetime,
    ev: EventSpec | None,
    rng: np.random.Generator,
    binding: MetricBinding,
    value: float | None,
) -> dict[str, Any]:
    props: dict[str, Any] = {}
    if ev:
        for p in ev.properties:
            props[p.name] = _dummy_prop(p.type, rng)
    if binding.value_property is not None and value is not None:
        props[binding.value_property] = round(value, 4)
    return {"event_name": name, "user_id": uid, "arm": arm, "ts": ts, "props": props}


def generate_events(
    bp: AnalyticsBlueprint,
    schema: TrackingSchema,
    *,
    seed: int,
    effect: float,
) -> list[dict[str, Any]]:
    """Simulate the full raw event stream for both arms."""
    rng = np.random.default_rng(seed)
    exp = bp.experiment
    horizon = exp.horizon_days
    n = exp.users_per_arm
    primary = bp.primary_metric.name
    metrics_by_name = {m.name: m for m in bp.all_metrics()}
    events: list[dict[str, Any]] = []

    for arm in (exp.control_arm, exp.treatment_arm):
        is_treatment = arm == exp.treatment_arm
        for i in range(n):
            uid = f"{arm}_{i}"
            entry_day = int(rng.integers(0, horizon))
            base_ts = START + timedelta(days=entry_day, seconds=int(rng.integers(0, 86400)))

            # Everyone is "exposed" so they appear in per-day denominators.
            events.append(
                {"event_name": EXPOSURE_EVENT, "user_id": uid, "arm": arm,
                 "ts": base_ts, "props": {}}
            )

            for b in schema.bindings:
                if b.metric_name not in metrics_by_name:
                    continue
                ev = schema.event(b.event_name)
                mult = 1.0 + effect if (is_treatment and b.metric_name == primary) else 1.0

                if b.kind == "unique_user_conversion":
                    p = min(max(b.base_value * mult, 0.0), 1.0)
                    if rng.random() < p:
                        events.append(_make_event(b.event_name, uid, arm, base_ts, ev, rng, b, None))
                elif b.kind == "event_count":
                    k = int(rng.poisson(max(b.base_value * mult, 0.0)))
                    for j in range(k):
                        ts_j = base_ts + timedelta(seconds=j + 1)
                        events.append(_make_event(b.event_name, uid, arm, ts_j, ev, rng, b, None))
                elif b.kind == "numeric_mean":
                    sd = abs(b.base_value) * 0.3 if b.base_value else 1.0
                    val = float(rng.normal(b.base_value * mult, sd))
                    events.append(_make_event(b.event_name, uid, arm, base_ts, ev, rng, b, val))

    return events
