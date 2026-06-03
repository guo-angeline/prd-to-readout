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
1. hypothesis         PRD  ->  analytics_blueprint.yaml         🔒 PM/DS approves
2. instrumentation    blueprint -> LOGGING_SPEC.md + snippets   🔔 hand off to an engineer
3. instrumentation_qa real events -> validated vs the spec      🔒 SRM + coverage checks pass
4. pipeline           self-corrected DuckDB SQL                 🔔 DS reviews   🔒 approves
5. readout            READOUT.md, the launch decision           ⏳ at the 2-week window, on real data
```

Two things make it trustworthy rather than just slick:

1. **It never grades its own homework.** Before instrumentation exists it runs on simulated data,
   and it labels that output a `SIMULATED PREVIEW` with no ship verdict. A real SHIP/KILL/ITERATE
   call only comes from real, adequately powered data.
2. **Humans stay in the loop at every gate**, in the terminal or natively in GitHub.

## Contents

- [Quickstart](#quickstart)
- [The five stages](#the-five-stages)
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
prd-to-readout hypothesize prd.md   # review ANALYTICS_BLUEPRINT.md
prd-to-readout spec                 # approves hypothesis, hands the spec to an engineer
# ... engineer ships the logging, events start flowing ...
prd-to-readout verify-instrumentation --source events.csv   # approves instrumentation, ingests + QAs
prd-to-readout build                # approves the QA, hands the SQL to a data scientist
prd-to-readout readout              # approves the pipeline, writes READOUT.md at the 2-week window

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
| 1 | `hypothesize` | PRD markdown | a readable `ANALYTICS_BLUEPRINT.md` to review, backed by `analytics_blueprint.yaml` (the machine source): primary metric, guardrails, health metrics, hypotheses (if/then/because), experiment design (split, horizon, MDE), and the decision-framing fields the readout needs | PM/DS reads the `.md` and approves |
| 2 | `spec` | blueprint | `LOGGING_SPEC.md` (the engineer's deliverable), `tracking_schema.json` (events + typed properties + metric bindings), and paste-ready `snippets/track.ts` + `track.py` | engineer implements the logging, ships it, then confirms |
| 3 | `verify-instrumentation` | tracking spec + a real events source | ingests events into DuckDB and writes `INSTRUMENTATION_QA.md`: every declared event arriving, required properties populated, both arms present, and a sample-ratio-mismatch check | DS confirms the data is trustworthy |
| 4 | `build` | spec + ingested events | `models/metrics_daily.sql`: the agent writes the aggregation SQL, runs it against DuckDB, and on failure feeds the traceback back to the model and rewrites until it passes (with a deterministic fallback so the loop never dead-ends) | DS reviews the SQL for correctness |
| 5 | `readout` | approved data | `READOUT.md`: the one-off launch decision (see below) | gated on the launch window and statistical power, not a human gate |

The metric bindings in the tracking spec are the contract: the simulator uses them to fabricate
data with a known signal, and the SQL agent independently re-derives the metrics from raw events, so
"the numbers came out right" actually means something.

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
review surface. **Just name the approvers in the PRD.** When the hypothesis stage extracts those
handles, the tool automatically creates a private repo, invites them, and opens an Issue at each
gate assigned to the right person, no extra command:

```bash
# In the PRD, name the approvers (the hypothesis step extracts these into the blueprint):
#   ## Approvers
#   - Product / metrics owner: @alice
#   - Engineering (instrumentation): @bob
#   - Data Science (QA + SQL): @carol

prd-to-readout run prd.md   # hypothesis names approvers -> private repo + per-gate issues, automatically
prd-to-readout sync         # pull decisions into the local workflow
```

This needs the `gh` CLI authenticated (`gh auth login`). If `gh` isn't ready, the run says so and
stays terminal-gated. To enable GitHub explicitly, or to reuse an existing repo, run `gh-setup`:

```bash
prd-to-readout gh-setup --create --repo my-launch   # create a private repo + invite approvers
```

Auto-setup is skipped under `--yes` (gates auto-clear locally, so issues would be moot) and when
the PRD names no approvers.

Roles map to gates: **product** clears the hypothesis, **engineering** confirms the instrumentation,
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

`verify-instrumentation --source events.csv` ingests your exported events (CSV, Parquet, JSON, or
JSONL) into the same pipeline that the simulated preview used, so everything downstream is identical.
The expected columns are `event_name, user_id, arm, ts`, plus either a `props` JSON column or extra
columns that get packed into `props`. If your export uses different column names, pass a mapping.

Once real events are flowing, the readout's verdict becomes real (subject to power), and `pulse`
reports actual adoption. Warehouse sources (BigQuery, Snowflake, Postgres) and product-analytics
sources (Segment, Amplitude) are documented extension points that implement the same `EventSource`
interface in `adapters/source.py`.

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
  flagged in instrumentation QA.
- **Honest framing.** Simulated data is a `SIMULATED PREVIEW` with no verdict. Relative-lift
  confidence intervals are reported. A repeated-looks (peeking) caveat is written into every
  readout, since a daily significance test is not a valid stopping rule.

## Health monitoring

`pulse` watches operational metrics declared in the blueprint (`health_metrics`): latency, crash
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
| `hypothesize <prd>` | 1 | PRD to `analytics_blueprint.yaml` |
| `spec` | 2 | Blueprint to `LOGGING_SPEC.md` + `tracking_schema.json` + snippets; notify engineer |
| `verify-instrumentation [--source f] [--simulate] [--force]` | 3 | Ingest events and validate them against the spec (coverage, types, SRM) |
| `build` | 4 | Author and self-correct the aggregation SQL; notify DS to review |
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
ANALYTICS_BLUEPRINT.md       # the metrics plan, readable: what you review and approve
analytics_blueprint.yaml     # the same plan as machine data (edit this to change the plan)
tracking_schema.json         # events, typed properties, and metric bindings
LOGGING_SPEC.md              # human-readable spec: the engineer's deliverable
snippets/track.ts, track.py  # paste-ready logger calls
INSTRUMENTATION_QA.md        # the data-validation report from stage 3
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
                    #   charts, instrumentation_qa, provenance, health
  adapters/         # notify (console/Slack/email), source (simulated/file),
                    #   github (gh-CLI gates)
  samples/          # the demo PRD shipped with `init`
```

Three pluggable interfaces:

- **`EventSource`** (`adapters/source.py`): where events come from. `SimulatedSource` and
  `FileSource` ship; warehouse and product-analytics sources slot in here.
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
