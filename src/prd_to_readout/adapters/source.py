"""Event sources: where the events analyzed by the readout come from.

`SimulatedSource` fabricates a labeled preview (the old behavior). `FileSource`
ingests REAL exported events (CSV / Parquet / JSON / JSONL) so the same pipeline
and stats run on actual product behavior. Both load into the same `raw_events`
table, so everything downstream is identical. Warehouse / Segment / Amplitude
sources implement the same `EventSource` protocol.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ..core.duckdb_runner import DuckDBRunner
from ..core.schemas import AnalyticsBlueprint, TrackingSchema

CANONICAL = ("event_name", "user_id", "arm", "ts")
_READERS = {
    ".csv": "read_csv_auto",
    ".parquet": "read_parquet",
    ".json": "read_json_auto",
    ".jsonl": "read_json_auto",
    ".ndjson": "read_json_auto",
}


def _extract_props(rec: dict, props_col: str | None, skip: set) -> dict:
    """Build the JSON `props` for one event: an explicit props column if present,
    otherwise any leftover (non-canonical) columns packed together."""
    if props_col is not None:
        val = rec.get(props_col)
        if isinstance(val, dict):
            return val
        if isinstance(val, str) and val.strip():
            try:
                return json.loads(val)
            except json.JSONDecodeError:
                return {"raw": val}
        return {}
    return {k: v for k, v in rec.items() if k not in skip and v is not None}


def rows_to_events(
    columns: Sequence[str], rows: Iterable[Sequence[Any]], mapping: dict | None = None
) -> list[dict]:
    """Map tabular rows (with their column names) to canonical raw_events records.

    Resolves each canonical field through `mapping` (identity by default), packs
    leftover columns into `props` (or parses an explicit `props` column), and
    raises if a required canonical column is absent. Shared by every file- and
    warehouse-backed `EventSource` so they agree on the row -> event contract.
    """
    mapping = mapping or {}

    def col(canonical: str) -> str:
        return mapping.get(canonical, canonical)

    missing = [c for c in CANONICAL if col(c) not in columns]
    if missing:
        need = ", ".join(col(c) for c in missing)
        raise ValueError(
            f"Events are missing required column(s): {need}. "
            f"Found columns: {', '.join(columns)}. Provide a column mapping if names differ."
        )

    props_col = col("props") if col("props") in columns else ("props" if "props" in columns else None)
    skip = {col(c) for c in CANONICAL} | ({props_col} if props_col else set())

    events = []
    for row in rows:
        rec = dict(zip(columns, row, strict=False))
        events.append({
            "event_name": rec[col("event_name")],
            "user_id": str(rec[col("user_id")]),
            "arm": str(rec[col("arm")]),
            "ts": rec[col("ts")],
            "props": _extract_props(rec, props_col, skip),
        })
    return events


@runtime_checkable
class EventSource(Protocol):
    kind: str

    def load(self, runner: DuckDBRunner) -> int:
        """Load events into raw_events; return the count."""

    def descriptor(self) -> dict: ...


class SimulatedSource:
    kind = "simulated"

    def __init__(self, blueprint: AnalyticsBlueprint, tracking: TrackingSchema, *,
                 seed: int, effect: float, adoption_effect: float = 0.0):
        self.blueprint, self.tracking, self.seed, self.effect = blueprint, tracking, seed, effect
        self.adoption_effect = adoption_effect

    def load(self, runner: DuckDBRunner) -> int:
        from ..core import mockgen

        events = mockgen.generate_events(
            self.blueprint, self.tracking, seed=self.seed, effect=self.effect,
            adoption_effect=self.adoption_effect,
        )
        runner.load_raw_events(events)
        return len(events)

    def descriptor(self) -> dict:
        d = {"kind": self.kind, "seed": self.seed, "effect": self.effect}
        if self.adoption_effect:  # keep flat-adoption descriptors backward-compatible
            d["adoption_effect"] = self.adoption_effect
        return d


class FileSource:
    kind = "file"

    def __init__(self, path: str | Path, mapping: dict | None = None):
        self.path = Path(path)
        self.mapping = mapping or {}

    def load(self, runner: DuckDBRunner) -> int:
        ext = self.path.suffix.lower()
        if ext not in _READERS:
            raise ValueError(f"Unsupported events file '{self.path.name}'. Use one of: {', '.join(_READERS)}")
        if not self.path.exists():
            raise FileNotFoundError(f"Events file not found: {self.path}")

        res = runner.con.execute(f"SELECT * FROM {_READERS[ext]}(?)", [str(self.path)])
        cols = [d[0] for d in res.description]
        events = rows_to_events(cols, res.fetchall(), self.mapping)
        runner.load_raw_events(events)
        return len(events)

    def descriptor(self) -> dict:
        return {"kind": self.kind, "path": str(self.path), "mapping": self.mapping}


class WarehouseSource:
    """Real events pulled from a warehouse query (BigQuery, Snowflake, ...).

    Driver-agnostic: it takes a `fetch` callable that returns
    ``(columns, rows)`` and maps those rows into `raw_events` through the shared
    `rows_to_events` contract. Concrete drivers (see R1.4) just supply a `fetch`
    that runs SQL; injecting it keeps this unit-testable with a fake, no network.
    """

    kind = "warehouse"

    def __init__(
        self,
        fetch: Callable[[], tuple[Sequence[str], Iterable[Sequence[Any]]]],
        *,
        mapping: dict | None = None,
        meta: dict | None = None,
    ):
        self.fetch = fetch
        self.mapping = mapping or {}
        self.meta = meta or {}

    def load(self, runner: DuckDBRunner) -> int:
        columns, rows = self.fetch()
        events = rows_to_events(columns, rows, self.mapping)
        runner.load_raw_events(events)
        return len(events)

    def descriptor(self) -> dict:
        return {"kind": self.kind, "mapping": self.mapping, **self.meta}


# Warehouse driver registry: name -> factory(source_config) -> fetch callable.
# Concrete drivers (e.g. BigQuery, R1.4) register here so `source_from_config`
# can build a WarehouseSource without importing any driver dependency.
_WAREHOUSE_DRIVERS: dict[str, Callable[[dict], Callable[[], tuple[Sequence[str], Iterable[Sequence[Any]]]]]] = {}


def register_warehouse_driver(
    name: str,
    factory: Callable[[dict], Callable[[], tuple[Sequence[str], Iterable[Sequence[Any]]]]],
) -> None:
    """Register a warehouse driver: `factory(source_config)` returns a `fetch`
    callable yielding `(columns, rows)`. Idempotent; last registration wins."""
    _WAREHOUSE_DRIVERS[name] = factory


def source_from_config(
    source: dict,
    blueprint: AnalyticsBlueprint,
    tracking: TrackingSchema,
    *,
    default_seed: int,
    default_effect: float,
) -> EventSource:
    """Build the configured EventSource from the workflow's stored source dict."""
    kind = (source or {}).get("kind", "simulated")
    if kind == "simulated":
        return SimulatedSource(
            blueprint, tracking,
            seed=int(source.get("seed", default_seed)),
            effect=float(source.get("effect", default_effect)),
            adoption_effect=float(source.get("adoption_effect", 0.0)),
        )
    if kind == "file":
        return FileSource(source["path"], source.get("mapping"))
    if kind == "warehouse":
        driver = source.get("driver", "")
        factory = _WAREHOUSE_DRIVERS.get(driver)
        if factory is None:
            known = ", ".join(sorted(_WAREHOUSE_DRIVERS)) or "none registered"
            raise ValueError(
                f"Unknown warehouse driver {driver!r}. Registered drivers: {known}."
            )
        return WarehouseSource(factory(source), mapping=source.get("mapping"),
                               meta={"driver": driver})
    raise ValueError(f"Unknown source kind: {kind!r}")


# Auto-register built-in warehouse drivers. Imported at the bottom so the registry
# and register_warehouse_driver above already exist. The driver modules import
# their heavy dependencies lazily, so this stays cheap and dependency-free.
from . import warehouse_bigquery as _warehouse_bigquery  # noqa: E402,F401
