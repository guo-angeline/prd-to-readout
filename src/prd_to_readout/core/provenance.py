"""RunContext: the honesty layer.

Captures *how* a readout was produced (real vs simulated data, sample size vs
required, alpha, corrections, approvals) so the report can label itself truthfully
and the verdict can be gated. Without this, a simulated or underpowered run looks
identical to a real, conclusive one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import stats
from .schemas import AnalyticsBlueprint
from .stats import StatResult


@dataclass
class RunContext:
    source_kind: str            # "simulated" | "file" | ...
    n_control: int
    n_treatment: int
    required_n: int
    alpha: float
    mde: float
    multiple_comparison: str
    generated_at: str
    prd_hash: str | None = None
    approvals: dict = field(default_factory=dict)

    @property
    def is_simulated(self) -> bool:
        """True if the run was driven by simulated data rather than a real source."""
        return self.source_kind == "simulated"

    @property
    def powered(self) -> bool:
        """True if each arm met the required sample size (or none was computable)."""
        return self.required_n == 0 or min(self.n_control, self.n_treatment) >= self.required_n

    @property
    def trustworthy_verdict(self) -> bool:
        """Only real, adequately powered data earns a hard SHIP/ITERATE/KILL."""
        return not self.is_simulated and self.powered


def build_run_context(
    state_source: dict,
    results: list[StatResult],
    bp: AnalyticsBlueprint,
    *,
    generated_at: str,
    prd_hash: str | None = None,
    approvals: dict | None = None,
    alpha: float = stats.ALPHA,
) -> RunContext:
    """Assemble the honesty layer from the run's source, results, and approvals.

    Reads the primary metric's arm sizes and, for a rate primary, the sample size
    its baseline + MDE require, so the readout can label itself and gate the
    verdict on real, adequately powered data.
    """
    primary = next((r for r in results if r.is_primary), results[0] if results else None)
    n_c = primary.n_control if primary else 0
    n_t = primary.n_treatment if primary else 0
    required = 0
    if primary and primary.metric_type == "rate":
        required = stats.required_sample_size_rate(primary.control_value, bp.experiment.mde, alpha=alpha)
    return RunContext(
        source_kind=(state_source or {}).get("kind", "simulated"),
        n_control=n_c,
        n_treatment=n_t,
        required_n=required,
        alpha=alpha,
        mde=bp.experiment.mde,
        multiple_comparison="Holm-Bonferroni",
        generated_at=generated_at,
        prd_hash=prd_hash,
        approvals=approvals or {},
    )
