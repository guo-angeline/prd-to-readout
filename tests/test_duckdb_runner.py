from datetime import datetime

from prd_to_readout.core.duckdb_runner import DuckDBRunner


def test_load_raw_events_serializes_non_json_props():
    # A real events file can pack a datetime/Decimal extra column into props;
    # it must serialize (as a string) rather than crash json.dumps.
    runner = DuckDBRunner(":memory:")
    runner.load_raw_events(
        [
            {"event_name": "buy", "user_id": "u1", "arm": "control",
             "ts": "2026-01-01 10:00:00", "props": {"signup": datetime(2026, 1, 2, 3, 4, 5)}},
        ]
    )
    rows = runner.query("SELECT props->>'signup' FROM raw_events")
    assert rows[0][0] == "2026-01-02 03:04:05"
    runner.close()


def test_load_and_query_props_json():
    runner = DuckDBRunner(":memory:")
    runner.load_raw_events(
        [
            {"event_name": "buy", "user_id": "u1", "arm": "control",
             "ts": "2026-01-01 10:00:00", "props": {"amount": 9.5}},
        ]
    )
    rows = runner.query("SELECT CAST(props->>'amount' AS DOUBLE) FROM raw_events")
    assert rows[0][0] == 9.5
    runner.close()


def test_try_execute_success_returns_none():
    runner = DuckDBRunner(":memory:")
    assert runner.try_execute("SELECT 1") is None
    runner.close()


def test_try_execute_captures_error():
    runner = DuckDBRunner(":memory:")
    err = runner.try_execute("SELECT * FROM definitely_missing")
    assert err is not None
    assert "missing" in err.lower() or "Catalog" in err or "Error" in err
    runner.close()


def test_table_exists():
    runner = DuckDBRunner(":memory:")
    assert not runner.table_exists("foo")
    runner.execute("CREATE TABLE foo (a INT)")
    assert runner.table_exists("foo")
    runner.close()
