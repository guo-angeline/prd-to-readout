# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project aims to
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Each autonomous-loop change adds a terse entry under "Unreleased" (see
`AUTONOMOUS_BACKLOG.md`).

## [Unreleased]

### Added

- Real-data warehouse path: a shared `rows_to_events` contract, driver-agnostic
  `WarehouseSource`, a pluggable driver registry (`register_warehouse_driver`),
  an optional BigQuery driver, `verify-logging --warehouse-query` CLI wiring, and
  a runnable no-external-services demo (`examples/warehouse_source_demo.py`).
- `metric` CLI warns when the planned `users_per_arm` is below the sample size
  needed to detect the target lift (shared `power_shortfall` helper).
- Opt-in, seeded `adoption_effect` in `mockgen.generate_events` so simulated
  previews can show adoption movement instead of a flat line, exposed as an
  `--adoption-effect` flag on `run` and `verify-logging` (and `Config.adoption_effect_size`).
- "What Success Looks Like" section in `READOUT.md`.
- `error_rate` health metric in the committed example (alongside latency and
  crash rate).

- PEP 561 `py.typed` marker so the package ships its inline type hints to
  downstream type checkers.

### Changed

- Package version is single-sourced from `__init__.py` via hatchling's dynamic
  version, so `pyproject.toml`, the CLI `version` command, and `__version__`
  cannot drift.
- `FileSource.load` checks file existence before the extension, so a mistyped
  path reports "not found" rather than an unsupported-extension error.
- `AnalyticsBlueprint` rejects duplicate metric names across primary, adoption,
  and guardrail metrics (a collision silently broke metric bindings and SQL).

### Fixed

- `DuckDBRunner.load_raw_events` no longer crashes when `props` holds non-JSON
  values (datetime/Decimal from a real events file's extra columns); they now
  serialize to their string form.

### Docs

- README: new "The metric plan" section documenting baseline-to-target framing,
  adoption metrics, power analysis, and the causal (quasi-experimental) fallback.
- Docstrings across the public surface: `core/stats.py`, `core/health.py`,
  `core/logging_qa.py`, `core/duckdb_runner.py`, `core/provenance.py`, and the
  `agents/*` entry points.

### Tests

- Coverage for `_power_lines` (baseline present/missing, under/over-powered) and
  `good_looks_like()` on rate, mean, and count metrics.
- End-to-end recovery tests for `stats.evaluate_metric` on `count` and `mean`
  metrics (per-user aggregation SQL, incl. the `numeric_mean` value_property).
