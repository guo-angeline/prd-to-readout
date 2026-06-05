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

### R1 — Real-data warehouse source ✅ COMPLETE (R1.1–R1.6, see Done log)

Shipped: shared `rows_to_events` contract, `WarehouseSource`, a pluggable driver
registry, an optional BigQuery driver, CLI wiring (`--warehouse-query`), and a
runnable no-external-services demo + docs. Next product theme is the user's call
(R3 segmentation and R5 CUPED/sequential both build on this real-data path).

### Hardening (now the active queue until a new theme is chosen)

- [ ] Optional planted lift on adoption metrics in `mockgen` so simulated
      previews show adoption movement, not a flat line. Keep it seeded + opt-in.
- [ ] Broaden example health coverage: add an `error_rate` (and/or `anr_rate`)
      health metric to `examples/_generate.py` and regenerate.
- [ ] Add a `CHANGELOG.md` and keep a terse entry per autonomous change.
- [ ] README: document the template-style metric plan (baseline->target,
      adoption metrics, power analysis, causal fallback).
- [ ] Pass over public functions missing docstrings/type hints; tighten where thin.

## Done log

(newest first)

- Hardening: `metric` CLI warns when the planned `users_per_arm` can't detect the
  target lift. New shared `power_shortfall()` helper (reuses `required_sample_size_rate`,
  refactors `_power_lines` to share baseline derivation); 4 unit tests. (iteration 10)
- Hardening: unit tests for `_power_lines` (no-baseline / underpowered / powered /
  primary-rate fallback / bias-mitigation) and `good_looks_like()` on mean+count
  metrics. Pure test coverage, no behavior change. (iteration 9)
- Hardening: `AnalyticsBlueprint` now rejects duplicate metric names across
  primary/adoption/guardrails (model_validator); collisions would silently break
  bindings + SQL. Test added. (iteration 8)
- R1.6: runnable `examples/warehouse_source_demo.py` (local DuckDB as a stand-in
  warehouse, no external services) + README warehouse docs. R1 COMPLETE. (iteration 7)
- R1.5: `verify-logging` gains `--warehouse-query` / `--warehouse-driver` /
  `--warehouse-project`, storing a warehouse source in state like `--source`
  does for files. CLI test via a registered fake driver. (iteration 6)
- R1.4: BigQuery driver (`adapters/warehouse_bigquery.py`) auto-registers the
  `bigquery` driver; `google-cloud-bigquery` is a lazy/optional import. Fake-client
  tests, no creds/network. (iteration 5)
- R1.3: `source_from_config` now builds a `WarehouseSource` for
  `kind=="warehouse"` via a pluggable driver registry
  (`register_warehouse_driver`); unknown driver raises a clear error.
  2 dispatch tests. (iteration 4)
- R1.2: added `WarehouseSource` (driver-agnostic, injected `fetch` callable,
  reuses `rows_to_events`). 3 fake-backed unit tests. (iteration 3)
- R1.1: extracted `rows_to_events` shared helper in `adapters/source.py`;
  `FileSource` now uses it. 3 helper unit tests added. (iteration 2)
- READOUT.md now has a "What Success Looks Like" section (quantitative + qualitative),
  rendered from the blueprint. Test added. (iteration 1)

## Parked (tried, reverted, why)

(none yet)
