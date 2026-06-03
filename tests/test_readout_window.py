"""The launch readout is gated on the 2-week window; pulse is not."""

from datetime import date, timedelta

from typer.testing import CliRunner

from prd_to_readout.cli import app
from prd_to_readout.core import workflow
from prd_to_readout.core.state import WorkflowState

runner = CliRunner()


def _ready_workspace(tmp_path, blueprint, tracking, *, launch_offset_days):
    from prd_to_readout.agents import pipeline_agent
    from prd_to_readout.core import mockgen
    from prd_to_readout.core.duckdb_runner import DuckDBRunner

    (tmp_path / ".pulse").mkdir(parents=True, exist_ok=True)
    (tmp_path / "analytics_blueprint.yaml").write_text(blueprint.to_yaml())
    (tmp_path / "tracking_schema.json").write_text(tracking.model_dump_json(indent=2))

    # Build the metrics table on disk so readout/pulse have data.
    runner_db = DuckDBRunner(tmp_path / ".pulse" / "pulse.duckdb")
    runner_db.load_raw_events(mockgen.generate_events(blueprint, tracking, seed=7, effect=0.2))
    runner_db.execute(pipeline_agent.fallback_sql(blueprint, tracking))
    runner_db.close()

    state = WorkflowState.new(blueprint.feature_name)
    for stage in ["hypothesis", "instrumentation", "instrumentation_qa", "pipeline"]:
        workflow.complete_stage(state, stage, [], auto_yes=True)
    state.launch_date = (date.today() - timedelta(days=launch_offset_days)).isoformat()
    state.save(tmp_path / ".pulse" / "state.yaml")


def test_readout_blocked_before_window(tmp_path, blueprint, tracking):
    _ready_workspace(tmp_path, blueprint, tracking, launch_offset_days=3)
    res = runner.invoke(app, ["readout", "-w", str(tmp_path)])
    assert res.exit_code == 0
    assert "not due yet" in res.stdout
    assert not (tmp_path / "READOUT.md").exists()


def test_readout_allowed_after_window(tmp_path, blueprint, tracking, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")  # satisfy the model preflight (LLM is stubbed)
    from prd_to_readout import cli
    from prd_to_readout.agents.readout_agent import ReadoutSections

    sections = ReadoutSections(tldr_outcome="x", next_steps=["y"], deep_dives=[],
                               rationale="r", monitoring_plan="m")

    class Router:
        def complete_json(self, system, user, schema, **k):
            return sections

    monkeypatch.setattr(cli, "_llm", lambda cfg: Router())
    _ready_workspace(tmp_path, blueprint, tracking, launch_offset_days=15)
    res = runner.invoke(app, ["readout", "-w", str(tmp_path)])
    assert res.exit_code == 0, res.stdout
    assert (tmp_path / "READOUT.md").exists()


def test_pulse_runs_without_window(tmp_path, blueprint, tracking):
    _ready_workspace(tmp_path, blueprint, tracking, launch_offset_days=1)
    res = runner.invoke(app, ["pulse", "-w", str(tmp_path)])
    assert res.exit_code == 0, res.stdout
    assert (tmp_path / "DAILY_PULSE.md").exists()
    assert "Health" in (tmp_path / "DAILY_PULSE.md").read_text()
