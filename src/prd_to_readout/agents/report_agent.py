"""Module 4 - The "Pulse Readout" Engine.

Turns the statistical results into a DAILY_PULSE.md: a deterministic verdict +
metrics table + trend charts (so the numbers are never hallucinated), wrapped in
an LLM-written executive narrative.
"""

from __future__ import annotations

from ..core.provenance import RunContext
from ..core.schemas import AnalyticsBlueprint
from ..core.stats import StatResult
from ..llm import LLMClient
from ..prompts import REPORT_SYSTEM


def _fmt(metric_type: str, value: float) -> str:
    if metric_type == "rate":
        return f"{value * 100:.2f}%"
    # count / mean: thousands-separated, fixed decimals, never scientific notation.
    return f"{value:,.2f}"


def recommend(bp: AnalyticsBlueprint, results: list[StatResult],
              ctx: RunContext | None = None) -> tuple[str, str]:
    """Deterministic verdict. Only real, powered data earns SHIP/ITERATE/KILL."""
    if ctx is not None and not ctx.trustworthy_verdict:
        if ctx.is_simulated:
            return "PREVIEW", "Simulated data, not a measured result. Use to validate the spec, not to decide."
        return ("PREVIEW",
                f"Not yet powered: n={min(ctx.n_control, ctx.n_treatment)}/arm, "
                f"need ~{ctx.required_n}. Keep collecting before deciding.")

    primary = next((r for r in results if r.is_primary), results[0])
    guardrails = [r for r in results if not r.is_primary]
    harmed = [r for r in guardrails if r.significant and not r.moved_favorably]

    if primary.significant and not primary.moved_favorably:
        return "KILL", "Primary metric moved significantly the wrong way."
    if primary.beats_mde and primary.moved_favorably:
        if harmed:
            names = ", ".join(r.metric_name for r in harmed)
            return "ITERATE", f"Primary wins, but guardrail(s) regressed: {names}."
        return "SHIP", "Primary metric beat the MDE with significance and guardrails held."
    if primary.significant and primary.moved_favorably:
        return "ITERATE", "Primary is significant but below the minimum detectable effect."
    return "ITERATE", "Primary metric result is not yet conclusive; keep collecting data."


def _results_digest(bp: AnalyticsBlueprint, results: list[StatResult]) -> str:
    lines = []
    for r in results:
        tag = "PRIMARY" if r.is_primary else "guardrail"
        lines.append(
            f"[{tag}] {r.metric_name} ({r.metric_type}, good={r.direction}): "
            f"control={_fmt(r.metric_type, r.control_value)}, "
            f"treatment={_fmt(r.metric_type, r.treatment_value)}, "
            f"rel_lift={r.relative_lift * 100:+.1f}%, p={r.p_value:.4f}, "
            f"significant={r.significant}, beats_mde({r.mde})={r.beats_mde}, "
            f"moved_favorably={r.moved_favorably}"
        )
    return "\n".join(lines)


def generate_report(
    bp: AnalyticsBlueprint, results: list[StatResult], charts: str, llm: LLMClient,
    ctx: RunContext | None = None,
) -> str:
    verdict, reason = recommend(bp, results, ctx)
    framing = ""
    if ctx is not None and ctx.is_simulated:
        framing = ("\nIMPORTANT: this data is SIMULATED, not measured. Frame the writeup as a "
                   "preview that validates the metric/spec design. Do NOT claim the feature works "
                   "or recommend shipping based on these numbers.\n")
    elif ctx is not None and not ctx.powered:
        framing = ("\nIMPORTANT: the sample is underpowered. Frame results as preliminary and "
                   "avoid a confident verdict.\n")
    user = (
        f"Feature: {bp.feature_name}\nIntent: {bp.summary}\n"
        f"Hypotheses: H0 = {bp.hypotheses.null}; H1 = {bp.hypotheses.alternative}\n"
        f"{framing}\n"
        f"Statistical results:\n{_results_digest(bp, results)}\n\n"
        f"Computed verdict (use this): {verdict} - {reason}\n\n"
        f"Trend charts:\n{charts}\n"
    )
    return llm.complete(REPORT_SYSTEM, user)


def _metrics_table(results: list[StatResult]) -> str:
    head = (
        "| Metric | Role | Control | Treatment | Rel. lift | p (adj.) | Significant | Verdict |\n"
        "|---|---|---|---|---|---|---|---|"
    )
    rows = []
    for r in results:
        favor = "✅" if r.moved_favorably else "⚠️"
        rows.append(
            f"| `{r.metric_name}` | {'primary' if r.is_primary else 'guardrail'} "
            f"| {_fmt(r.metric_type, r.control_value)} | {_fmt(r.metric_type, r.treatment_value)} "
            f"| {r.relative_lift * 100:+.1f}% | {r.effective_p:.4f} "
            f"| {'yes' if r.significant else 'no'} | {favor} |"
        )
    return "\n".join([head, *rows])


def _banner_md(ctx: RunContext | None) -> list[str]:
    if ctx is None:
        return []
    if ctx.is_simulated:
        return ["> ⚠️ **SIMULATED PREVIEW**: these numbers are generated, not measured. "
                "For validating the metric and tracking design only, not for product decisions.", ""]
    if not ctx.powered:
        return [f"> ⏳ **ACCUMULATING**: {min(ctx.n_control, ctx.n_treatment)} users/arm so far, "
                f"need ~{ctx.required_n} to detect the {ctx.mde:.0%} MDE. Results not yet reliable.", ""]
    return ["> ✅ **Real data, adequately powered.**", ""]


def _methodology_md(bp: AnalyticsBlueprint, results: list[StatResult], ctx: RunContext | None) -> list[str]:
    if ctx is None:
        return []
    src = "simulated preview" if ctx.is_simulated else f"real events ({ctx.source_kind})"
    approvals = ", ".join(f"{k}: {v}" for k, v in ctx.approvals.items() if v) or "none recorded"
    return [
        "## Methodology & Assumptions",
        "",
        f"- **Data source:** {src}",
        f"- **Sample size:** control {ctx.n_control}, treatment {ctx.n_treatment} "
        f"(≈{ctx.required_n} per arm needed for the {ctx.mde:.0%} MDE at 80% power)",
        "- **Tests:** two-proportion z-test (rates), Welch's t-test (means/counts)",
        f"- **Significance:** α={ctx.alpha}, family-wise correction across "
        f"{len(results)} metrics via {ctx.multiple_comparison}",
        "- **Caveat, repeated looks:** scheduled re-runs are repeated significance tests "
        "(peeking), which inflate false positives. Treat a single day's significance cautiously.",
        f"- **Provenance:** generated {ctx.generated_at}, PRD `{ctx.prd_hash or 'n/a'}`; approvals: {approvals}",
        "",
    ]


def assemble(
    bp: AnalyticsBlueprint, results: list[StatResult], charts: str, narrative: str,
    ctx: RunContext | None = None,
) -> str:
    """Compose the final DAILY_PULSE.md from deterministic facts + LLM narrative."""
    verdict, reason = recommend(bp, results, ctx)
    badge = {"SHIP": "🟢", "ITERATE": "🟡", "KILL": "🔴", "PREVIEW": "⚪"}.get(verdict, "🟡")
    return "\n".join(
        [
            f"# 📊 Daily Pulse: {bp.feature_name}",
            "",
            f"> {bp.summary}",
            "",
            *_banner_md(ctx),
            f"## {badge} Verdict: **{verdict}**",
            "",
            reason,
            "",
            narrative.strip(),
            "",
            "## Metrics",
            "",
            _metrics_table(results),
            "",
            *_methodology_md(bp, results, ctx),
            "## Trends",
            "",
            "```",
            charts.rstrip(),
            "```",
            "",
            "---",
            f"*H0: {bp.hypotheses.null}*  ",
            f"*H1: {bp.hypotheses.alternative}*  ",
            "*Generated by [prd-to-readout](https://github.com/guo-angeline/prd-to-readout).*",
            "",
        ]
    )
