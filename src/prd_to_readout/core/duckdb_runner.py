"""A thin DuckDB wrapper.

Holds the raw event stream and runs agent-authored SQL. ``try_execute`` returns
the error text instead of raising so the pipeline agent can feed tracebacks back
into the model and self-correct.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb

RAW_DDL = """
CREATE OR REPLACE TABLE raw_events (
    event_name VARCHAR,
    user_id    VARCHAR,
    arm        VARCHAR,
    ts         TIMESTAMP,
    props      JSON
);
"""


class DuckDBRunner:
    def __init__(self, path: Path | str = ":memory:"):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(str(path))

    def load_raw_events(self, events: list[dict[str, Any]]) -> None:
        """(Re)create the raw_events table and bulk-insert the event dicts."""
        self.con.execute(RAW_DDL)
        rows = [
            (e["event_name"], e["user_id"], e["arm"], e["ts"], json.dumps(e.get("props", {})))
            for e in events
        ]
        self.con.executemany(
            "INSERT INTO raw_events VALUES (?, ?, ?, ?, CAST(? AS JSON))", rows
        )

    def try_execute(self, sql: str) -> str | None:
        """Run a statement. Return None on success, or the error string on failure."""
        try:
            self.con.execute(sql)
            return None
        except (duckdb.Error, Exception) as e:  # noqa: BLE001 - feed any failure back to the LLM
            return f"{type(e).__name__}: {e}"

    def execute(self, sql: str) -> None:
        """Run a statement, raising on error (use try_execute to capture it instead)."""
        self.con.execute(sql)

    def query(self, sql: str) -> list[tuple]:
        """Run a query and return all rows as tuples."""
        return self.con.execute(sql).fetchall()

    def query_dicts(self, sql: str) -> list[dict[str, Any]]:
        """Run a query and return all rows as column-keyed dicts."""
        cur = self.con.execute(sql)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def table_exists(self, name: str) -> bool:
        """True if a table with the given name exists in the database."""
        rows = self.con.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [name]
        ).fetchall()
        return bool(rows and rows[0][0])

    def close(self) -> None:
        """Close the underlying DuckDB connection."""
        self.con.close()
