from prd_to_readout.core import logging_qa, mockgen, stats
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
    report = logging_qa.run_qa(runner, blueprint, tracking)
    assert report.passed
    assert any("arriving" in c.name for c in report.checks)
    runner.close()


def test_qa_flags_missing_event(blueprint, tracking):
    runner = _runner(blueprint, tracking)
    runner.execute("DELETE FROM raw_events WHERE event_name = 'order_cancelled'")
    report = logging_qa.run_qa(runner, blueprint, tracking)
    assert not report.passed
    missing = [c for c in report.checks if "order_cancelled" in c.name and not c.passed]
    assert missing
    runner.close()


def test_unbound_declared_event_is_simulated_and_passes_qa(blueprint, tracking):
    # A declared event with no metric binding (like a session/denominator event)
    # must still be produced by the simulator, or the tool fails its own QA.
    from prd_to_readout.core.schemas import EventSpec, PropertySpec

    tracking.events.append(
        EventSpec(name="session_started", description="A session begins",
                  properties=[PropertySpec(name="session_id", type="string")])
    )
    runner = DuckDBRunner(":memory:")
    runner.load_raw_events(mockgen.generate_events(blueprint, tracking, seed=42, effect=0.2))

    present = {r[0] for r in runner.query("SELECT DISTINCT event_name FROM raw_events")}
    assert "session_started" in present

    report = logging_qa.run_qa(runner, blueprint, tracking)
    assert report.passed  # the unbound event arrives, so QA no longer fails
    runner.close()


def test_qa_arm_mismatch_surfaces_present_labels(blueprint, tracking):
    # Real file uses A/B instead of control/treatment: the check fails and the
    # detail must name the arm labels actually present, not just "0, 0".
    runner = _runner(blueprint, tracking)
    runner.execute("UPDATE raw_events SET arm = CASE WHEN arm = 'control' THEN 'A' ELSE 'B' END")
    report = logging_qa.run_qa(runner, blueprint, tracking)
    arms_check = next(c for c in report.checks if c.name == "both arms have users")
    assert not arms_check.passed
    assert "arms present:" in arms_check.detail
    assert "A=" in arms_check.detail and "B=" in arms_check.detail
    runner.close()


def test_qa_report_renders(blueprint, tracking):
    runner = _runner(blueprint, tracking)
    report = logging_qa.run_qa(runner, blueprint, tracking)
    md = logging_qa.render_qa_report(report, blueprint)
    assert "Logging QA" in md and "PASS" in md
    runner.close()
