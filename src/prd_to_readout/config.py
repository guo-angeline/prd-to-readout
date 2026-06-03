"""Runtime configuration and the canonical layout of generated artifacts.

Everything the tool writes lives at predictable paths relative to a workspace
directory (default: the current directory). Headline artifacts sit at the root
so they're visible in a repo; bulky data lives in a hidden ``.pulse/`` folder.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_SEED = 42


@dataclass
class Paths:
    """Canonical artifact locations under a workspace root."""

    root: Path

    @property
    def blueprint(self) -> Path:
        return self.root / "analytics_blueprint.yaml"

    @property
    def tracking_schema(self) -> Path:
        return self.root / "tracking_schema.json"

    @property
    def report(self) -> Path:
        return self.root / "DAILY_PULSE.md"

    @property
    def readout_doc(self) -> Path:
        return self.root / "READOUT.md"

    @property
    def spec_doc(self) -> Path:
        return self.root / "LOGGING_SPEC.md"

    @property
    def qa_report(self) -> Path:
        return self.root / "INSTRUMENTATION_QA.md"

    @property
    def state(self) -> Path:
        return self.pulse_dir / "state.yaml"

    @property
    def models_dir(self) -> Path:
        return self.root / "models"

    @property
    def snippets_dir(self) -> Path:
        return self.root / "snippets"

    @property
    def pulse_dir(self) -> Path:
        return self.root / ".pulse"

    @property
    def db(self) -> Path:
        return self.pulse_dir / "pulse.duckdb"

    @property
    def feedback(self) -> Path:
        return self.pulse_dir / "feedback.jsonl"

    def ensure(self) -> None:
        for d in (self.root, self.models_dir, self.snippets_dir, self.pulse_dir):
            d.mkdir(parents=True, exist_ok=True)


@dataclass
class Config:
    model: str = DEFAULT_MODEL
    seed: int = DEFAULT_SEED
    workdir: Path = field(default_factory=Path.cwd)
    max_fix_attempts: int = 3
    # Simulated lift baked into mock data, as a relative fraction on the primary
    # metric (0.15 = treatment is 15% better). Keeps the demo's significance real.
    effect_size: float = 0.15

    @property
    def paths(self) -> Paths:
        return Paths(self.workdir)

    @classmethod
    def load(cls, workdir: Path | None = None, model: str | None = None,
             seed: int | None = None) -> Config:
        """Build a Config from .env + environment, with explicit overrides winning."""
        load_dotenv()
        return cls(
            model=model or os.getenv("P2R_MODEL", DEFAULT_MODEL),
            seed=seed if seed is not None else int(os.getenv("P2R_SEED", DEFAULT_SEED)),
            workdir=workdir or Path.cwd(),
        )
