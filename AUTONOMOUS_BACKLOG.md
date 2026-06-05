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
4. GREEN -> commit with a clear message + move the item to the Done log + add a
   terse entry under "Unreleased" in `CHANGELOG.md`.
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

- [ ] Power-gating only works for rate primaries: `build_run_context` computes
      `required_n` only when the primary metric is a rate, so a mean/count-primary
      experiment has `required_n=0` and is treated as always-powered, earning a hard
      verdict even when underpowered. Add a mean/count sample-size path (needs a
      baseline std / effect-size assumption) or label such verdicts as not power-gated.

## Done log

(newest first)

- Hardening: test for the terminal "not yet conclusive" ITERATE branch of
  `recommend()` (primary not significant). All five verdict branches now covered.
  (iteration 31)
- Hardening: test for the `pipeline_agent._verify` recovery branch, SQL that
  executes but yields a wrong-shaped `metrics_daily` is retried, not accepted.
  (iteration 30)
- Hardening: schema now validates SQL-interpolated names (metric/event names,
  value properties) as safe snake_case identifiers, so a malformed or injection-y
  name is rejected at the boundary instead of breaking the generated SQL. Test
  added. (iteration 29)
- Bugfix: `MultiNotifier.send` used `all(generator)`, which short-circuited and
  skipped every channel after one that returned False (a Slack outage silently
  dropped the email handoff). Now sends to all channels, then aggregates. Test added.
  (iteration 28)
- Hardening: the logging-QA "both arms have users" check now lists the arm labels
  actually present when the expected control/treatment labels are missing, so a
  real-file arm-naming mismatch is obvious instead of a bare "0, 0". Test added.
  (iteration 27)
- Hardening: single-sourced the package version. `pyproject.toml` now uses
  hatchling's dynamic version from `__init__.py`'s `__version__`, so the build,
  the CLI `version` command, and `__version__` can no longer drift. Wheel build
  verified at 0.1.0. (iteration 26)
- Bugfix: `DuckDBRunner.load_raw_events` crashed (`TypeError`) when `props` held a
  datetime/Decimal, which happens when a real events file packs a timestamp/decimal
  extra column into props. Now serializes via `json.dumps(default=str)`. Test added.
  (iteration 25)
- Hardening: `FileSource.load` checks file existence before the extension, so a
  mistyped path reports "not found" rather than complaining about the suffix.
  Added tests for the not-found and unsupported-extension branches. (iteration 24)
- Hardening: added a PEP 561 `py.typed` marker so the package's type hints are
  used by downstream type checkers. Verified it ships in the built wheel. (iteration 23)
- Hardening: end-to-end tests for `stats.evaluate_metric` on `count` and `mean`
  metrics (per-user aggregation SQL + `numeric_mean` value_property), recovering a
  mockgen-planted lift. Previously only `rate` was covered. (iteration 22)
- Hardening: docstrings for the `agents/*` entry points (`generate_tracking_schema`,
  `generate_pulse`, `generate_sections`, `assemble_readout`, `generate_readout`,
  `generate_report`). Completes the per-module docstring pass. Docs only. (iteration 21)
- Hardening: docstrings for `core/provenance.py` public surface (`build_run_context`,
  `RunContext.is_simulated`/`powered`). Docs only. (iteration 20)
- Hardening: docstrings for `core/duckdb_runner.py` public methods (`load_raw_events`,
  `execute`, `query`, `query_dicts`, `table_exists`, `close`). Docs only. (iteration 19)
- Hardening: docstrings for `core/logging_qa.py` public surface (`run_qa`,
  `render_qa_report`, and `QAReport.passed`/`warnings`). Docs only. (iteration 18)
- Hardening: docstrings for `core/health.py` public surface (`detect_regressions`,
  `overall_status`). Docs only, no behavior change. (iteration 17)
- Hardening: docstrings for the public surface of `core/stats.py` (`evaluate_metric`,
  `evaluate_all`, and the `StatResult` decision flags `significant`/`moved_favorably`/
  `beats_mde`/`as_dict`). Docs only, no behavior change. (iteration 16)
- Hardening: `--adoption-effect` flag on `run` and `verify-logging` (and
  `Config.adoption_effect_size`) exposes the iteration-11 mockgen adoption lift;
  stored in the simulated source dict only when non-zero. Test added. (iteration 15)
- Hardening: README gains a "The metric plan" section (baseline->target, adoption
  metrics, power analysis, causal fallback). The causal/quasi-experimental fallback
  was previously undocumented. (iteration 14)
- Hardening: added `CHANGELOG.md` (Keep a Changelog), seeded "Unreleased" from the
  Done log. Operating rule 4 now requires a terse CHANGELOG entry per change.
  (iteration 13)
- Hardening: example now carries a `checkout_error_rate` health metric (kind
  `error_rate`) alongside latency + crash, so the sample DAILY_PULSE / METRIC_PLAN
  exercise the error-rate path. Regenerated artifacts. (iteration 12)
- Hardening: `mockgen.generate_events` gains an opt-in, seeded `adoption_effect`
  to plant lift on adoption metrics (primary lift + flat guardrails unchanged);
  default 0.0 preserves the existing stream byte-for-byte. Plumbed through
  `SimulatedSource`/`source_from_config` (descriptor stays backward-compatible).
  2 unit tests. (iteration 11)

  Follow-up (not yet done): expose `adoption_effect` as a CLI flag / config field
  so previews can request it without hand-editing the source dict.
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
