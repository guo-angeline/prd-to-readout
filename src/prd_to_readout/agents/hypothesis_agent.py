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
        f"Produce the analytics blueprint as JSON matching this schema:\n{schema}"
    )


def generate_blueprint(prd_text: str, llm: LLMClient) -> AnalyticsBlueprint:
    """Turn raw PRD markdown into a validated blueprint."""
    return llm.complete_json(HYPOTHESIS_SYSTEM, _user_prompt(prd_text), AnalyticsBlueprint)


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
