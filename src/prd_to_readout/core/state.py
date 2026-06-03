"""Workflow state: the manifest that makes the pipeline stateful and resumable.

Each feature progresses through ordered stages, every one of which can sit at a
human gate. The manifest records where each stage is, who approved it, and what
artifacts it produced, so the CLI can refuse to run a stage before its
predecessor is approved and pick up exactly where it left off.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

StageStatus = Literal[
    "pending",            # not started
    "awaiting_approval",  # work done, waiting at the gate for a human
    "approved",           # gate passed
    "changes_requested",  # human asked for rework
    "done",               # terminal (e.g. readout produced)
]

# The lifecycle, in order. Each stage may only start once the prior one is
# approved/done. readout is the terminal output stage and is not gated.
STAGE_ORDER: list[str] = [
    "hypothesis",
    "instrumentation",
    "instrumentation_qa",
    "pipeline",
    "readout",
]

STAGE_TITLES = {
    "hypothesis": "Hypothesis & metrics",
    "instrumentation": "Instrumentation spec (engineer handoff)",
    "instrumentation_qa": "Instrumentation QA (events verified)",
    "pipeline": "Pipeline SQL (DS review)",
    "readout": "Launch readout (decision)",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class StageState(BaseModel):
    name: str
    status: StageStatus = "pending"
    approver: str | None = None
    note: str | None = None
    updated_at: str | None = None
    artifacts: list[str] = Field(default_factory=list)
    history: list[dict] = Field(default_factory=list)
    # GitHub-native gate: the issue tracking this stage's approval, if any.
    issue_number: int | None = None
    issue_url: str | None = None

    def record(self, action: str, *, by: str | None = None, note: str | None = None) -> None:
        self.updated_at = _now()
        self.history.append({"ts": self.updated_at, "action": action, "by": by, "note": note})


class WorkflowState(BaseModel):
    feature: str
    prd_path: str | None = None
    prd_hash: str | None = None
    # Launch date (ISO). The one-off launch readout opens window_days after this.
    launch_date: str | None = None
    readout_window_days: int = 14
    # Data source config, e.g. {"kind": "simulated", "seed": 42, "effect": 0.15}
    # or {"kind": "file", "path": "events.csv"}.
    source: dict = Field(default_factory=lambda: {"kind": "simulated"})
    # GitHub-native gates: {"repo": "owner/name", "approvers": {role: handle}}.
    github: dict | None = None
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)
    stages: dict[str, StageState] = Field(default_factory=dict)

    # -- construction ----------------------------------------------------- #
    @classmethod
    def new(cls, feature: str, prd_path: str | None = None, prd_hash: str | None = None) -> WorkflowState:
        return cls(
            feature=feature,
            prd_path=prd_path,
            prd_hash=prd_hash,
            stages={name: StageState(name=name) for name in STAGE_ORDER},
        )

    # -- persistence ------------------------------------------------------ #
    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.updated_at = _now()
        path.write_text(yaml.safe_dump(self.model_dump(), sort_keys=False, allow_unicode=True))

    @classmethod
    def load(cls, path: Path) -> WorkflowState:
        return cls.model_validate(yaml.safe_load(path.read_text()))

    @classmethod
    def load_or_new(cls, path: Path, feature: str) -> WorkflowState:
        if path.exists():
            return cls.load(path)
        return cls.new(feature)

    # -- accessors -------------------------------------------------------- #
    def stage(self, name: str) -> StageState:
        if name not in self.stages:  # tolerate manifests written by older versions
            self.stages[name] = StageState(name=name)
        return self.stages[name]
