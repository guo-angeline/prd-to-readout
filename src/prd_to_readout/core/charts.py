"""Compact, ANSI-free ASCII trend charts for the readout.

Reads the agent-built ``metrics_daily`` layer and renders one sparkline per arm
per metric, normalized across arms so the two lines are visually comparable. The
output embeds cleanly in both the terminal and DAILY_PULSE.md.
"""

from __future__ import annotations

from .duckdb_runner import DuckDBRunner
from .schemas import AnalyticsBlueprint

_BLOCKS = "▁▂▃▄▅▆▇█"


def sparkline(values: list[float], lo: float, hi: float) -> str:
    if not values:
        return ""
    span = hi - lo
    if span <= 0:
        return _BLOCKS[0] * len(values)
    out = []
    for v in values:
        idx = round((v - lo) / span * (len(_BLOCKS) - 1))
        out.append(_BLOCKS[min(max(idx, 0), len(_BLOCKS) - 1)])
    return "".join(out)


def _metric_chart(name: str, series: dict[str, list[tuple]]) -> str:
    """series: arm -> list of (day, value) sorted by day."""
    all_vals = [v for pts in series.values() for _, v in pts if v is not None]
    if not all_vals:
        return f"{name}: (no data)\n"
    lo, hi = min(all_vals), max(all_vals)
    width = max(len(a) for a in series)
    lines = [f"{name}  (by day, normalized {lo:.4g}–{hi:.4g})"]
    for arm, pts in sorted(series.items()):
        vals = [v for _, v in pts if v is not None]
        spark = sparkline(vals, lo, hi)
        first, last = (vals[0], vals[-1]) if vals else (0, 0)
        lines.append(f"  {arm:<{width}}  {spark}  {first:.4g} → {last:.4g}")
    return "\n".join(lines) + "\n"


def render_all(runner: DuckDBRunner, bp: AnalyticsBlueprint) -> str:
    if not runner.table_exists("metrics_daily"):
        return "(metrics_daily not built)"
    rows = runner.query(
        "SELECT metric_name, arm, day, value FROM metrics_daily ORDER BY metric_name, arm, day"
    )
    by_metric: dict[str, dict[str, list[tuple]]] = {}
    for metric_name, arm, day, value in rows:
        by_metric.setdefault(metric_name, {}).setdefault(arm, []).append((day, value))

    # Primary metric first, then guardrails in blueprint order.
    order = [m.name for m in bp.all_metrics()]
    chunks = [
        _metric_chart(name, by_metric[name])
        for name in order
        if name in by_metric
    ]
    return "\n".join(chunks)
