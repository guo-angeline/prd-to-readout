"""BigQuery warehouse driver (optional).

Registers a `bigquery` warehouse driver so a launch readout can run on a live
BigQuery query. `google-cloud-bigquery` is an OPTIONAL dependency: it is imported
lazily inside `_client`, only when a query actually runs, so importing this module
(and the package) never requires the library to be installed.

Config shape (stored in the workflow's `source` dict):
    {"kind": "warehouse", "driver": "bigquery", "query": "SELECT ...",
     "project": "my-gcp-project", "mapping": {...}}
The query must return the canonical columns (event_name, user_id, arm, ts) plus
any extra columns, which get packed into `props`.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from .source import register_warehouse_driver


def _client(cfg: dict):
    """Build a BigQuery client. Lazy import keeps the dependency optional."""
    try:
        from google.cloud import bigquery
    except ImportError as e:  # pragma: no cover - exercised only without the extra
        raise RuntimeError(
            "The 'bigquery' warehouse driver needs google-cloud-bigquery. "
            "Install it with: pip install google-cloud-bigquery"
        ) from e
    return bigquery.Client(project=cfg.get("project"))


def make_fetch(cfg: dict):
    """Driver factory: return a `fetch()` that runs cfg['query'] on BigQuery and
    yields `(columns, rows)` for `WarehouseSource`."""
    query = cfg["query"]

    def fetch() -> tuple[Sequence[str], Iterable[Sequence[Any]]]:
        result = _client(cfg).query(query).result()
        columns = [field.name for field in result.schema]
        rows = [tuple(row.values()) for row in result]
        return columns, rows

    return fetch


register_warehouse_driver("bigquery", make_fetch)
