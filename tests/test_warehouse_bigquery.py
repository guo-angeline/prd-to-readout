"""BigQuery driver, tested with a fake client (no google lib, creds, or network)."""

from prd_to_readout.adapters import source, warehouse_bigquery
from prd_to_readout.core.duckdb_runner import DuckDBRunner


class _FakeField:
    def __init__(self, name):
        self.name = name


class _FakeRow:
    def __init__(self, values):
        self._values = values

    def values(self):
        return self._values


class _FakeResult:
    def __init__(self, columns, rows):
        self.schema = [_FakeField(c) for c in columns]
        self._rows = [_FakeRow(r) for r in rows]

    def __iter__(self):
        return iter(self._rows)


class _FakeJob:
    def __init__(self, result):
        self._result = result

    def result(self):
        return self._result


class _FakeClient:
    def __init__(self, columns, rows):
        self._result = _FakeResult(columns, rows)
        self.last_sql = None

    def query(self, sql):
        self.last_sql = sql
        return _FakeJob(self._result)


def test_bigquery_driver_is_registered():
    assert "bigquery" in source._WAREHOUSE_DRIVERS


def test_bigquery_fetch_maps_rows(monkeypatch):
    client = _FakeClient(
        ["event_name", "user_id", "arm", "ts", "amount"],
        [("buy", "u1", "treatment", "2026-01-01 10:00:00", 9.5)],
    )
    monkeypatch.setattr(warehouse_bigquery, "_client", lambda cfg: client)
    fetch = warehouse_bigquery.make_fetch({"query": "SELECT * FROM events"})
    columns, rows = fetch()
    assert columns == ["event_name", "user_id", "arm", "ts", "amount"]
    assert rows == [("buy", "u1", "treatment", "2026-01-01 10:00:00", 9.5)]
    assert client.last_sql == "SELECT * FROM events"


def test_bigquery_source_loads_into_raw_events(monkeypatch, blueprint, tracking):
    client = _FakeClient(
        ["event_name", "user_id", "arm", "ts", "amount"],
        [("buy", "u1", "treatment", "2026-01-01 10:00:00", 9.5),
         ("buy", "u2", "control", "2026-01-01 11:00:00", 12.0)],
    )
    monkeypatch.setattr(warehouse_bigquery, "_client", lambda cfg: client)
    src = source.source_from_config(
        {"kind": "warehouse", "driver": "bigquery", "query": "SELECT * FROM events",
         "project": "demo"},
        blueprint, tracking, default_seed=1, default_effect=0.1,
    )
    runner = DuckDBRunner(":memory:")
    assert src.load(runner) == 2
    val = runner.query("SELECT CAST(props->>'amount' AS DOUBLE) FROM raw_events WHERE user_id='u2'")
    assert val[0][0] == 12.0
    runner.close()
