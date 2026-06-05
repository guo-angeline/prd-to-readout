"""Statistical evaluation of each metric against its hypothesis.

Computed from the raw event stream (statistically correct), so a rate metric
gets a two-proportion z-test and mean/count metrics get Welch's t-test. The
aggregated ``metrics_daily`` layer drives the trend charts instead.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy import stats as sps

from .duckdb_runner import DuckDBRunner
from .mockgen import EXPOSURE_EVENT
from .schemas import AnalyticsBlueprint, Metric, TrackingSchema

ALPHA = 0.05


@dataclass
class StatResult:
    metric_name: str
    metric_type: str
    direction: str
    is_primary: bool
    control_value: float
    treatment_value: float
    abs_diff: float
    relative_lift: float
    p_value: float
    ci_low: float
    ci_high: float
    n_control: int
    n_treatment: int
    mde: float
    # primary / adoption / guardrail. Defaults to guardrail so a hand-built result
    # still gates the verdict; the real role is set from the blueprint in evaluate_metric.
    role: str = "guardrail"
    notes: list[str] = field(default_factory=list)
    alpha: float = ALPHA
    # Set by apply_holm() once all metrics are known; None means "not adjusted".
    p_adjusted: float | None = None
    rel_ci_low: float = 0.0
    rel_ci_high: float = 0.0
    # Control-arm standard deviation for mean/count metrics (0.0 for rates), used
    # to size the required sample for power-gating non-rate primaries.
    control_std: float = 0.0

    @property
    def effective_p(self) -> float:
        """The p-value used for decisions: multiple-comparison-adjusted if available."""
        return self.p_adjusted if self.p_adjusted is not None else self.p_value

    @property
    def significant(self) -> bool:
        """True if the (adjusted) p-value clears the significance threshold."""
        return self.effective_p < self.alpha

    @property
    def moved_favorably(self) -> bool:
        """True if the observed change points in the metric's desired direction."""
        return self.abs_diff > 0 if self.direction == "increase" else self.abs_diff < 0

    @property
    def beats_mde(self) -> bool:
        """True if the effect is significant and at least as large as the MDE."""
        return self.significant and abs(self.relative_lift) >= self.mde

    def as_dict(self) -> dict:
        """Serialize the result plus the derived decision flags for templating."""
        d = self.__dict__.copy()
        d |= {
            "effective_p": self.effective_p,
            "significant": self.significant,
            "moved_favorably": self.moved_favorably,
            "beats_mde": self.beats_mde,
        }
        return d


def apply_holm(results: list[StatResult], alpha: float = ALPHA) -> list[StatResult]:
    """Holm-Bonferroni correction across metrics, controlling family-wise error.

    Testing the primary + every guardrail inflates false positives; without this a
    flat guardrail will occasionally read 'significant' and flip the verdict. Sets
    ``p_adjusted`` and ``alpha`` on each result in place.
    """
    m = len(results)
    order = sorted(range(m), key=lambda i: results[i].p_value)
    running = 0.0
    for rank, idx in enumerate(order):
        adj = min(1.0, (m - rank) * results[idx].p_value)
        running = max(running, adj)  # enforce monotonic non-decreasing adjusted p
        results[idx].p_adjusted = running
        results[idx].alpha = alpha
    return results


def required_sample_size_rate(baseline: float, mde: float, *, alpha: float = ALPHA,
                              power: float = 0.8) -> int:
    """Per-arm sample size to detect a relative ``mde`` on a rate at given power."""
    p1 = min(max(baseline, 1e-6), 1 - 1e-6)
    p2 = min(max(p1 * (1 + mde), 1e-6), 1 - 1e-6)
    if p2 == p1:
        return 0
    z_a = sps.norm.ppf(1 - alpha / 2)
    z_b = sps.norm.ppf(power)
    n = (z_a + z_b) ** 2 * (p1 * (1 - p1) + p2 * (1 - p2)) / (p2 - p1) ** 2
    return int(math.ceil(n))


def required_sample_size_mean(baseline_mean: float, std: float, mde: float, *,
                              alpha: float = ALPHA, power: float = 0.8) -> int:
    """Per-arm sample size to detect a relative ``mde`` on a mean at given power.

    Two-sample t-test approximation: delta is the absolute effect
    (``baseline_mean * mde``) and ``std`` is the control-arm standard deviation.
    Returns 0 when no detectable effect can be defined (zero baseline or std).
    """
    delta = abs(baseline_mean * mde)
    if delta == 0 or std <= 0:
        return 0
    z_a = sps.norm.ppf(1 - alpha / 2)
    z_b = sps.norm.ppf(power)
    n = (z_a + z_b) ** 2 * 2 * std**2 / delta**2
    return int(math.ceil(n))


def srm_check(n_control: int, n_treatment: int, expected_treatment_frac: float = 0.5,
              alpha: float = 0.001) -> dict:
    """Sample-ratio-mismatch check: are arm sizes consistent with the planned split?

    A failing SRM (very small p) means randomization or logging is broken and the
    whole experiment is untrustworthy. This is a standard pre-analysis trust gate.
    """
    total = n_control + n_treatment
    if total == 0:
        return {"chisq": 0.0, "p_value": 1.0, "passed": True}
    exp_t = total * expected_treatment_frac
    exp_c = total * (1 - expected_treatment_frac)
    chisq = ((n_control - exp_c) ** 2 / exp_c if exp_c else 0.0) + (
        (n_treatment - exp_t) ** 2 / exp_t if exp_t else 0.0
    )
    p = float(sps.chi2.sf(chisq, df=1))
    return {"chisq": chisq, "p_value": p, "passed": p >= alpha}


def _two_proportion(x1: int, n1: int, x2: int, n2: int, mde: float) -> dict:
    p1 = x1 / n1 if n1 else 0.0
    p2 = x2 / n2 if n2 else 0.0
    diff = p2 - p1
    pooled = (x1 + x2) / (n1 + n2) if (n1 + n2) else 0.0
    se_pool = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2)) if n1 and n2 else 0.0
    z = diff / se_pool if se_pool else 0.0
    p_value = 2 * sps.norm.sf(abs(z)) if se_pool else 1.0
    se_unpool = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2) if n1 and n2 else 0.0
    half = 1.96 * se_unpool
    rel = diff / p1 if p1 else 0.0
    rel_half = (1.96 * se_unpool / p1) if p1 else 0.0
    return {
        "control_value": p1, "treatment_value": p2, "abs_diff": diff,
        "relative_lift": rel, "p_value": float(p_value),
        "ci_low": diff - half, "ci_high": diff + half, "n_control": n1, "n_treatment": n2,
        "rel_ci_low": rel - rel_half, "rel_ci_high": rel + rel_half,
    }


def _welch(control: np.ndarray, treatment: np.ndarray) -> dict:
    m1, m2 = float(control.mean()) if len(control) else 0.0, float(treatment.mean()) if len(treatment) else 0.0
    diff = m2 - m1
    if len(control) > 1 and len(treatment) > 1:
        res = sps.ttest_ind(treatment, control, equal_var=False)
        p_value = float(res.pvalue)
        se = math.sqrt(control.var(ddof=1) / len(control) + treatment.var(ddof=1) / len(treatment))
    else:
        p_value, se = 1.0, 0.0
    half = 1.96 * se
    rel = diff / m1 if m1 else 0.0
    rel_half = (1.96 * se / m1) if m1 else 0.0
    control_std = float(control.std(ddof=1)) if len(control) > 1 else 0.0
    return {
        "control_value": m1, "treatment_value": m2, "abs_diff": diff,
        "relative_lift": rel, "p_value": p_value,
        "ci_low": diff - half, "ci_high": diff + half,
        "n_control": len(control), "n_treatment": len(treatment),
        "rel_ci_low": rel - rel_half, "rel_ci_high": rel + rel_half,
        "control_std": control_std,
    }


def _binding(schema: TrackingSchema | None, metric: Metric):
    return schema.binding_for(metric.name) if schema else None


def evaluate_metric(
    runner: DuckDBRunner, bp: AnalyticsBlueprint, metric: Metric, schema: TrackingSchema | None
) -> StatResult:
    """Recover one metric from the raw event stream and run its significance test.

    Rates use a two-proportion z-test over distinct exposed/converting users;
    means and counts aggregate per user, then use Welch's t-test. The metric's
    binding (if any) names the event; otherwise it falls back to a sensible
    default. Returns an unadjusted :class:`StatResult`; call :func:`apply_holm`
    across the full set to set multiple-comparison-adjusted p-values.
    """
    exp = bp.experiment
    b = _binding(schema, metric)
    ctrl, treat = exp.control_arm, exp.treatment_arm
    notes: list[str] = []

    if metric.type == "rate":
        event = b.event_name if b else EXPOSURE_EVENT
        rows = {
            r[0]: (r[1], r[2])
            for r in runner.query(
                "SELECT arm, count(DISTINCT user_id) AS exposed, "
                f"count(DISTINCT CASE WHEN event_name='{event}' THEN user_id END) AS conv "
                "FROM raw_events GROUP BY arm"
            )
        }
        n1, x1 = rows.get(ctrl, (0, 0))
        n2, x2 = rows.get(treat, (0, 0))
        stats_d = _two_proportion(x1, n1, x2, n2, exp.mde)
    else:
        if metric.type == "count":
            event = b.event_name if b else metric.name
            sql = (
                f"SELECT arm, user_id, count(*) FILTER (WHERE event_name='{event}') AS v "
                "FROM raw_events GROUP BY arm, user_id"
            )
        else:  # mean
            event = b.event_name if b else metric.name
            prop = (b.value_property if b and b.value_property else "value")
            sql = (
                f"SELECT arm, user_id, avg(CAST(props->>'{prop}' AS DOUBLE)) AS v "
                f"FROM raw_events WHERE event_name='{event}' GROUP BY arm, user_id"
            )
        data: dict[str, list[float]] = {ctrl: [], treat: []}
        for arm, _uid, v in runner.query(sql):
            if v is not None and arm in data:
                data[arm].append(float(v))
        stats_d = _welch(np.array(data[ctrl]), np.array(data[treat]))

    return StatResult(
        metric_name=metric.name,
        metric_type=metric.type,
        direction=metric.direction,
        is_primary=(metric.name == bp.primary_metric.name),
        role=bp.role_of(metric.name),
        mde=exp.mde,
        notes=notes,
        **stats_d,
    )


def evaluate_all(
    runner: DuckDBRunner, bp: AnalyticsBlueprint, schema: TrackingSchema | None = None
) -> list[StatResult]:
    """Evaluate every blueprint metric (primary, adoption, guardrails) in order."""
    return [evaluate_metric(runner, bp, m, schema) for m in bp.all_metrics()]
