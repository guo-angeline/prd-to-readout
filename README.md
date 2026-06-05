<h1 align="center">prd-to-readout</h1>

<p align="center">
  <b>Turn a PRD into a gated, self-healing analytics workflow.</b><br>
  Hypotheses, tracking spec, logging QA, reviewed SQL, a launch decision, and a daily health monitor.
</p>

<p align="center">
  <code>pip install prd-to-readout</code> · MIT · runs locally on DuckDB · any LLM via LiteLLM
</p>

---

> Dashboards are static and dead. Analytics should adapt to the feature you're building.

`prd-to-readout` is not a one-shot toy that fakes a result. Most "PRD to insight" demos invent a
metric, fabricate data, and print a confident verdict in one breath. Real analytics has time gaps
and handoffs: a spec is written, an engineer instruments it over a sprint, someone checks the events
actually arrive, a data scientist reviews the SQL, and only then, after enough real data, do you
make a call.

This tool models that **real lifecycle** as a stateful, resumable workflow with human gates and
handoffs. It writes deterministic code artifacts into your repo at each step, tracks where every
feature is, files the handoff to the right person, and refuses to run a stage before its predecessor
has done its work (moving on to a stage approves the gate behind it).

```
1. metric             PRD  ->  metric_plan.yaml         🔒 PM/DS approves
2. logging    metric plan -> LOGGING_SPEC.md + snippets   🔔 hand off to an engineer
3. logging_qa real events -> validated vs the spec      🔒 SRM + coverage checks pass
4. query              self-corrected DuckDB SQL                 🔔 DS reviews   🔒 approves
5. readout            READOUT.md, the launch decision           ⏳ at the 2-week window, on real data
```

Two things make it trustworthy rather than just slick:

1. **It never grades its own homework.** Before logging exists it runs on simulated data,
   and it labels that output a `SIMULATED PREVIEW` with no ship verdict. A real SHIP/KILL/ITERATE
   call only comes from real, adequately powered data.
2. **Humans stay in the loop at every gate**, in the terminal or natively in GitHub.

## Contents

- [Quickstart](#quickstart)
- [The five stages](#the-five-stages)
- [The metric plan](#the-metric-plan)
- [Two outputs: the decision and the monitor](#two-outputs-the-decision-and-the-monitor)
- [GitHub-native gates](#github-native-gates)
- [Real data](#real-data)
- [Statistical methodology](#statistical-methodology)
- [Health monitoring](#health-monitoring)
- [Commands](#commands)
- [Configuration](#configuration)
- [Generated artifacts](#generated-artifacts)
- [Architecture and extension points](#architecture-and-extension-points)
- [Install](#install)
- [Development](#development)

## Quickstart

```bash
pip install prd-to-readout        # not on PyPI yet: see "Install" below to install from source
prd-to-readout init               # creates a sample prd.md, a guided .env, and workflow state
```

`init` tells you whether your model is ready and exactly what to do next.

### Set up your model (required)

prd-to-readout reads your PRD with an AI model, so it needs one before the AI steps run. Open the
`.env` file that `init` created and pick **one** option:

| Option | What to do |
|--------|------------|
| **Claude** (recommended) | Get a key at <https://console.anthropic.com/settings/keys>, then put `ANTHROPIC_API_KEY=your-key` in `.env` |
| **OpenAI** | Get a key at <https://platform.openai.com/api-keys>, then set `OPENAI_API_KEY=your-key` and `P2R_MODEL=gpt-4o` |
| **Free, on your computer** | Install [Ollama](https://ollama.com), run `ollama pull llama3.1`, and set `P2R_MODEL=ollama/llama3.1` (no key, works offline, lower quality) |

Run `prd-to-readout status` anytime to see the model line. If a key is missing, the tool says so in
plain language and points at the exact file and line to fix, so you never hit a cryptic error.

### See it run

```bash
prd-to-readout run prd.md --yes --preview   # the whole flow on sample data, labeled a preview
```

The real, gated flow runs stage by stage. Each stage stops at a gate. **Running the next stage is
itself the approval of the one before it**, so you just walk forward, reviewing each artifact as you
go (use explicit `approve` / `request-changes` only when you want to record an approver or reject):

```bash
prd-to-readout metric prd.md   # review METRIC_PLAN.md
prd-to-readout logging                 # approves metric, hands the spec to an engineer
# ... engineer ships the logging, events start flowing ...
prd-to-readout verify-logging --source events.csv   # approves logging, ingests + QAs
prd-to-readout query                # approves the QA, hands the SQL to a data scientist
prd-to-readout readout              # approves the query, writes READOUT.md at the 2-week window

prd-to-readout pulse                # DAILY_PULSE.md: adoption + health, run daily from here on
prd-to-readout status               # the board, at any time
```

To reject instead of advance, `request-changes <stage> --note "..."` and re-run that stage. GitHub
gates are the exception: an open issue must be cleared in GitHub (then `sync`), not by moving on.

`p2r` is a shorter alias for every command.

## The five stages

Every stage reads the previous stage's artifact, runs its work, then parks at a gate
(`awaiting_approval`). Moving on to the next stage approves it; `approve` / `request-changes` are
there when you want to name an approver or reject. `readout` is the terminal decision; it is not a
recurring step.

| # | Stage | Input | Output | Gate |
|---|-------|-------|--------|------|
| 1 | `metric` | PRD markdown | a readable `METRIC_PLAN.md` to review, backed by `metric_plan.yaml` (the machine source): primary metric, guardrails, health metrics, hypotheses (if/then/because), experiment design (split, horizon, MDE), and the decision-framing fields the readout needs | PM/DS reads the `.md` and approves |
| 2 | `logging` | metric plan | `LOGGING_SPEC.md` (the engineer's deliverable), `tracking_schema.json` (events + typed properties + metric bindings), and paste-ready `snippets/track.ts` + `track.py` | engineer implements the logging, ships it, then confirms |
| 3 | `verify-logging` | tracking spec + a real events source | ingests events into DuckDB and writes `LOGGING_QA.md`: every declared event arriving, required properties populated, both arms present, and a sample-ratio-mismatch check | DS confirms the data is trustworthy |
| 4 | `query` | spec + ingested events | `models/metrics_daily.sql`: the agent writes the aggregation SQL, runs it against DuckDB, and on failure feeds the traceback back to the model and rewrites until it passes (with a deterministic fallback so the loop never dead-ends) | DS reviews the SQL for correctness |
| 5 | `readout` | approved data | `READOUT.md`: the one-off launch decision (see below) | gated on the launch window and statistical power, not a human gate |

The metric bindings in the tracking spec are the contract: the simulator uses them to fabricate
data with a known signal, and the SQL agent independently re-derives the metrics from raw events, so
"the numbers came out right" actually means something.

## The metric plan

Stage 1 produces `METRIC_PLAN.md` (and its machine source `metric_plan.yaml`) on a standard
product-analytics-plan template. Four parts are worth calling out:

- **Baseline to target ("what good looks like").** Every metric carries a `baseline` (today's
  control value) and a `target` (the value that counts as a win), rendered as `32.0% -> 36.0%`. Rates
  show as percentages; means and counts keep their units. With no numbers in the PRD it falls back to
  a direction ("higher is better").
- **Adoption & engagement metrics.** A separate list from the primary metric and guardrails. These
  funnel/depth signals show the feature is being *used* (a take-rate, a depth-of-engagement). They are
  tracked and reported but **informational**: they do not gate the ship decision.
- **Power analysis.** From the primary metric's baseline conversion and your MDE, the plan computes
  the per-arm sample size needed to detect that lift at 80% power. The `metric` command warns when the
  planned `users_per_arm` is below it, and the readout labels underpowered data `ACCUMULATING` rather
  than calling a verdict.
- **Causal fallback.** When a clean user-level A/B test is blocked (network effects, marketplace
  dynamics, a hard rollout), the plan can specify a quasi-experimental design instead:
  difference-in-differences, synthetic control, RDD, or PSM, with its treatment/control units and the
  parallel-trends check. Leave it unset and the default stays a straight A/B test.

Edit `metric_plan.yaml` and re-run `metric` to change any of this; the readable `.md` is regenerated
from it.

## Two outputs: the decision and the monitor

These are deliberately separate documents with different jobs, cadences, and trust models.

**`READOUT.md`, the one-off launch decision.** Generated once, at the launch window (two weeks
post-launch by default; `launch_date` is set automatically when data first flows). It follows a
standard launch-readout template: TL;DR, context and problem, what shipped, the if/then/because
hypothesis with its MDE, a Primary & Secondary metrics table, a Guardrail & Counter-metrics table,
key deep dives, and the **SHIP / KILL / ITERATE** recommendation with rationale and a monitoring
plan. It carries a Methodology section so every number is auditable. The verdict only goes hard on
real, powered data; otherwise it stays a labeled `PREVIEW`.

**`DAILY_PULSE.md`, the recurring monitor.** Run it daily via `pulse`. It tracks adoption and
engagement and watches operational **health for regressions**: latency spikes, crash and ANR
increases, error-rate jumps. It is cheap and deterministic (no LLM call), so it is safe to schedule,
and it makes **no** ship decision. A status badge summarizes 🟢 healthy / 🟡 watch / 🔴 regression,
with an active-alerts callout when something crosses a threshold.

See committed examples: [`READOUT.md`](examples/sample_run/READOUT.md) and
[`DAILY_PULSE.md`](examples/sample_run/DAILY_PULSE.md).

## GitHub-native gates

Approvals can live in GitHub instead of the terminal, giving you a real audit trail and a familiar
review surface. You don't have to set anything up first: **as each stage parks at its gate, the tool
asks for that approver's GitHub handle as an optional step.** Type a handle and it lazily creates a
private repo (on the first one), invites the approver, and opens an Issue assigned to them; press
Enter to skip and keep that gate terminal-based.

```bash
prd-to-readout metric prd.md   # at the gate: "GitHub handle for the product approver (optional)"
prd-to-readout logging         # asks for the engineering approver, reuses the same repo
# ... each later gate asks for its own approver, once
prd-to-readout sync            # pull their decisions back into the local workflow
```

To skip the prompts, **name the approvers in the PRD** and they're used automatically (no asking):

```markdown
## Approvers
- Product / metrics owner: @alice
- Engineering (logging): @bob
- Data Science (QA + SQL): @carol
```

This needs the `gh` CLI authenticated (`gh auth login`); if it isn't ready, the gate says so and
stays terminal-based. Prompts only appear in an interactive terminal, so they never block `--yes`,
piped, or CI runs. To set everything up in one shot, or reuse an existing repo, run `gh-setup`:

```bash
prd-to-readout gh-setup --create --repo my-launch   # create a private repo + invite approvers
```

Roles map to gates: **product** clears the metric gate, **engineering** confirms the logging,
**data science** reviews QA and the SQL.

The approver clears a gate by commenting **`/approve`**, or sends it back with
**`/request-changes <reason>`**. Closing the issue also approves, but only when the approver is the
one who closed it. Approval always requires a named approver: a gate with no configured handle never
advances through GitHub on its own, and a `/approve` from anyone other than the assigned approver is
ignored. `sync` reconciles these decisions into the local workflow and closes approved issues.

If the PRD does not list a handle, `gh-setup` asks for it in the CLI before proceeding (auto-setup
just skips that role). This uses the `gh` CLI (run `gh auth login` once); there is no server to host,
`sync` simply polls. Approvers must accept the repo invite to be assignable. Without any approvers or
`gh`, gates stay terminal-based (`approve` / `request-changes`), and that path still works as a
manual override even with GitHub on.

## Real data

`verify-logging --source events.csv` ingests your exported events (CSV, Parquet, JSON, or
JSONL) into the same pipeline that the simulated preview used, so everything downstream is identical.
The expected columns are `event_name, user_id, arm, ts`, plus either a `props` JSON column or extra
columns that get packed into `props`. If your export uses different column names, pass a mapping.

Once real events are flowing, the readout's verdict becomes real (subject to power), and `pulse`
reports actual adoption.

### Warehouse sources

Pull events straight from a warehouse query instead of a file:

```bash
verify-logging --warehouse-query "SELECT event_name, user_id, arm, ts, props FROM analytics.events" \
               --warehouse-driver bigquery --warehouse-project my-gcp-project
```

The query must return the canonical columns (`event_name, user_id, arm, ts`) plus any extras, which
get packed into `props` (same contract as the file source). BigQuery ships as an optional driver:
`pip install google-cloud-bigquery` and authenticate with the usual `GOOGLE_APPLICATION_CREDENTIALS`.

Drivers are pluggable via `register_warehouse_driver(name, factory)` in `adapters/source.py`: a
`factory(config)` returns a `fetch()` callable yielding `(columns, rows)`, and `WarehouseSource` maps
those rows into the pipeline through the shared `rows_to_events` contract. New backends (Snowflake,
Postgres, Segment, Amplitude) slot in the same way. See `examples/warehouse_source_demo.py` for a
runnable end-to-end demo backed by a local DuckDB standing in for a warehouse (no external services).

## Statistical methodology

The readout is built for a data scientist to trust:

- **Tests.** Two-proportion z-test for rate metrics; Welch's t-test for means and counts. Computed
  from the raw event stream, not from the aggregated layer, so they are statistically correct.
- **Multiple comparisons.** Testing the primary metric plus every guardrail inflates false
  positives, so p-values are adjusted with **Holm-Bonferroni** across the family of metrics. Without
  this, a flat guardrail occasionally reads "significant" and flips the verdict.
- **Power and sufficiency.** The readout computes the per-arm sample size needed to detect your MDE
  at 80% power and gates a hard verdict on reaching it. Underpowered data is labeled `ACCUMULATING`.
- **Sample-ratio mismatch (SRM).** A chi-square check that arm sizes match the planned split. A
  failing SRM means randomization or logging is broken and the whole experiment is suspect; it is
  flagged in logging QA.
- **Honest framing.** Simulated data is a `SIMULATED PREVIEW` with no verdict. Relative-lift
  confidence intervals are reported. A repeated-looks (peeking) caveat is written into every
  readout, since a daily significance test is not a valid stopping rule.

## Health monitoring

`pulse` watches operational metrics declared in the metric plan (`health_metrics`): latency, crash
rate, ANR rate, error rate, each with a regression threshold and unit. For each metric it compares a
recent window against the earlier baseline and the threshold, and classifies it:

- 🔴 **regression**: recent value is over the threshold (paged in the active-alerts list)
- 🟡 **watch**: trending up sharply versus baseline but still under threshold
- 🟢 **ok**: stable

The pulse status badge is the worst of the health signals and the adoption signal (a primary metric
moving the wrong way significantly is itself a 🔴). Health values come from the simulated stream in
preview mode; wiring a real APM or crash reporter is an `EventSource`-style extension.

## Commands

| Command | Stage | What it does |
|---|---|---|
| `init` | | Scaffold a sample PRD, `.env`, and workflow state |
| `metric <prd>` | 1 | PRD to `metric_plan.yaml` |
| `logging` | 2 | Metric plan to `LOGGING_SPEC.md` + `tracking_schema.json` + snippets; notify engineer |
| `verify-logging [--source f] [--simulate] [--force]` | 3 | Ingest events and validate them against the spec (coverage, types, SRM) |
| `query` | 4 | Author and self-correct the aggregation SQL; notify DS to review |
| `readout [--force] [--window-days N]` | 5 | The one-off launch decision `READOUT.md`, gated on the window |
| `pulse` | | Recurring monitor `DAILY_PULSE.md` (adoption + health); run daily |
| `approve <stage> [--by --note]` / `request-changes <stage> --note` | | Explicitly clear (naming an approver) or reject a gate; running the next stage also approves |
| `gh-setup [--create] [--repo name]` | | Create a private repo + invite approvers; enable GitHub-native gates |
| `sync` | | Pull gate decisions from GitHub issues into the workflow |
| `status` | | Show the workflow board and the next action |
| `run <prd> [--yes] [--preview]` | | Walk all stages, stopping at each gate unless `--yes` |
| `schedule [--cron "0 9 * * *"]` | | Print a cron snippet to run `pulse` on a schedule |
| `feedback up\|down [-n "..."]` | | Capture thumbs up/down on the readout |
| `version` | | Print the version |

Common flags: `--workdir/-w` (where artifacts live, default the current directory), `--model/-m`
(override `P2R_MODEL`), `--seed`, `--effect` (the planted lift for the simulated preview),
`--max-fix-attempts` (SQL self-correction budget), `--yes/-y` (auto-approve a gate).

## Configuration

Set via `.env` or the environment.

| Var | Default | Meaning |
|---|---|---|
| `P2R_MODEL` | `claude-sonnet-4-6` | Any LiteLLM model string (`gpt-4o`, `ollama/llama3.1`, ...) |
| `P2R_SEED` | `42` | Seed for reproducible simulated previews |
| `P2R_SLACK_WEBHOOK` | unset | Slack incoming webhook; gate handoffs post here |
| `P2R_SMTP_HOST` / `P2R_SMTP_PORT` / `P2R_SMTP_USER` / `P2R_SMTP_PASSWORD` | unset | SMTP server for email handoffs |
| `P2R_EMAIL_FROM` / `P2R_EMAIL_TO` | unset | Email sender and recipient for handoffs |
| provider key, e.g. `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | unset | Whatever your `P2R_MODEL` provider needs |

Handoffs at each gate always echo to the console, and additionally fire to Slack and/or email if
configured. The engineer gets the logging spec; the data scientist gets the SQL to review. New
channels (Linear, PagerDuty, ...) implement the same `Notifier` protocol in `adapters/notify.py`.

## Generated artifacts

A run writes these into your working directory (headline artifacts at the root, bulky state under a
hidden `.pulse/`):

```
METRIC_PLAN.md       # the metrics plan, readable: what you review and approve
metric_plan.yaml     # the same plan as machine data (edit this to change the plan)
tracking_schema.json         # events, typed properties, and metric bindings
LOGGING_SPEC.md              # human-readable spec: the engineer's deliverable
snippets/track.ts, track.py  # paste-ready logger calls
LOGGING_QA.md        # the data-validation report from stage 3
models/metrics_daily.sql     # the reviewed, self-corrected aggregation
READOUT.md                   # the one-off launch decision
DAILY_PULSE.md               # the recurring adoption + health monitor
.pulse/state.yaml            # the workflow manifest (stages, approvals, issues, source, launch date)
.pulse/pulse.duckdb          # the local warehouse
```

## Architecture and extension points

Provider-agnostic and zero-infrastructure: **DuckDB** is the warehouse, **LiteLLM** is the model
layer (bring any provider, with prompt caching on Claude), and the state lives in a single YAML
manifest. The codebase is small and modular so plugins are easy.

```
src/prd_to_readout/
  cli.py            # the Typer CLI and stage orchestration
  config.py         # paths and runtime config
  llm.py            # the LiteLLM wrapper (the only model surface)
  prompts.py        # one system prompt per agent
  agents/           # hypothesis, logging, pipeline, report, readout, pulse
  core/             # schemas, state, workflow, mockgen, duckdb_runner, stats,
                    #   charts, logging_qa, provenance, health
  adapters/         # notify (console/Slack/email), source (simulated/file),
                    #   github (gh-CLI gates)
  samples/          # the demo PRD shipped with `init`
```

Three pluggable interfaces:

- **`EventSource`** (`adapters/source.py`): where events come from. `SimulatedSource`, `FileSource`,
  and a pluggable `WarehouseSource` (BigQuery driver included) ship; more warehouse / product-analytics
  backends register via `register_warehouse_driver`.
- **`Notifier`** (`adapters/notify.py`): how humans are pinged at a gate.
- **GitHub gates** (`adapters/github.py`): the decision logic (`evaluate_issue`) is pure and unit
  tested; the `gh`-CLI calls are isolated.

The SQL destination is pluggable too: the agent emits DuckDB SQL today, and the warehouse-agnostic
metric bindings mean a contributor can add a Snowflake or dbt generator without touching the rest.

## Install

Not published to PyPI yet, so install from source. To just use it (puts `prd-to-readout` and `p2r`
on your PATH):

```bash
git clone https://github.com/guo-angeline/prd-to-readout.git
uv tool install --editable ./prd-to-readout      # or: pipx install ./prd-to-readout
```

## Development

```bash
uv venv && uv pip install -e ".[dev]"
uv run pytest        # LLM and network calls are stubbed; no API key needed
uv run ruff check .
python examples/_generate.py   # regenerate the committed example READOUT.md + DAILY_PULSE.md
```

The test suite stubs the model and GitHub, so CI runs offline with no secrets.

## License

MIT
