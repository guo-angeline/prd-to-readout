"""Reproduce the committed example artifacts without calling a real LLM.

Drives the actual pipeline modules with canned model responses (blueprint,
tracking schema, SQL, narrative) so `examples/sample_run/` always reflects real
output. Run from the repo root:  python examples/_generate.py
"""

from __future__ import annotations

import json
from pathlib import Path

from prd_to_readout.agents import (
    hypothesis_agent,
    logging_agent,
    pipeline_agent,
    pulse_agent,
    readout_agent,
)
from prd_to_readout.agents.readout_agent import ReadoutSections
from prd_to_readout.core import charts, health, mockgen, stats
from prd_to_readout.core.duckdb_runner import DuckDBRunner
from prd_to_readout.core.provenance import build_run_context
from prd_to_readout.core.schemas import AnalyticsBlueprint, TrackingSchema

OUT = Path(__file__).parent / "sample_run"

BLUEPRINT_JSON = {
    "feature_name": "One-Tap Checkout",
    "summary": "Let returning customers place an order in a single tap, skipping the multi-screen flow.",
    "problem": "35% of returning users drop off at the payment step, re-entering details we already have.",
    "strategic_alignment": "Supports the Q2 goal of improving checkout funnel efficiency.",
    "whats_shipped": "A one-tap checkout button for returning users with a saved card, with a 5-second undo.",
    "scope_audience": "50/50 A/B on iOS and Android, returning US customers with a saved payment method.",
    "approvers": {"product": "octocat", "engineering": "hubot", "data_science": "octocat"},
    "health_metrics": [
        {"name": "p95_checkout_latency_ms", "kind": "latency", "unit": "ms", "threshold": 250.0},
        {"name": "crash_rate", "kind": "crash_rate", "unit": "%", "threshold": 1.0},
    ],
    "primary_metric": {
        "name": "cart_conversion_rate",
        "description": "Share of exposed carts that convert to a completed order.",
        "type": "rate",
        "formula": "distinct users who complete an order / distinct exposed users",
        "direction": "increase",
        "unit": "proportion",
    },
    "guardrail_metrics": [
        {
            "name": "order_cancellation_rate",
            "description": "Share of exposed users who cancel an order within the undo window.",
            "type": "rate",
            "formula": "distinct users who cancel / distinct exposed users",
            "direction": "decrease",
            "unit": "proportion",
        }
    ],
    "hypotheses": {
        "null": "One-Tap Checkout has no effect on cart conversion rate.",
        "alternative": "One-Tap Checkout increases cart conversion rate for returning customers.",
        "if_we": "give returning users a one-tap checkout that reuses their saved card and address",
        "then_observe": "more carts convert to paid orders, without more cancellations",
        "because": "we remove redundant friction for users who have already shared payment details",
    },
    "experiment": {
        "control_arm": "control",
        "treatment_arm": "treatment",
        "treatment_split": 0.5,
        "horizon_days": 14,
        "users_per_arm": 3000,
        "mde": 0.05,
    },
}

TRACKING_JSON = {
    "events": [
        {
            "name": "order_completed",
            "description": "Fired when a user completes payment for an order.",
            "properties": [{"name": "amount", "type": "number", "required": True,
                            "description": "Order total in USD."}],
        },
        {
            "name": "order_cancelled",
            "description": "Fired when a user cancels within the 5-second undo window.",
            "properties": [],
        },
    ],
    "bindings": [
        {"metric_name": "cart_conversion_rate", "event_name": "order_completed",
         "kind": "unique_user_conversion", "base_value": 0.32},
        {"metric_name": "order_cancellation_rate", "event_name": "order_cancelled",
         "kind": "unique_user_conversion", "base_value": 0.04},
    ],
}

SECTIONS = ReadoutSections(
    tldr_outcome="In this simulated dry run, conversion separates between arms as the spec intends; "
                 "real numbers will come from instrumented events.",
    next_steps=["Approve the blueprint", "Hand the logging spec to engineering",
                "Re-run the readout on real events at the 2-week window"],
    deep_dives=["No segmentation was computed for this preview; on real data, split by platform "
                "(iOS vs Android) and by new vs returning users."],
    rationale="This is a simulated preview, so the verdict stays a PREVIEW. It confirms the metric "
              "definitions and tracking spec are coherent before any code ships.",
    monitoring_plan="After launch, run the daily pulse to watch adoption and health (latency, "
                    "crashes) and generate this readout once two weeks of real data are in.",
)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    bp = AnalyticsBlueprint.model_validate(BLUEPRINT_JSON)
    tracking = TrackingSchema.model_validate(TRACKING_JSON)

    (OUT / "analytics_blueprint.yaml").write_text(bp.to_yaml())
    (OUT / "ANALYTICS_BLUEPRINT.md").write_text(hypothesis_agent.render_blueprint_doc(bp))
    (OUT / "tracking_schema.json").write_text(json.dumps(TRACKING_JSON, indent=2))
    snip = OUT / "snippets"
    snip.mkdir(exist_ok=True)
    for fname, content in logging_agent.render_snippets(tracking).items():
        (snip / fname).write_text(content)

    events = mockgen.generate_events(bp, tracking, seed=42, effect=0.15)
    runner = DuckDBRunner(":memory:")
    runner.load_raw_events(events)
    sql = pipeline_agent.fallback_sql(bp, tracking)
    runner.execute(sql)
    models = OUT / "models"
    models.mkdir(exist_ok=True)
    (models / "metrics_daily.sql").write_text(sql)

    results = stats.evaluate_all(runner, bp, tracking)
    stats.apply_holm(results)
    ctx = build_run_context(
        {"kind": "simulated", "seed": 42, "effect": 0.15}, results, bp,
        generated_at="2026-06-03T00:00:00+00:00", prd_hash="demo123",
        approvals={"hypothesis": "pm"},
    )
    chart_text = charts.render_all(runner, bp)
    runner.close()

    # READOUT.md: the one-off launch decision document.
    readout = readout_agent.assemble_readout(
        bp, results, ctx, SECTIONS,
        date_label="2026-01-15", window_label="2026-01-01 to 2026-01-15",
        stakeholders="PM, Eng, Data Science",
    )
    (OUT / "READOUT.md").write_text(readout)

    # DAILY_PULSE.md: the recurring adoption + health monitor.
    series = health.simulate_health(bp.health_metrics, horizon_days=bp.experiment.horizon_days, seed=42)
    alerts = health.detect_regressions(series, bp.health_metrics)
    pulse = pulse_agent.generate_pulse(bp, results, alerts, chart_text, ctx,
                                       generated_at="2026-01-15T00:00:00+00:00")
    (OUT / "DAILY_PULSE.md").write_text(pulse)

    print(f"Wrote example artifacts to {OUT}")
    print("\n===== READOUT.md =====\n")
    print(readout)
    print("\n===== DAILY_PULSE.md =====\n")
    print(pulse)


if __name__ == "__main__":
    main()
