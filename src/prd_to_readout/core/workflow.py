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
