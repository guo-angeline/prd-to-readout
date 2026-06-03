from prd_to_readout.agents import pipeline_agent
from prd_to_readout.core import charts, mockgen
from prd_to_readout.core.duckdb_runner import DuckDBRunner


def test_sparkline_maps_range():
    assert charts.sparkline([0, 1, 2], 0, 2) == "▁▅█"
    assert charts.sparkline([5, 5, 5], 5, 5) == "▁▁▁"  # flat -> lowest block
    assert charts.sparkline([], 0, 1) == ""


def test_render_all_covers_each_metric(blueprint, tracking):
    runner = DuckDBRunner(":memory:")
    runner.load_raw_events(mockgen.generate_events(blueprint, tracking, seed=42, effect=0.2))
    runner.execute(pipeline_agent.fallback_sql(blueprint, tracking))
    out = charts.render_all(runner, blueprint)
    assert "cart_conversion_rate" in out
    assert "order_cancellation_rate" in out
    assert "control" in out and "treatment" in out
    runner.close()
