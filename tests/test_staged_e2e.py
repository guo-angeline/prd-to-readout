"""End-to-end staged workflow through the CLI, with a routed stub LLM.

Drives every stage and gate via CliRunner, so the real state machine, gate
enforcement, simulated ingestion, SQL build, and readout all execute. The only
thing stubbed is the network LLM call.
"""

from typer.testing import CliRunner

from prd_to_readout import cli
from prd_to_readout.agents import pipeline_agent
from prd_to_readout.agents.readout_agent import ReadoutSections
from prd_to_readout.cli import app
from prd_to_readout.core.schemas import AnalyticsBlueprint, TrackingSchema
from prd_to_readout.core.state import WorkflowState

runner = CliRunner()

_SECTIONS = ReadoutSections(
    tldr_outcome="Primary metric moved favorably.",
    next_steps=["Roll out to 100%"],
    deep_dives=["No segmentation computed."],
    rationale="Primary beat the bar without harming guardrails.",
    monitoring_plan="Watch retention for 30 days.",
)


def test_full_gated_workflow(tmp_path, blueprint, tracking, monkeypatch):
    bp_json = blueprint.model_dump_json()
    tr_json = tracking.model_dump_json()
    good_sql = pipeline_agent.fallback_sql(blueprint, tracking)

    class Router:
        """Routes by schema/system prompt so one stub serves every stage."""

        def complete(self, system, user, **k):
            return good_sql if "DuckDB" in system else "The primary metric moved favorably."

        def complete_json(self, system, user, schema, **k):
            if schema is AnalyticsBlueprint:
                return AnalyticsBlueprint.model_validate_json(bp_json)
            if schema is TrackingSchema:
                return TrackingSchema.model_validate_json(tr_json)
            if schema is ReadoutSections:
                return _SECTIONS
            raise AssertionError(f"unexpected schema {schema}")

    monkeypatch.setattr(cli, "_llm", lambda cfg: Router())

    w = ["-w", str(tmp_path)]
    prd = tmp_path / "prd.md"
    prd.write_text("# Feature\nLet users check out in one tap.")

    def ok(*args):
        res = runner.invoke(app, [*args, *w])
        assert res.exit_code == 0, res.stdout
        return res

    # Gate enforcement: cannot build before earlier stages are approved.
    blocked = runner.invoke(app, ["build", *w])
    assert blocked.exit_code == 1

    ok("hypothesize", str(prd))
    ok("approve", "hypothesis", "--by", "pm")
    ok("spec")
    ok("approve", "instrumentation", "--by", "eng")
    ok("verify-instrumentation")
    ok("approve", "instrumentation_qa", "--by", "ds")
    ok("build")
    ok("approve", "pipeline", "--by", "ds")
    ok("pulse")                       # monitoring works after pipeline approved
    ok("readout", "--force")          # one-off decision; force past the 2-week window

    # Final state: everything cleared, readout terminal.
    state = WorkflowState.load(tmp_path / ".pulse" / "state.yaml")
    assert state.stage("pipeline").status == "approved"
    assert state.stage("readout").status == "done"
    assert state.launch_date is not None

    readout = (tmp_path / "READOUT.md").read_text()
    assert "Launch Readout" in readout
    assert "Final Recommendation" in readout
    pulse = (tmp_path / "DAILY_PULSE.md").read_text()
    assert "Status" in pulse and "Health" in pulse
    assert (tmp_path / "models" / "metrics_daily.sql").exists()


def test_run_yes_preview_one_shot(tmp_path, blueprint, tracking, monkeypatch):
    bp_json = blueprint.model_dump_json()
    tr_json = tracking.model_dump_json()
    good_sql = pipeline_agent.fallback_sql(blueprint, tracking)

    class Router:
        def complete(self, system, user, **k):
            return good_sql if "DuckDB" in system else "Looks good."

        def complete_json(self, system, user, schema, **k):
            if schema is AnalyticsBlueprint:
                return AnalyticsBlueprint.model_validate_json(bp_json)
            if schema is ReadoutSections:
                return _SECTIONS
            return TrackingSchema.model_validate_json(tr_json)

    monkeypatch.setattr(cli, "_llm", lambda cfg: Router())
    prd = tmp_path / "prd.md"
    prd.write_text("# Feature\nOne tap.")

    res = runner.invoke(app, ["run", str(prd), "-w", str(tmp_path), "--yes", "--preview"])
    assert res.exit_code == 0, res.stdout
    state = WorkflowState.load(tmp_path / ".pulse" / "state.yaml")
    assert state.stage("readout").status == "done"
    assert (tmp_path / "READOUT.md").exists()
    assert (tmp_path / "DAILY_PULSE.md").exists()
