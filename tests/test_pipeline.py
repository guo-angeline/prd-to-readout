from conftest import StubLLM

from prd_to_readout.agents import pipeline_agent
from prd_to_readout.core import mockgen
from prd_to_readout.core.duckdb_runner import DuckDBRunner


def _runner(blueprint, tracking):
    runner = DuckDBRunner(":memory:")
    runner.load_raw_events(
        mockgen.generate_events(blueprint, tracking, seed=42, effect=0.2)
    )
    return runner


def test_self_correction_recovers_after_bad_sql(blueprint, tracking):
    runner = _runner(blueprint, tracking)
    good_sql = pipeline_agent.fallback_sql(blueprint, tracking)
    llm = StubLLM(["SELECT * FROM table_that_does_not_exist", good_sql])

    sql, attempts = pipeline_agent.build_metrics_model(
        runner, blueprint, tracking, llm, max_attempts=3
    )
    assert attempts == 2
    assert runner.table_exists("metrics_daily")
    assert runner.query("SELECT count(*) FROM metrics_daily")[0][0] > 0
    runner.close()


def test_self_correction_rejects_wrong_shaped_table(blueprint, tracking):
    # SQL that EXECUTES but builds a metrics_daily missing required columns must
    # count as a failed attempt (via _verify) and be retried, not accepted.
    runner = _runner(blueprint, tracking)
    good_sql = pipeline_agent.fallback_sql(blueprint, tracking)
    llm = StubLLM(["CREATE OR REPLACE TABLE metrics_daily AS SELECT 1 AS wrong_col", good_sql])

    sql, attempts = pipeline_agent.build_metrics_model(
        runner, blueprint, tracking, llm, max_attempts=3
    )
    assert attempts == 2  # first ran but was wrong-shaped, second is correct
    cols = {r[0].lower() for r in runner.query("DESCRIBE metrics_daily")}
    assert {"metric_name", "arm", "day", "numerator", "denominator", "value"} <= cols
    runner.close()


def test_falls_back_to_deterministic_sql(blueprint, tracking):
    runner = _runner(blueprint, tracking)
    llm = StubLLM(["broken one", "broken two", "broken three"])

    sql, attempts = pipeline_agent.build_metrics_model(
        runner, blueprint, tracking, llm, max_attempts=3
    )
    assert attempts == 3
    assert sql == pipeline_agent.fallback_sql(blueprint, tracking)
    assert runner.table_exists("metrics_daily")
    runner.close()


def test_fallback_sql_executes_and_has_columns(blueprint, tracking):
    runner = _runner(blueprint, tracking)
    runner.execute(pipeline_agent.fallback_sql(blueprint, tracking))
    cols = {r[0].lower() for r in runner.query("DESCRIBE metrics_daily")}
    assert {"metric_name", "arm", "day", "numerator", "denominator", "value"} <= cols
    runner.close()
