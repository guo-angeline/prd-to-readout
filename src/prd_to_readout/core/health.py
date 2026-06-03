"""Operational health monitoring for the recurring pulse.

Watches latency / crash / ANR / error metrics for regressions, separate from the
success metrics that drive the launch decision. For the simulated preview this
fabricates a daily series with an injected spike so the alerting is demonstrable;
real sources would feed observed values from an APM / crash reporter.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .schemas import HealthMetric

Severity = str  # "ok" | "watch" | "regression"


@dataclass
class HealthAlert:
    name: str
    kind: str
    unit: str
    severity: Severity
    observed: float       # recent-window mean (treatment arm)
    threshold: float
    baseline: float       # earlier-window mean


def simulate_health(health_metrics: list[HealthMetric], *, horizon_days: int, seed: int,
                    inject_regression: bool = True) -> dict[str, dict[str, list[float]]]:
    """Daily control/treatment series per health metric. Spikes the first metric."""
    rng = np.random.default_rng(seed + 777)
    series: dict[str, dict[str, list[float]]] = {}
    for i, hm in enumerate(health_metrics):
        baseline = max(hm.threshold * 0.6, 1e-6)
        ctrl = [max(0.0, float(rng.normal(baseline, baseline * 0.1))) for _ in range(horizon_days)]
        treat = [max(0.0, float(rng.normal(baseline, baseline * 0.1))) for _ in range(horizon_days)]
        if inject_regression and i == 0:
            for d in range(max(0, horizon_days - 3), horizon_days):
                treat[d] = hm.threshold * float(rng.uniform(1.2, 1.6))  # blow past the threshold
        series[hm.name] = {"control": ctrl, "treatment": treat}
    return series


def detect_regressions(series: dict[str, dict[str, list[float]]],
                       health_metrics: list[HealthMetric], *, recent: int = 3) -> list[HealthAlert]:
    alerts: list[HealthAlert] = []
    for hm in health_metrics:
        s = series.get(hm.name)
        if not s:
            continue
        treat = s["treatment"]
        recent_vals = treat[-recent:] if len(treat) >= recent else treat
        earlier = treat[:-recent] if len(treat) > recent else treat
        recent_mean = float(np.mean(recent_vals)) if recent_vals else 0.0
        baseline_mean = float(np.mean(earlier)) if earlier else recent_mean
        if recent_mean > hm.threshold:
            severity = "regression"
        elif baseline_mean > 0 and recent_mean > baseline_mean * 1.3:
            severity = "watch"
        else:
            severity = "ok"
        alerts.append(HealthAlert(hm.name, hm.kind, hm.unit, severity, recent_mean, hm.threshold, baseline_mean))
    return alerts


def overall_status(alerts: list[HealthAlert]) -> Severity:
    if any(a.severity == "regression" for a in alerts):
        return "regression"
    if any(a.severity == "watch" for a in alerts):
        return "watch"
    return "ok"
