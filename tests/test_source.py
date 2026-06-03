import pytest

from prd_to_readout.adapters import source
from prd_to_readout.core.duckdb_runner import DuckDBRunner


def _write_csv(path, text):
    path.write_text(text.strip() + "\n")
    return path


def test_filesource_packs_extra_columns_into_props(tmp_path):
    csv = _write_csv(tmp_path / "events.csv", """
event_name,user_id,arm,ts,amount
order_completed,u1,treatment,2026-01-01 10:00:00,9.5
order_completed,u2,control,2026-01-01 11:00:00,12.0
""")
    runner = DuckDBRunner(":memory:")
    n = source.FileSource(csv).load(runner)
    assert n == 2
    val = runner.query("SELECT CAST(props->>'amount' AS DOUBLE) FROM raw_events WHERE user_id='u1'")
    assert val[0][0] == 9.5
    runner.close()


def test_filesource_explicit_props_json_column(tmp_path):
    csv = _write_csv(tmp_path / "e.csv", """
event_name,user_id,arm,ts,props
buy,u1,control,2026-01-01 10:00:00,"{""amount"": 7.0}"
""")
    runner = DuckDBRunner(":memory:")
    source.FileSource(csv).load(runner)
    val = runner.query("SELECT CAST(props->>'amount' AS DOUBLE) FROM raw_events")
    assert val[0][0] == 7.0
    runner.close()


def test_filesource_missing_required_column_raises(tmp_path):
    csv = _write_csv(tmp_path / "bad.csv", """
event_name,user_id,ts
order_completed,u1,2026-01-01 10:00:00
""")
    runner = DuckDBRunner(":memory:")
    with pytest.raises(ValueError, match="arm"):
        source.FileSource(csv).load(runner)
    runner.close()


def test_filesource_column_mapping(tmp_path):
    csv = _write_csv(tmp_path / "m.csv", """
event,uid,variant,time,amount
order_completed,u1,treatment,2026-01-01 10:00:00,3.0
""")
    runner = DuckDBRunner(":memory:")
    mapping = {"event_name": "event", "user_id": "uid", "arm": "variant", "ts": "time"}
    n = source.FileSource(csv, mapping=mapping).load(runner)
    assert n == 1
    assert runner.query("SELECT arm FROM raw_events")[0][0] == "treatment"
    runner.close()


def test_source_from_config_dispatch(blueprint, tracking, tmp_path):
    sim = source.source_from_config({"kind": "simulated"}, blueprint, tracking, default_seed=1, default_effect=0.1)
    assert isinstance(sim, source.SimulatedSource)
    f = source.source_from_config({"kind": "file", "path": "x.csv"}, blueprint, tracking, default_seed=1, default_effect=0.1)
    assert isinstance(f, source.FileSource)
    with pytest.raises(ValueError):
        source.source_from_config({"kind": "warehouse"}, blueprint, tracking, default_seed=1, default_effect=0.1)
