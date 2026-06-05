"""Module 1 - The Socratic Hypothesis & Metric Engine.

Reads a PRD (or a few interactive answers) and produces a validated
``AnalyticsBlueprint``: the primary metric, guardrails, hypotheses, and a clean
A/B experiment design.
"""

from __future__ import annotations

import json

from ..core.schemas import AnalyticsBlueprint
from ..llm import LLMClient
from ..prompts import HYPOTHESIS_SYSTEM

# The handful of questions that, answered, stand in for a PRD.
SOCRATIC_QUESTIONS = [
    ("feature", "What feature are you launching, in one sentence?"),
    ("action", "What is the core user action it should drive?"),
    ("counter", "What metric might it accidentally hurt (the counter-metric)?"),
    ("audience", "Who is the target user?"),
]


def _user_prompt(prd_text: str) -> str:
    schema = json.dumps(AnalyticsBlueprint.model_json_schema())
    return (
        f"PRD:\n\"\"\"\n{prd_text.strip()}\n\"\"\"\n\n"
        f"Produce the metric plan as JSON matching this schema:\n{schema}"
    )


def generate_blueprint(prd_text: str, llm: LLMClient) -> AnalyticsBlueprint:
    """Turn raw PRD markdown into a validated blueprint."""
    return llm.complete_json(HYPOTHESIS_SYSTEM, _user_prompt(prd_text), AnalyticsBlueprint)


_GOOD = {"increase": "higher is better", "decrease": "lower is better"}


def _metric_table(metrics, *, good_header: str = "What good looks like") -> list[str]:
    rows = [f"| Metric | Type | {good_header} | Definition |", "|---|---|---|---|"]
    for m in metrics:
        rows.append(f"| `{m.name}` | {m.type} | {m.good_looks_like()} | {m.description} |")
    return rows


def _rate_baseline(bp: AnalyticsBlueprint) -> float | None:
    """The control rate to power against: the explicit ``baseline_conversion``,
    else the primary metric's baseline when it is a rate. None if neither exists."""
    baseline = bp.experiment.baseline_conversion
    if baseline is None and bp.primary_metric.type == "rate":
        baseline = bp.primary_metric.baseline
    return baseline


def power_shortfall(bp: AnalyticsBlueprint) -> tuple[int, int] | None:
    """If the planned per-arm sample can't detect the MDE on the rate baseline,
    return ``(required, planned)``; else None (including when there's no baseline)."""
    baseline = _rate_baseline(bp)
    if baseline is None:
        return None
    from ..core.stats import required_sample_size_rate

    need = required_sample_size_rate(baseline, bp.experiment.mde)
    planned = bp.experiment.users_per_arm
    return (need, planned) if planned < need else None


def _power_lines(bp: AnalyticsBlueprint) -> list[str]:
    """Power-analysis summary: baseline conversion, MDE, required sample size."""
    exp = bp.experiment
    baseline = _rate_baseline(bp)
    out = [f"- **Minimum detectable effect:** {exp.mde:.0%} relative lift, 80% power, two-tailed at α=0.05."]
    if baseline is not None:
        out.append(f"- **Baseline conversion:** {baseline * 100:.1f}%.")
        try:
            from ..core.stats import required_sample_size_rate

            need = required_sample_size_rate(baseline, exp.mde)
            short = " (current plan may be underpowered)" if exp.users_per_arm < need else ""
            out.append(f"- **Required sample size:** ~{need:,} users per arm to detect that lift{short}.")
        except Exception:
            pass
    if exp.bias_mitigation:
        out.append(f"- **Bias & variance control:** {exp.bias_mitigation}")
    return out


def render_blueprint_doc(bp: AnalyticsBlueprint) -> str:
    """A friendly, readable version of the blueprint for a PM to review at the gate.

    Mirrors the product-analytics-plan template: overview + core hypothesis, what
    success looks like, the full metric framework (goal / adoption / guardrails /
    health), and the experiment + power analysis.
    """
    h = bp.hypotheses
    pm = bp.primary_metric
    lines = [
        f"# Metric Plan: {bp.feature_name}",
        "",
        f"> {bp.summary}",
        "",
        "_This is the plan we will measure against. If anything looks off, edit_ "
        "`metric_plan.yaml` _(the machine-readable file next to this one) and re-run_ "
        "`prd-to-readout metric`.",
        "",
        "## What we are building",
        "",
        f"- **What's shipped:** {bp.whats_shipped or bp.summary}",
        f"- **Who sees it:** {bp.scope_audience or f'{bp.experiment.treatment_split:.0%} in treatment'}",
        f"- **Why it matters:** {bp.problem or 'n/a'}",
    ]
    if bp.strategic_alignment:
        lines.append(f"- **Strategic fit:** {bp.strategic_alignment}")
    lines += [
        "",
        "## The bet",
        "",
        f"- **If we** {h.if_we or bp.summary}",
        f"- **Then we will see** {h.then_observe or h.alternative}",
        f"- **Because** {h.because or 'n/a'}",
        f"- **We can detect** a {bp.experiment.mde:.0%} relative change at 80% power.",
        "",
    ]

    if bp.success_qualitative or bp.success_quantitative:
        lines += ["## What success looks like", ""]
        if bp.success_quantitative:
            lines.append(f"- **By the numbers:** {bp.success_quantitative}")
        if bp.success_qualitative:
            lines.append(f"- **For users:** {bp.success_qualitative}")
        lines.append("")

    lines += [
        "## Primary metric (the one that decides ship or not)",
        "",
        f"**{pm.name}** ({pm.type}, {_GOOD.get(pm.direction, '')})",
        "",
        f"{pm.description}",
        "",
        f"_What good looks like:_ {pm.good_looks_like()}",
        "",
        f"_How it is computed:_ {pm.formula}",
        "",
    ]

    if bp.adoption_metrics:
        lines += ["## Adoption & engagement (is the feature being used?)", "",
                  "_Informational. These confirm reach and depth but do not gate the ship decision._",
                  ""]
        lines += _metric_table(bp.adoption_metrics, good_header="Target")
        lines.append("")

    if bp.guardrail_metrics:
        lines += ["## Guardrails (must not get worse)", ""]
        lines += _metric_table(bp.guardrail_metrics)
        lines.append("")

    if bp.health_metrics:
        lines += ["## Health to watch after launch", "",
                  "| Metric | Kind | Alert if above |", "|---|---|---|"]
        for hm in bp.health_metrics:
            unit = hm.unit or ""
            lines.append(f"| `{hm.name}` | {hm.kind} | {hm.threshold:g}{unit} |")
        lines.append("")

    exp = bp.experiment
    lines += [
        "## How we will test it",
        "",
        f"- {exp.control_arm} vs {exp.treatment_arm}, {exp.treatment_split:.0%} in treatment",
        f"- About {exp.users_per_arm:,} users per group, over {exp.horizon_days} days",
        *_power_lines(bp),
        "",
    ]

    if exp.causal:
        c = exp.causal
        lines += [
            "### If we cannot run a clean A/B test",
            "",
            f"- **Why not:** {c.challenge or 'n/a'}",
            f"- **Method:** {c.method}",
            f"- **Treatment vs control:** {c.treatment_units or 'n/a'} vs {c.control_units or 'n/a'}",
        ]
        if c.parallel_trends:
            lines.append(f"- **Parallel-trends check:** {c.parallel_trends}")
        lines.append("")

    ap = bp.approvers
    if ap.product or ap.engineering or ap.data_science:
        who = []
        if ap.product:
            who.append(f"Product @{ap.product}")
        if ap.engineering:
            who.append(f"Engineering @{ap.engineering}")
        if ap.data_science:
            who.append(f"Data Science @{ap.data_science}")
        lines += ["## Approvers", "", ", ".join(who), ""]

    lines += ["---", "*Generated by prd-to-readout from your PRD. "
              "Source of truth: metric_plan.yaml.*", ""]
    return "\n".join(lines)


def prd_from_answers(answers: dict[str, str]) -> str:
    """Synthesize a mini-PRD from Socratic survey answers."""
    lines = ["# Feature brief", "", answers.get("feature", "").strip(), ""]
    if answers.get("action"):
        lines += ["## Core user action", answers["action"].strip(), ""]
    if answers.get("counter"):
        lines += ["## Counter-metric to protect", answers["counter"].strip(), ""]
    if answers.get("audience"):
        lines += ["## Target users", answers["audience"].strip(), ""]
    return "\n".join(lines)
