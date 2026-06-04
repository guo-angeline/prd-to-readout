"""verify-logging against a REAL events file, driven through the CLI."""

import csv
import json

from typer.testing import CliRunner

from prd_to_readout.cli import app
from prd_to_readout.core import mockgen, workflow
from prd_to_readout.core.state import WorkflowState

runner = CliRunner()


def _seed_workspace(tmp_path, blueprint, tracking, *, events_path):
    (tmp_path / ".pulse").mkdir(parents=True, exist_ok=True)
    (tmp_path / "metric_plan.yaml").write_text(blueprint.to_yaml())
    (tmp_path / "tracking_schema.json").write_text(tracking.model_dump_json(indent=2))

    # Approve stages 1-2 so verify-logging may run.
    state = WorkflowState.new(blueprint.feature_name)
    workflow.complete_stage(state, "metric", [], auto_yes=True)
    workflow.complete_stage(state, "logging", [], auto_yes=True)
    state.save(tmp_path / ".pulse" / "state.yaml")

    # Export simulated events to a CSV so it stands in for a real export.
    events = mockgen.generate_events(blueprint, tracking, seed=7, effect=0.2)
    with events_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["event_name", "user_id", "arm", "ts", "props"])
        for e in events:
            w.writerow([e["event_name"], e["user_id"], e["arm"], str(e["ts"]), json.dumps(e["props"])])


def test_verify_logging_with_real_file(tmp_path, blueprint, tracking):
    events_path = tmp_path / "real_events.csv"
    _seed_workspace(tmp_path, blueprint, tracking, events_path=events_path)

    res = runner.invoke(app, ["verify-logging", "--source", str(events_path), "-w", str(tmp_path)])
    assert res.exit_code == 0, res.stdout

    state = WorkflowState.load(tmp_path / ".pulse" / "state.yaml")
    assert state.source["kind"] == "file"
    assert state.stage("logging_qa").status == "awaiting_approval"
    assert (tmp_path / "LOGGING_QA.md").exists()
    assert "PASS" in (tmp_path / "LOGGING_QA.md").read_text()


def test_verify_logging_fails_qa_on_truncated_file(tmp_path, blueprint, tracking):
    # A file missing a declared event should fail QA and block the gate.
    events_path = tmp_path / "partial.csv"
    _seed_workspace(tmp_path, blueprint, tracking, events_path=events_path)
    # Strip out the cancellation event entirely.
    rows = [r for r in events_path.read_text().splitlines() if "order_cancelled" not in r]
    events_path.write_text("\n".join(rows) + "\n")

    res = runner.invoke(app, ["verify-logging", "--source", str(events_path), "-w", str(tmp_path)])
    assert res.exit_code == 1
    state = WorkflowState.load(tmp_path / ".pulse" / "state.yaml")
    assert state.stage("logging_qa").status == "changes_requested"


def test_running_a_stage_implicitly_approves_the_prior_gate(tmp_path, blueprint, tracking):
    events_path = tmp_path / "real_events.csv"
    _seed_workspace(tmp_path, blueprint, tracking, events_path=events_path)
    # Leave logging parked at its gate, with no explicit approval.
    state = WorkflowState.load(tmp_path / ".pulse" / "state.yaml")
    state.stage("logging").status = "awaiting_approval"
    state.save(tmp_path / ".pulse" / "state.yaml")

    res = runner.invoke(app, ["verify-logging", "--source", str(events_path), "-w", str(tmp_path)])
    assert res.exit_code == 0, res.stdout

    state = WorkflowState.load(tmp_path / ".pulse" / "state.yaml")
    assert state.stage("logging").status == "approved"  # cleared by moving on
    assert state.stage("logging").approver == "advancing to logging_qa"
