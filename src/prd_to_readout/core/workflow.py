"""The stage graph and gate rules that drive the workflow.

Gated by default: a stage's work runs, then it parks at ``awaiting_approval``
until a human approves (or ``--yes`` auto-approves). A stage cannot start until
its predecessor is approved/done. ``readout`` is the terminal output and is not
gated.
"""

from __future__ import annotations

from .state import STAGE_ORDER, WorkflowState

# Every stage except the terminal readout waits at a human gate by default.
GATED_STAGES = {"hypothesis", "instrumentation", "instrumentation_qa", "pipeline"}

PASSED = {"approved", "done"}


class GateError(RuntimeError):
    """Raised when a stage is run out of order (its predecessor isn't approved)."""


def predecessor(stage: str) -> str | None:
    i = STAGE_ORDER.index(stage)
    return STAGE_ORDER[i - 1] if i > 0 else None


def successor(stage: str) -> str | None:
    i = STAGE_ORDER.index(stage)
    return STAGE_ORDER[i + 1] if i + 1 < len(STAGE_ORDER) else None


def ensure_can_run(state: WorkflowState, stage: str) -> None:
    """Raise GateError unless the prior stage has cleared its gate."""
    prev = predecessor(stage)
    if prev is None:
        return
    status = state.stage(prev).status
    if status not in PASSED:
        raise GateError(
            f"Cannot run '{stage}': '{prev}' is '{status}'. "
            f"Approve it first with: prd-to-readout approve {prev}"
        )


def advance_into(state: WorkflowState, stage: str) -> str | None:
    """Clear the predecessor's gate by virtue of moving on to ``stage``.

    Running a stage is itself the approval of the one before it: if the
    predecessor is parked at ``awaiting_approval``, this approves it and returns
    its name. Returns ``None`` when there is nothing to clear (no predecessor, or
    it already passed). Raises ``GateError`` when the predecessor genuinely blocks
    ``stage``:

    - it never ran (``pending``): run it first;
    - it needs rework (``changes_requested``): re-run it;
    - it is a live GitHub gate (an open issue): that approval belongs in GitHub,
      so clear it there and ``sync`` rather than silently bypassing the audit trail.
    """
    prev = predecessor(stage)
    if prev is None:
        return None
    st = state.stage(prev)
    if st.status in PASSED:
        return None
    if st.status == "awaiting_approval":
        if state.github and st.issue_number:
            raise GateError(
                f"'{prev}' is awaiting approval in GitHub issue #{st.issue_number}. "
                f"Approve it there, then run 'prd-to-readout sync' before '{stage}'."
            )
        approve(state, prev, by=f"advancing to {stage}",
                note="approved implicitly by moving on to the next stage")
        return prev
    if st.status == "changes_requested":
        raise GateError(
            f"Cannot run '{stage}': '{prev}' has changes requested. "
            f"Re-run it first: prd-to-readout {_stage_cmd(prev)}"
        )
    raise GateError(
        f"Cannot run '{stage}': '{prev}' hasn't run yet. "
        f"Run it first: prd-to-readout {_stage_cmd(prev)}"
    )


def complete_stage(
    state: WorkflowState,
    stage: str,
    artifacts: list[str],
    *,
    auto_yes: bool = False,
) -> str:
    """Mark a stage's work finished. Returns the resulting status.

    Gated stages land at ``awaiting_approval`` (or ``approved`` if ``auto_yes``);
    the terminal readout lands at ``done``.
    """
    st = state.stage(stage)
    st.artifacts = artifacts
    if stage not in GATED_STAGES:
        st.status = "done"
        st.record("completed")
    elif auto_yes:
        st.status = "approved"
        st.approver = "--yes"
        st.record("auto-approved")
    else:
        st.status = "awaiting_approval"
        st.record("awaiting_approval")
    return st.status


def approve(state: WorkflowState, stage: str, *, by: str | None = None, note: str | None = None) -> None:
    st = state.stage(stage)
    st.status = "approved"
    st.approver = by
    st.note = note
    st.record("approved", by=by, note=note)


def request_changes(state: WorkflowState, stage: str, *, by: str | None = None, note: str | None = None) -> None:
    st = state.stage(stage)
    st.status = "changes_requested"
    st.note = note
    st.record("changes_requested", by=by, note=note)


def next_action(state: WorkflowState) -> str:
    """Human-readable hint for what to do next."""
    for stage in STAGE_ORDER:
        st = state.stage(stage)
        if st.status == "awaiting_approval":
            if state.github and st.issue_number:
                return (f"Approve '{stage}' in GitHub issue #{st.issue_number}, "
                        f"then: prd-to-readout sync")
            nxt = successor(stage)
            if nxt:
                return (f"Review '{stage}', then run the next stage to approve it and continue: "
                        f"prd-to-readout {_stage_cmd(nxt)}")
            return f"Review and approve '{stage}': prd-to-readout approve {stage}"
        if st.status == "changes_requested":
            return f"Rework '{stage}', then re-run that stage."
        if st.status == "pending":
            prev = predecessor(stage)
            if prev is None or state.stage(prev).status in PASSED:
                return f"Run '{stage}': prd-to-readout {_stage_cmd(stage)}"
            return f"Waiting on '{prev}'."
    return "Workflow complete. Re-run 'readout' anytime to refresh."


def _stage_cmd(stage: str) -> str:
    return {
        "hypothesis": "hypothesize <prd>",
        "instrumentation": "spec",
        "instrumentation_qa": "verify-instrumentation",
        "pipeline": "build",
        "readout": "readout",
    }[stage]
