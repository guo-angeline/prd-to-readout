"""Smoke tests for the committed runnable examples, so they can't rot silently."""

import importlib.util
import subprocess
import sys
from pathlib import Path

EXAMPLES = Path(__file__).parent.parent / "examples"


def _load_generate():
    spec = importlib.util.spec_from_file_location("_p2r_generate", EXAMPLES / "_generate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_committed_examples_are_fresh(tmp_path, capsys):
    # The committed examples/sample_run/ must match what _generate.py produces, so
    # a code change that alters generated docs can't land without regenerating them.
    _load_generate().main(tmp_path)
    committed = EXAMPLES / "sample_run"
    stale = []
    for f in sorted(committed.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(committed)
        produced = tmp_path / rel
        if not produced.exists() or produced.read_text() != f.read_text():
            stale.append(str(rel))
    assert not stale, (
        "committed examples are out of date; run `python examples/_generate.py`: "
        + ", ".join(stale)
    )


def test_warehouse_source_demo_runs():
    # Runs exactly as the README documents: python examples/warehouse_source_demo.py
    res = subprocess.run(
        [sys.executable, str(EXAMPLES / "warehouse_source_demo.py")],
        capture_output=True, text=True,
    )
    assert res.returncode == 0, res.stderr
    assert "events into raw_events" in res.stdout
    assert "Driver: duckdb_demo" in res.stdout
