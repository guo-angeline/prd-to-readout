"""Smoke tests for the committed runnable examples, so they can't rot silently."""

import subprocess
import sys
from pathlib import Path

EXAMPLES = Path(__file__).parent.parent / "examples"


def test_warehouse_source_demo_runs():
    # Runs exactly as the README documents: python examples/warehouse_source_demo.py
    res = subprocess.run(
        [sys.executable, str(EXAMPLES / "warehouse_source_demo.py")],
        capture_output=True, text=True,
    )
    assert res.returncode == 0, res.stderr
    assert "events into raw_events" in res.stdout
    assert "Driver: duckdb_demo" in res.stdout
