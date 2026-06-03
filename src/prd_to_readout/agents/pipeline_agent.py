"""Module 3 - Self-Correcting Data Pipeline Builder.

The agent writes a DuckDB SQL statement that aggregates the raw event stream into
``metrics_daily``. If the SQL fails, the runtime traceback is fed back to the
model and the query is rewritten, up to ``max_attempts``. A deterministic
fallback (built from the metric bindings) guarantees the loop always produces a
working model, so the demo never dead-ends.
"""

from __future__ import annotations

from ..core.duckdb_runner import DuckDBRunner
from ..core.schemas import AnalyticsBlueprint, TrackingSchema
from ..llm import LLMClient, strip_code_fence
from ..prompts import PIPELINE_FIX, PIPELINE_SYSTEM


def _user_prompt(bp: AnalyticsBlueprint, schema: TrackingSchema) -> str:
    metrics = "\n".join(
        f"- {m.name} (type={m.type}): {m.formula}" for m in bp.all_metrics()
    )
    binds = "\n".join(
        f"- metric {b.metric_name}: kind={b.kind}, event={b.event_name}"
        + (f", value_property={b.value_property}" if b.value_property else "")
        for b in schema.bindings
    )
    return (
        f"Metrics to compute:\n{metrics}\n\n"
        f"How each maps to raw events:\n{binds}\n\n"
        "Write the CREATE OR REPLACE TABLE metrics_daily AS ... statement now."
    )


def _verify(runner: DuckDBRunner) -> str | None:
    """Confirm metrics_daily exists with the expected columns and some rows."""
    if not runner.table_exists("metrics_daily"):
        return "Statement ran but table `metrics_daily` was not created."
    cols = {r[0] for r in runner.query("DESCRIBE metrics_daily")}
    needed = {"metric_name", "arm", "day", "numerator", "denominator", "value"}
    missing = needed - {c.lower() for c in cols}
    if missing:
        return f"metrics_daily is missing required columns: {sorted(missing)}"
    if runner.query("SELECT count(*) FROM metrics_daily")[0][0] == 0:
        return "metrics_daily is empty; the aggregation matched no rows."
    return None


def build_metrics_model(
    runner: DuckDBRunner,
    bp: AnalyticsBlueprint,
    schema: TrackingSchema,
    llm: LLMClient,
    *,
    max_attempts: int = 3,
    console=None,
) -> tuple[str, int]:
    """Return (working_sql, attempts_used). Falls back to deterministic SQL."""
    user = _user_prompt(bp, schema)
    sql = strip_code_fence(llm.complete(PIPELINE_SYSTEM, user))
    for attempt in range(1, max_attempts + 1):
        err = runner.try_execute(sql) or _verify(runner)
        if err is None:
            return sql, attempt
        if console:
            console.print(f"  [yellow]attempt {attempt} failed:[/] {err.splitlines()[0][:90]}")
        if attempt == max_attempts:
            break
        sql = strip_code_fence(llm.complete(PIPELINE_SYSTEM, PIPELINE_FIX.format(error=err, sql=sql)))

    # Self-correction exhausted: use the deterministic model so the loop still ships.
    if console:
        console.print("  [yellow]falling back to deterministic SQL after retries[/]")
    sql = fallback_sql(bp, schema)
    runner.execute(sql)
    return sql, max_attempts


def fallback_sql(bp: AnalyticsBlueprint, schema: TrackingSchema) -> str:
    """Deterministic metrics_daily builder derived straight from the bindings."""
    selects: list[str] = []
    for b in schema.bindings:
        m, ev = b.metric_name, b.event_name
        if b.kind == "unique_user_conversion":
            num = f"count(DISTINCT CASE WHEN event_name='{ev}' THEN user_id END)"
            den = "count(DISTINCT user_id)"
        elif b.kind == "event_count":
            num = f"count(*) FILTER (WHERE event_name='{ev}')"
            den = "count(DISTINCT user_id)"
        else:  # numeric_mean
            prop = b.value_property or "value"
            cast = f"CAST(props->>'{prop}' AS DOUBLE)"
            num = f"sum({cast}) FILTER (WHERE event_name='{ev}')"
            den = f"count(*) FILTER (WHERE event_name='{ev}')"
        selects.append(
            f"SELECT '{m}' AS metric_name, arm, CAST(ts AS DATE) AS day, "
            f"{num} AS numerator, {den} AS denominator, "
            f"{num} * 1.0 / nullif({den}, 0) AS value "
            f"FROM raw_events GROUP BY arm, CAST(ts AS DATE)"
        )
    body = "\nUNION ALL\n".join(selects)
    return f"CREATE OR REPLACE TABLE metrics_daily AS\n{body};"
