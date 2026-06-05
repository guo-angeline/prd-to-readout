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
  previews can show adoption movement instead of a flat line.
- "What Success Looks Like" section in `READOUT.md`.
- `error_rate` health metric in the committed example (alongside latency and
  crash rate).

### Changed

- `AnalyticsBlueprint` rejects duplicate metric names across primary, adoption,
  and guardrail metrics (a collision silently broke metric bindings and SQL).

### Docs

- README: new "The metric plan" section documenting baseline-to-target framing,
  adoption metrics, power analysis, and the causal (quasi-experimental) fallback.

### Tests

- Coverage for `_power_lines` (baseline present/missing, under/over-powered) and
  `good_looks_like()` on rate, mean, and count metrics.
