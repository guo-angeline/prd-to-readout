from prd_to_readout.core import instrumentation_qa, mockgen, stats
from prd_to_readout.core.duckdb_runner import DuckDBRunner


def _runner(blueprint, tracking, effect=0.2):
    runner = DuckDBRunner(":memory:")
    runner.load_raw_events(mockgen.generate_events(blueprint, tracking, seed=42, effect=effect))
    return runner


def test_srm_check_balanced_passes():
    out = stats.srm_check(1000, 1000, 0.5)
    assert out["passed"]
    assert out["p_value"] > 0.05


def test_srm_check_skewed_fails():
    out = stats.srm_check(1000, 500, 0.5)
    assert not out["passed"]
    assert out["p_value"] < 0.001


def test_qa_passes_on_clean_simulated_data(blueprint, tracking):
    runner = _runner(blueprint, tracking)
    report = instrumentation_qa.run_qa(runner, blueprint, tracking)
    assert report.passed
    assert any("arriving" in c.name for c in report.checks)
    runner.close()


def test_qa_flags_missing_event(blueprint, tracking):
    runner = _runner(blueprint, tracking)
    runner.execute("DELETE FROM raw_events WHERE event_name = 'order_cancelled'")
    report = instrumentation_qa.run_qa(runner, blueprint, tracking)
    assert not report.passed
    missing = [c for c in report.checks if "order_cancelled" in c.name and not c.passed]
    assert missing
    runner.close()


def test_qa_report_renders(blueprint, tracking):
    runner = _runner(blueprint, tracking)
    report = instrumentation_qa.run_qa(runner, blueprint, tracking)
    md = instrumentation_qa.render_qa_report(report, blueprint)
    assert "Instrumentation QA" in md and "PASS" in md
    runner.close()
