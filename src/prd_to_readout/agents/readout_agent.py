"""The one-off Launch Readout (READOUT.md): the ship/kill/iterate decision document.

Generated once, at the launch-readout window (two weeks post-launch by default).
It owns all decision content: hypothesis result, primary/secondary metrics with
significance, guardrails vs thresholds, and the recommendation. The recurring
DAILY_PULSE.md is monitoring only; this is the call.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..core.provenance import RunContext
from ..core.schemas import AnalyticsBlueprint
from ..core.stats import StatResult
from ..llm import LLMClient
from ..prompts import READOUT_SYSTEM
from .report_agent import _results_digest, recommend


class ReadoutSections(BaseModel):
    tldr_outcome: str
    next_steps: list[str] = Field(default_factory=list)
    deep_dives: list[str] = Field(default_factory=list)
    rationale: str
    monitoring_plan: str


def _arrow(direction: str) -> str:
    return "⬆️" if direction == "increase" else "⬇️"


def _yn(r: StatResult) -> str:
    return "Y" if r.significant else "N"


def _primary_secondary_table(results: list[StatResult]) -> str:
    head = (
        "| Metric Name | Metric Type | Expected Direction | Observed Change (%) | P-Value | Stat. Sig? (Y/N) |\n"
        "| :---- | :---- | :---- | :---- | :---- | :---- |"
    )
    rows = []
    for r in results:
        if r.is_primary:
            mtype = "Success / North Star"
        elif r.direction == "increase":
            mtype = "Engagement / Upstream"
        else:
            continue  # decrease-direction metrics are counter-metrics; they go in the guardrail table
        rows.append(
            f"| **{r.metric_name}** | {mtype} | {_arrow(r.direction)} | "
            f"**{r.relative_lift * 100:+.1f}%** | *{r.effective_p:.3f}* | **{_yn(r)}** |"
        )
    return "\n".join([head, *rows])


def _guardrail_table(bp: AnalyticsBlueprint, results: list[StatResult]) -> str:
    head = (
        "| Guardrail Metric | Expected Max Threshold | Observed Change (%) | Impact / Action Taken |\n"
        "| :---- | :---- | :---- | :---- |"
    )
    rows = []
    for r in results:
        if r.is_primary or r.direction == "increase":
            continue
        if r.significant and not r.moved_favorably:
            action = f"ALERT: regressed (p={r.effective_p:.3f}); investigate before/after ship."
        elif r.moved_favorably:
            action = "Moved favorably; safe."
        else:
            action = f"Statistically flat (p={r.effective_p:.3f}); safe."
        rows.append(f"| **{r.metric_name}** | No increase | **{r.relative_lift * 100:+.1f}%** | {action} |")
    if not rows:
        rows = ["| _none defined_ |  |  |  |"]
    return "\n".join([head, *rows])


def _key_results(results: list[StatResult]) -> list[str]:
    out = []
    for r in results:
        if r.is_primary or r.direction == "increase":
            sig = "Statistically Significant" if r.significant else "Not Significant"
            out.append(f"  * **{r.metric_name}**: **{r.relative_lift * 100:+.1f}%** ({sig})")
    return out


def _banner(ctx: RunContext | None) -> list[str]:
    if ctx is None:
        return []
    if ctx.is_simulated:
        return ["> ⚠️ **SIMULATED PREVIEW**: this is a dry run on generated data to validate the "
                "readout format and spec, not a real launch decision.", ""]
    if not ctx.powered:
        return [f"> ⏳ **UNDERPOWERED**: {min(ctx.n_control, ctx.n_treatment)} users/arm, "
                f"need ~{ctx.required_n}. Treat the decision as provisional.", ""]
    return []


def generate_sections(bp: AnalyticsBlueprint, results: list[StatResult],
                      ctx: RunContext | None, llm: LLMClient) -> ReadoutSections:
    verdict, reason = recommend(bp, results, ctx)
    user = (
        f"Feature: {bp.feature_name}\nIntent: {bp.summary}\n"
        f"Hypothesis: if {bp.hypotheses.if_we or bp.summary}, then {bp.hypotheses.then_observe or bp.hypotheses.alternative}.\n"
        f"Computed verdict (use this): {verdict} - {reason}\n\n"
        f"Statistical results:\n{_results_digest(bp, results)}\n"
    )
    return llm.complete_json(READOUT_SYSTEM, user, ReadoutSections)


def assemble_readout(bp: AnalyticsBlueprint, results: list[StatResult], ctx: RunContext | None,
                     sections: ReadoutSections, *, date_label: str, window_label: str,
                     stakeholders: str) -> str:
    verdict, _ = recommend(bp, results, ctx)
    mde_pct = f"{bp.experiment.mde:.0%}"
    methodology = ""
    if ctx is not None:
        src = "simulated preview" if ctx.is_simulated else f"real events ({ctx.source_kind})"
        methodology = (f"Source: {src}; n={ctx.n_control}/{ctx.n_treatment}; α={ctx.alpha}; "
                       f"correction: {ctx.multiple_comparison}; PRD {ctx.prd_hash or 'n/a'}.")
    lines = [
        f"# {bp.feature_name}: Launch Readout",
        "",
        f"**Date:** {date_label}  ",
        "**Author(s):** prd-to-readout (generated)  ",
        f"**Stakeholders:** {stakeholders}  ",
        f"**Experiment/Launch Window:** {window_label}  ",
        f"**Decision Status:** {verdict}",
        "",
        *_banner(ctx),
        "### TL;DR (Too Long; Didn't Read)",
        "",
        f"* **The Outcome:** {sections.tldr_outcome}",
        "* **Key Results:**",
        *_key_results(results),
        f"* **Next Steps:** {'; '.join(sections.next_steps) or 'n/a'}",
        "",
        "### Context & Problem Statement",
        "",
        f"* **The Problem:** {bp.problem or bp.summary}",
        f"* **Strategic Alignment:** {bp.strategic_alignment or 'n/a'}",
        "",
        "### What's Shipped",
        "",
        f"* **Core Experience:** {bp.whats_shipped or bp.summary}",
        f"* **Scope & Audience:** {bp.scope_audience or f'{bp.experiment.treatment_split:.0%} treatment split'}",
        "",
        "### Hypothesis",
        "",
        f"* **If we:** {bp.hypotheses.if_we or bp.summary}",
        f"* **Then we will observe:** {bp.hypotheses.then_observe or bp.hypotheses.alternative}",
        f"* **Because:** {bp.hypotheses.because or 'n/a'}",
        f"* **Minimum Detectable Effect (MDE):** {mde_pct} relative lift at 80% power.",
        "",
        "### Metrics & Results",
        "",
        "#### 1. Primary & Secondary Metrics",
        "",
        _primary_secondary_table(results),
        "",
        "#### 2. Guardrail & Counter-Metrics",
        "",
        _guardrail_table(bp, results),
        "",
        "#### 3. Key Deep Dives & Segmentation",
        "",
        *([f"* {d}" for d in sections.deep_dives] or ["* No segmentation was computed for this readout."]),
        "",
        "### Decision: Ship / Kill / Iterate",
        "",
        f"* **Final Recommendation:** **{verdict}**",
        f"* **Data-Driven Rationale:** {sections.rationale}",
        f"* **Post-Launch Monitoring Plan:** {sections.monitoring_plan}",
        "",
        "---",
        f"*Generated by prd-to-readout. {methodology}*",
        "",
    ]
    return "\n".join(lines)


def generate_readout(bp: AnalyticsBlueprint, results: list[StatResult], ctx: RunContext | None,
                     llm: LLMClient, *, date_label: str, window_label: str,
                     stakeholders: str) -> str:
    sections = generate_sections(bp, results, ctx, llm)
    return assemble_readout(bp, results, ctx, sections, date_label=date_label,
                            window_label=window_label, stakeholders=stakeholders)
