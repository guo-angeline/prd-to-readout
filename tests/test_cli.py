"""CLI tests for the commands that don't need an LLM (init, status, gates)."""

from typer.testing import CliRunner

from prd_to_readout.cli import app
from prd_to_readout.core.state import WorkflowState

runner = CliRunner()


def test_init_creates_state(tmp_path):
    res = runner.invoke(app, ["init", "-w", str(tmp_path)])
    assert res.exit_code == 0
    assert (tmp_path / ".pulse" / "state.yaml").exists()
    assert (tmp_path / "prd.md").exists()


def test_status_before_init(tmp_path):
    res = runner.invoke(app, ["status", "-w", str(tmp_path)])
    assert res.exit_code == 0
    assert "No workflow" in res.stdout


def test_spec_blocked_before_hypothesis_approved(tmp_path):
    runner.invoke(app, ["init", "-w", str(tmp_path)])
    res = runner.invoke(app, ["logging", "-w", str(tmp_path)])
    assert res.exit_code == 1
    assert "Cannot run 'logging'" in res.stdout


def test_approve_records_in_state(tmp_path):
    runner.invoke(app, ["init", "-w", str(tmp_path)])
    res = runner.invoke(app, ["approve", "metric", "--by", "alice", "-w", str(tmp_path)])
    assert res.exit_code == 0
    state = WorkflowState.load(tmp_path / ".pulse" / "state.yaml")
    assert state.stage("metric").status == "approved"
    assert state.stage("metric").approver == "alice"


def test_request_changes_requires_note(tmp_path):
    runner.invoke(app, ["init", "-w", str(tmp_path)])
    # Missing --note should error out (it's required).
    res = runner.invoke(app, ["request-changes", "metric", "-w", str(tmp_path)])
    assert res.exit_code != 0


def test_stage_prefix_resolves(tmp_path):
    runner.invoke(app, ["init", "-w", str(tmp_path)])
    res = runner.invoke(app, ["approve", "met", "-w", str(tmp_path)])
    assert res.exit_code == 0
    state = WorkflowState.load(tmp_path / ".pulse" / "state.yaml")
    assert state.stage("metric").status == "approved"


def test_status_shows_board(tmp_path):
    runner.invoke(app, ["init", "-w", str(tmp_path)])
    res = runner.invoke(app, ["status", "-w", str(tmp_path)])
    assert res.exit_code == 0
    assert "Metric" in res.stdout
