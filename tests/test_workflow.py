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
    # At a terminal gate the hint points at the next stage, which approves implicitly.
    hint = workflow.next_action(s)
    assert "spec" in hint and "approve it" in hint


def test_advance_into_approves_parked_predecessor():
    s = WorkflowState.new("feat")
    workflow.complete_stage(s, "hypothesis", [])  # parks at awaiting_approval
    cleared = workflow.advance_into(s, "instrumentation")
    assert cleared == "hypothesis"
    assert s.stage("hypothesis").status == "approved"
    workflow.ensure_can_run(s, "instrumentation")  # no longer blocked


def test_advance_into_blocks_when_predecessor_never_ran():
    s = WorkflowState.new("feat")  # hypothesis still pending
    with pytest.raises(workflow.GateError):
        workflow.advance_into(s, "instrumentation")


def test_advance_into_blocks_on_changes_requested():
    s = WorkflowState.new("feat")
    workflow.complete_stage(s, "hypothesis", [])
    workflow.request_changes(s, "hypothesis", note="redo")
    with pytest.raises(workflow.GateError):
        workflow.advance_into(s, "instrumentation")


def test_advance_into_noop_when_already_approved():
    s = WorkflowState.new("feat")
    workflow.complete_stage(s, "hypothesis", [], auto_yes=True)
    assert workflow.advance_into(s, "instrumentation") is None


def test_advance_into_defers_to_github_gate():
    s = WorkflowState.new("feat")
    workflow.complete_stage(s, "hypothesis", [])
    s.github = {"repo": "owner/repo", "approvers": {"product": "alice"}}
    s.stage("hypothesis").issue_number = 12
    with pytest.raises(workflow.GateError) as e:
        workflow.advance_into(s, "instrumentation")
    assert "#12" in str(e.value) and "sync" in str(e.value)
    assert s.stage("hypothesis").status == "awaiting_approval"  # not silently bypassed
