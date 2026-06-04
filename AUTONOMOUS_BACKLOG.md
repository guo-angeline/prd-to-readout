# Autonomous improvement loop

Shared state for the self-paced `/loop` and the scheduled routine. Both read this
file, pick ONE item, ship it, and update the log. Keep this file on the
`auto-improve` branch only (do not merge it to `main`).

## Operating rules (hard constraints)

1. Work ONLY on the `auto-improve` branch. Never commit to or push `main`. Never
   force-push. Never delete files you did not create.
2. One small, reversible improvement per iteration. Favor high-value, low-risk.
3. Before committing, BOTH must pass:
   - `.venv/bin/python -m pytest tests/ -q`
   - `.venv/bin/ruff check src/ tests/`
   If a change touches generated docs, regenerate: `.venv/bin/python examples/_generate.py`.
4. GREEN -> commit with a clear message + move the item to the Done log.
   RED and not quickly fixable -> `git checkout -- .` to discard, note it under
   "Parked", move on. Never commit a red tree.
5. Respect house style: no em dashes; punchy copy; warm/minimal for any UI.
6. Stay inside this repo. No deploys, no external posting, no destructive ops.
7. When the backlog runs dry, identify new improvements (read the code, tests,
   docs) and add them here before implementing.

## Backlog (pick from the top; reorder freely)

### R1 — Real-data warehouse source (TOP PRIORITY, build in order)

Goal: let a launch decision run on a live warehouse query, not just a file or the
simulated preview. The FILE path (`FileSource`, csv/parquet/json) already exists
and is wired to `--source`; do NOT rebuild it. This adds the WAREHOUSE half.

Build these increments in order, one per iteration, each test-gated:

- [ ] R1.3 Wire `source_from_config` to build a `WarehouseSource` for
      `kind == "warehouse"` (config carries the query + mapping + a driver name).
      Add a dispatch test. Keep simulated/file behavior unchanged.
- [ ] R1.4 BigQuery driver behind an OPTIONAL import (`google-cloud-bigquery`):
      a thin function that runs the configured SQL and yields rows for
      `WarehouseSource`. Guard the import so the package still works without it;
      unit-test with a fake client (no real creds/network). Document creds via env.
- [ ] R1.5 CLI: a way to point at a warehouse (e.g. `verify-logging --warehouse-query
      <sql> --warehouse-driver bigquery`) that stores the warehouse source in state,
      mirroring how `--source <file>` works today. Add a CLI test.
- [ ] R1.6 Docs + a runnable example (a tiny in-memory/duckdb "warehouse" fake) so
      `examples/` shows the warehouse path without external services.

### Hardening (background, lower priority)

- [ ] Add a model_validator to `AnalyticsBlueprint` rejecting duplicate metric
      names across primary/adoption/guardrails (collisions break bindings + SQL).
      Add a test.
- [ ] `metric` CLI: warn when `experiment.users_per_arm` is below the required
      sample size for the MDE + baseline (reuse `required_sample_size_rate`).
- [ ] Optional planted lift on adoption metrics in `mockgen` so simulated
      previews show adoption movement, not a flat line. Keep it seeded + opt-in.
- [ ] Broaden example health coverage: add an `error_rate` (and/or `anr_rate`)
      health metric to `examples/_generate.py` and regenerate.
- [ ] Unit tests for `_power_lines` (baseline present vs missing) and
      `good_looks_like()` on mean/count metrics.
- [ ] Add a `CHANGELOG.md` and keep a terse entry per autonomous change.
- [ ] README: document the template-style metric plan (baseline->target,
      adoption metrics, power analysis, causal fallback).
- [ ] Pass over public functions missing docstrings/type hints; tighten where thin.

## Done log

(newest first)

- R1.2: added `WarehouseSource` (driver-agnostic, injected `fetch` callable,
  reuses `rows_to_events`). 3 fake-backed unit tests. (iteration 3)
- R1.1: extracted `rows_to_events` shared helper in `adapters/source.py`;
  `FileSource` now uses it. 3 helper unit tests added. (iteration 2)
- READOUT.md now has a "What Success Looks Like" section (quantitative + qualitative),
  rendered from the blueprint. Test added. (iteration 1)

## Parked (tried, reverted, why)

(none yet)
