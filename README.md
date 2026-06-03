<h1 align="center">prd-to-readout</h1>

<p align="center">
  <b>Turn a PRD into a gated, self-healing analytics workflow.</b><br>
  Hypotheses, tracking spec, instrumentation QA, reviewed SQL, a launch decision, and a daily health monitor.
</p>

<p align="center">
  <code>pip install prd-to-readout</code> · MIT · runs locally on DuckDB · any LLM via LiteLLM
</p>

---

> Dashboards are static and dead. Analytics should adapt to the feature you're building.

`prd-to-readout` is not a one-shot toy that fakes a result. It models the **real lifecycle** of
shipping analytics for a feature, as a stateful workflow with human gates and handoffs:

```
1. hypothesis        PRD  ->  analytics_blueprint.yaml        🔒 PM/DS approves
2. instrumentation   blueprint -> LOGGING_SPEC.md + snippets  🔔 hand off to an engineer
3. instrumentation_qa real events -> validated vs the spec    🔒 SRM + coverage checks pass
4. pipeline          self-corrected DuckDB SQL                🔔 DS reviews  🔒 approves
5. readout           READOUT.md, the launch decision          ⏳ at the 2-week window, on real data
```

Each stage stops at a gate until a human approves it (or you pass `--yes`). The tool tracks where
every feature is, files the handoff to the right person, and refuses to run a stage before its
predecessor is approved. `prd-to-readout status` shows the board.

## Two outputs: the decision and the monitor

These are deliberately separate documents:

- **`READOUT.md` (one-off launch decision).** Generated once, at the launch window (two weeks
  post-launch by default). It owns the decision: hypothesis result, primary/secondary metrics with
  significance, guardrails vs thresholds, and the **SHIP / KILL / ITERATE** recommendation. It
  follows a standard launch-readout template.
- **`DAILY_PULSE.md` (recurring monitor).** Run it daily via `pulse`. It tracks adoption and
  engagement and watches operational **health for regressions** (latency spikes, crash/ANR
  increases). It is cheap and deterministic (no LLM) and makes **no** ship decision. Schedule it
  with `prd-to-readout schedule`.

See committed examples: [`READOUT.md`](examples/sample_run/READOUT.md) and
[`DAILY_PULSE.md`](examples/sample_run/DAILY_PULSE.md).

## Why you can trust the numbers

Most "PRD to insight" demos quietly grade their own homework on fake data. This one is explicit
about what's real:

- **Simulated runs are labeled.** Before instrumentation exists, the readout is a `⚠️ SIMULATED
  PREVIEW` that validates your metric and tracking design. It never prints a SHIP/KILL verdict.
- **Real results require real, powered data.** Plug in your exported events; the verdict only fires
  once the sample clears the power threshold for your MDE.
- **The stats are honest.** Two-proportion z-test / Welch's t-test, Holm-Bonferroni correction
  across primary + guardrails, a sample-ratio-mismatch (SRM) check, relative-lift CIs, and a
  written caveat about repeated-looks (peeking). Every readout ships a Methodology section.
- **The SQL is reviewable.** The agent self-corrects the aggregation SQL until it runs, then hands
  it to a data scientist to approve for correctness before it touches anything.

## Quickstart

```bash
pip install prd-to-readout
prd-to-readout init                 # sample PRD + .env template + workflow state
cp .env.example .env                # add a key, or point P2R_MODEL at a local model

# walk the workflow, stopping at each gate:
prd-to-readout run prd.md

# or drive it stage by stage:
prd-to-readout hypothesize prd.md
prd-to-readout approve hypothesis --by you
prd-to-readout spec                 # notifies the engineer with LOGGING_SPEC.md
# ... engineer ships the logging ...
prd-to-readout approve instrumentation --by eng
prd-to-readout verify-instrumentation --source events.csv   # real data + QA
prd-to-readout approve instrumentation_qa --by ds
prd-to-readout build                # notifies a DS to review models/metrics_daily.sql
prd-to-readout approve pipeline --by ds

prd-to-readout pulse                # DAILY_PULSE.md: adoption + health, run this daily
prd-to-readout readout              # READOUT.md: the launch decision, at the 2-week window

prd-to-readout status               # the board, anytime
```

`p2r` is a shorter alias. To see the whole loop instantly on simulated data:
`prd-to-readout run prd.md --yes --preview`.

## Commands

| Command | Stage | What it does |
|---|---|---|
| `init` | | Scaffold a sample PRD, `.env`, and workflow state |
| `hypothesize <prd>` | 1 | PRD to `analytics_blueprint.yaml` |
| `spec` | 2 | Blueprint to `LOGGING_SPEC.md` + `tracking_schema.json` + snippets; notify engineer |
| `verify-instrumentation [--source f]` | 3 | Ingest events and validate them against the spec (coverage, types, SRM) |
| `build` | 4 | Author + self-correct the aggregation SQL; notify DS to review |
| `readout [--force --window-days]` | 5 | The one-off launch decision `READOUT.md` (gated on the 2-week window) |
| `pulse` | | Recurring monitor `DAILY_PULSE.md` (adoption + health); run daily |
| `approve <stage>` / `request-changes <stage>` | | Clear or reject a gate (recorded with who/when) |
| `status` | | Show the workflow board and the next action |
| `run <prd> [--yes] [--preview]` | | Walk all stages, stopping at each gate unless `--yes` |
| `schedule [--cron]` | | Print a cron snippet to run `pulse` on a schedule |
| `feedback up\|down -n "..."` | | Capture thumbs up/down on the readout |

## Real data

`verify-instrumentation --source events.csv` ingests your exported events (CSV / Parquet / JSON /
JSONL) into the same pipeline. The expected columns are `event_name, user_id, arm, ts` plus either a
`props` JSON column or extra columns that get packed into `props`. Names differ? Pass a mapping.
Warehouse (BigQuery/Snowflake/Postgres) and Segment/Amplitude sources are documented extension
points implementing the same `EventSource` interface (`adapters/source.py`).

## Notifications and handoffs

Handoffs at each gate fire to whatever you configure, with a console echo always on:

- **Slack:** set `P2R_SLACK_WEBHOOK`.
- **Email:** set `P2R_SMTP_HOST` / `P2R_EMAIL_TO` (and the related SMTP vars).

The engineer gets the logging spec; the data scientist gets the SQL to review. New channels
(GitHub, Linear, PagerDuty) implement the same `Notifier` protocol (`adapters/notify.py`).

## Configuration

| Var | Default | Meaning |
|---|---|---|
| `P2R_MODEL` | `claude-sonnet-4-6` | Any LiteLLM model string (`gpt-4o`, `ollama/llama3.1`, ...) |
| `P2R_SEED` | `42` | Seed for reproducible simulated previews |
| `P2R_SLACK_WEBHOOK` / SMTP vars | unset | Notification channels (see `.env.example`) |

## Development

```bash
uv venv && uv pip install -e ".[dev]"
uv run pytest        # LLM + network stubbed; no API key needed
uv run ruff check .
python examples/_generate.py   # regenerate the committed example readout
```

## License

MIT
