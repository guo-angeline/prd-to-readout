import pytest

from prd_to_readout.core import workflow
from prd_to_readout.core.state import STAGE_ORDER, WorkflowState
from prd_to_readout.core.workflow import GateError


def test_new_state_all_pending():
    s = WorkflowState.new("feat", prd_path="prd.md")
    assert set(s.stages) == set(STAGE_ORDER)
    assert all(st.status == "pending" for st in s.stages.values())


def test_gate_blocks_out_of_order():
    s = WorkflowState.new("feat")
    workflow.ensure_can_run(s, "hypothesis")  # first stage always runnable
    with pytest.raises(GateError):
        workflow.ensure_can_run(s, "instrumentation")


def test_complete_stage_parks_at_gate_then_approve_unblocks():
    s = WorkflowState.new("feat")
    status = workflow.complete_stage(s, "hypothesis", ["analytics_blueprint.yaml"])
    assert status == "awaiting_approval"
    # Still blocked until a human approves.
    with pytest.raises(GateError):
        workflow.ensure_can_run(s, "instrumentation")
    workflow.approve(s, "hypothesis", by="alice", note="looks good")
    assert s.stage("hypothesis").status == "approved"
    assert s.stage("hypothesis").approver == "alice"
    workflow.ensure_can_run(s, "instrumentation")  # no raise


def test_auto_yes_approves_immediately():
    s = WorkflowState.new("feat")
    status = workflow.complete_stage(s, "hypothesis", [], auto_yes=True)
    assert status == "approved"
    workflow.ensure_can_run(s, "instrumentation")


def test_readout_is_terminal_not_gated():
    s = WorkflowState.new("feat")
    for stage in ["hypothesis", "instrumentation", "instrumentation_qa", "pipeline"]:
        workflow.complete_stage(s, stage, [], auto_yes=True)
    status = workflow.complete_stage(s, "readout", ["DAILY_PULSE.md"])
    assert status == "done"


def test_request_changes_blocks_next_stage():
    s = WorkflowState.new("feat")
    workflow.complete_stage(s, "hypothesis", [], auto_yes=True)
    workflow.request_changes(s, "hypothesis", by="bob", note="wrong primary metric")
    assert s.stage("hypothesis").status == "changes_requested"
    with pytest.raises(GateError):
        workflow.ensure_can_run(s, "instrumentation")


def test_state_roundtrip(tmp_path):
    s = WorkflowState.new("feat", prd_path="prd.md", prd_hash="abc123")
    workflow.complete_stage(s, "hypothesis", ["bp.yaml"], auto_yes=True)
    path = tmp_path / "state.yaml"
    s.save(path)
    loaded = WorkflowState.load(path)
    assert loaded.feature == "feat"
    assert loaded.prd_hash == "abc123"
    assert loaded.stage("hypothesis").status == "approved"
    assert loaded.stage("hypothesis").history  # history persisted


def test_next_action_points_to_first_runnable():
    s = WorkflowState.new("feat")
    assert "hypothesize" in workflow.next_action(s)
    workflow.complete_stage(s, "hypothesis", [])
    assert "approve hypothesis" in workflow.next_action(s)
