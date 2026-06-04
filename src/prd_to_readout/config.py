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
class ModelStatus:
    """Whether the configured model is ready to use, in plain language."""

    model: str
    provider: str            # "Anthropic" | "OpenAI" | "Local (Ollama)" | "your provider"
    key_var: str | None      # env var to set, or None for local models
    key_present: bool        # is it set (or not needed)?
    is_local: bool
    help_url: str | None     # where to get a key


def model_status(model: str) -> ModelStatus:
    """Classify a LiteLLM model string and report whether its key is set.

    Call after Config.load() so the .env file has been loaded.
    """
    m = model.lower()
    if m.startswith("ollama/") or "ollama" in m:
        return ModelStatus(model, "Local (Ollama)", None, True, True, "https://ollama.com")
    if "claude" in m or m.startswith("anthropic/"):
        var = "ANTHROPIC_API_KEY"
        return ModelStatus(model, "Anthropic", var, bool(os.getenv(var)), False,
                           "https://console.anthropic.com/settings/keys")
    if m.startswith(("gpt", "o1", "o3", "openai/")) or "gpt-" in m:
        var = "OPENAI_API_KEY"
        return ModelStatus(model, "OpenAI", var, bool(os.getenv(var)), False,
                           "https://platform.openai.com/api-keys")
    # Unknown provider: don't block, let LiteLLM surface any auth error itself.
    return ModelStatus(model, "your provider", None, True, False, None)


@dataclass
class Paths:
    """Canonical artifact locations under a workspace root."""

    root: Path

    @property
    def blueprint(self) -> Path:
        return self.root / "metric_plan.yaml"

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
    def blueprint_doc(self) -> Path:
        return self.root / "METRIC_PLAN.md"

    @property
    def spec_doc(self) -> Path:
        return self.root / "LOGGING_SPEC.md"

    @property
    def qa_report(self) -> Path:
        return self.root / "LOGGING_QA.md"

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
