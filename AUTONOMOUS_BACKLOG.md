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

- READOUT.md now has a "What Success Looks Like" section (quantitative + qualitative),
  rendered from the blueprint. Test added. (iteration 1)

## Parked (tried, reverted, why)

(none yet)
