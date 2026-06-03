from prd_to_readout.core import health
from prd_to_readout.core.schemas import HealthMetric

METRICS = [
    HealthMetric(name="p95_latency_ms", kind="latency", unit="ms", threshold=250.0),
    HealthMetric(name="crash_rate", kind="crash_rate", unit="%", threshold=1.0),
]


def test_simulate_health_shapes():
    series = health.simulate_health(METRICS, horizon_days=10, seed=42)
    assert set(series) == {"p95_latency_ms", "crash_rate"}
    assert len(series["p95_latency_ms"]["treatment"]) == 10


def test_injected_spike_is_detected_as_regression():
    series = health.simulate_health(METRICS, horizon_days=10, seed=42, inject_regression=True)
    alerts = {a.name: a for a in health.detect_regressions(series, METRICS)}
    assert alerts["p95_latency_ms"].severity == "regression"
    assert alerts["p95_latency_ms"].observed > 250.0
    assert alerts["crash_rate"].severity == "ok"
    assert health.overall_status(list(alerts.values())) == "regression"


def test_no_regression_when_not_injected():
    series = health.simulate_health(METRICS, horizon_days=10, seed=42, inject_regression=False)
    alerts = health.detect_regressions(series, METRICS)
    assert health.overall_status(alerts) in ("ok", "watch")
