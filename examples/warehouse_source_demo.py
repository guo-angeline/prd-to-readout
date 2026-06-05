"""Runnable demo: drive the warehouse EventSource end to end with NO external services.

A local in-memory DuckDB stands in for a real warehouse (BigQuery / Snowflake /
Postgres). We register a tiny driver that runs the configured SQL against it, then
let `source_from_config` build a `WarehouseSource` and load the events into the
pipeline exactly as a real warehouse would.

Run from the repo root:  python examples/warehouse_source_demo.py
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from prd_to_readout.adapters import source
from prd_to_readout.core import mockgen
from prd_to_readout.core.duckdb_runner import DuckDBRunner
from prd_to_readout.core.schemas import AnalyticsBlueprint, TrackingSchema

SAMPLE = Path(__file__).parent / "sample_run"


def main() -> None:
    # Reuse the committed example plan + tracking spec.
    bp = AnalyticsBlueprint.from_yaml((SAMPLE / "metric_plan.yaml").read_text())
    tracking = TrackingSchema.model_validate_json((SAMPLE / "tracking_schema.json").read_text())

    # Stand up a local DuckDB that plays the role of the warehouse.
    events = mockgen.generate_events(bp, tracking, seed=42, effect=0.15)
    warehouse = duckdb.connect()
    warehouse.execute(
        "CREATE TABLE events (event_name VARCHAR, user_id VARCHAR, arm VARCHAR, ts TIMESTAMP, props JSON)"
    )
    warehouse.executemany(
        "INSERT INTO events VALUES (?, ?, ?, ?, ?)",
        [(e["event_name"], e["user_id"], e["arm"], e["ts"], json.dumps(e["props"])) for e in events],
    )

    # A driver is just: factory(config) -> fetch() -> (columns, rows).
    def duckdb_driver(cfg: dict):
        def fetch():
            res = warehouse.execute(cfg["query"])
            return [d[0] for d in res.description], res.fetchall()
        return fetch

    source.register_warehouse_driver("duckdb_demo", duckdb_driver)

    # This config is exactly what `verify-logging --warehouse-query ...` stores in state.
    src = source.source_from_config(
        {"kind": "warehouse", "driver": "duckdb_demo", "query": "SELECT * FROM events"},
        bp, tracking, default_seed=0, default_effect=0.0,
    )

    runner = DuckDBRunner(":memory:")
    n = src.load(runner)
    distinct_events = runner.query("SELECT count(DISTINCT event_name) FROM raw_events")[0][0]
    arms = runner.query("SELECT count(DISTINCT arm) FROM raw_events")[0][0]
    runner.close()

    print(f"Driver: {src.descriptor()['driver']}")
    print(f"Loaded {n} events into raw_events ({distinct_events} event types, {arms} arms).")
    print("The rest of the pipeline (QA, SQL, stats, readout) runs identically to the file source.")


if __name__ == "__main__":
    main()
