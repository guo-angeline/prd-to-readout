"""prd-to-readout command line interface.

The pipeline is a stateful, gated workflow. Each stage runs, writes its
artifacts, and parks at a human gate (approve / request-changes) unless --yes.
`status` shows the board; `run` walks the stages but stops at each gate.
"""

from __future__ import annotations

import functools
import hashlib
import json
from contextlib import contextmanager
from pathlib import Path

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from . import __version__
from .config import Config
from .core import workflow
from .core.state import STAGE_ORDER, STAGE_TITLES, WorkflowState
from .core.workflow import GateError

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Turn a PRD into a self-healing, local analytics workflow.",
)
console = Console()

FRIENDLY_ENV = """\
# prd-to-readout settings. This file is loaded automatically. Keep it private.
#
# ============================================================
#  STEP 1 (required): pick a model and paste a key
# ============================================================
# prd-to-readout uses an AI model to read your PRD. Choose ONE option.
#
# --- Option A: Claude (recommended) -------------------------
#   Get a key: https://console.anthropic.com/settings/keys
#   Paste it after the = sign below (no quotes, no spaces).
ANTHROPIC_API_KEY=
P2R_MODEL=claude-sonnet-4-6
#
# --- Option B: OpenAI ---------------------------------------
#   Get a key: https://platform.openai.com/api-keys
# OPENAI_API_KEY=
# P2R_MODEL=gpt-4o
#
# --- Option C: Free, runs on your computer ------------------
#   No key, no internet, lower quality. Install https://ollama.com,
#   then run: ollama pull llama3.1
# P2R_MODEL=ollama/llama3.1
#
# ============================================================
#  STEP 2 (optional): send approval handoffs to Slack / email
# ============================================================
# P2R_SLACK_WEBHOOK=
# P2R_SMTP_HOST=
# P2R_EMAIL_TO=
"""


def _print_model_status(cfg: Config) -> None:
    """Tell the user, in plain language, whether their model is ready."""
    from .config import model_status

    st = model_status(cfg.model)
    if st.is_local:
        console.print(f"[green]✓[/] Model: [cyan]{st.model}[/] (local, no key needed).")
    elif st.key_present:
        console.print(f"[green]✓[/] Model ready: [cyan]{st.model}[/] ({st.provider} key found).")
    else:
        console.print(f"[yellow]●[/] Model: [cyan]{st.model}[/] ({st.provider}). "
                      f"[yellow]No API key yet.[/]")
        console.print(f"   Get one: [bold]{st.help_url}[/]")
        console.print(f"   Then open [bold]{cfg.workdir / '.env'}[/] and set "
                      f"[bold]{st.key_var}=your-key[/]")


def _require_model(cfg: Config) -> None:
    """Friendly, early stop (before any AI call) if the model has no key."""
    from .config import model_status

    st = model_status(cfg.model)
    if st.key_present:
        return
    console.print(f"[bold yellow]Almost there, one setup step.[/] Your model "
                  f"[cyan]{st.model}[/] ({st.provider}) needs an API key.")
    console.print(f"  1. Get a key: [bold]{st.help_url}[/]")
    console.print(f"  2. Put it in [bold]{cfg.workdir / '.env'}[/] like this:  {st.key_var}=your-key-here")
    console.print("  Prefer free + offline? Set [bold]P2R_MODEL=ollama/llama3.1[/] (see https://ollama.com).")
    raise typer.Exit(1)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _config(workdir: Path | None, model: str | None, seed: int | None) -> Config:
    return Config.load(workdir=workdir, model=model, seed=seed)


def _llm(cfg: Config):
    from .llm import LLMClient

    return LLMClient(cfg.model)


def _banner(text: str) -> None:
    console.print(f"[bold green]▸[/] [bold]{text}[/]")


@contextmanager
def _working(message: str):
    """Show an animated spinner while a slow step runs, so it never looks stuck."""
    with console.status(f"[bold cyan]{message}[/]", spinner="dots"):
        yield


def _state(cfg: Config) -> WorkflowState:
    feature = (cfg.workdir / "prd.md").stem if (cfg.workdir / "prd.md").exists() else cfg.workdir.name
    return WorkflowState.load_or_new(cfg.paths.state, feature)


def _save(state: WorkflowState, cfg: Config) -> None:
    state.save(cfg.paths.state)


def _hint(state: WorkflowState) -> None:
    console.print(f"\n[dim]Next:[/] {workflow.next_action(state)}")


def _finish_stage(cfg: Config, state: WorkflowState, stage: str, artifacts, *, yes: bool = False) -> str:
    """Complete a stage, fire the handoff notification, open a GitHub gate, persist."""
    from .adapters.notify import build_notifier, gate_notification

    arts = [str(a) for a in artifacts]
    status_now = workflow.complete_stage(state, stage, arts, auto_yes=yes)
    if status_now in ("awaiting_approval", "done"):
        build_notifier().send(gate_notification(stage, arts))
    if status_now == "awaiting_approval":
        _open_gate_issue(cfg, state, stage)
    _save(state, cfg)
    return status_now


def _github_client(state: WorkflowState):
    """Return a GitHubClient if GitHub gates are configured, else None."""
    from .adapters.github import GitHubClient

    if not state.github or not state.github.get("repo"):
        return None
    return GitHubClient(state.github["repo"])


def _gate_artifact(cfg: Config, stage: str) -> Path | None:
    return {
        "hypothesis": cfg.paths.blueprint,
        "instrumentation": cfg.paths.spec_doc,
        "instrumentation_qa": cfg.paths.qa_report,
        "pipeline": cfg.paths.models_dir / "metrics_daily.sql",
    }.get(stage)


def _open_gate_issue(cfg: Config, state: WorkflowState, stage: str) -> None:
    """Open a GitHub issue assigned to the stage's approver (no-op if GitHub off)."""
    from .adapters.github import GATE_ROLE, GitHubError
    from .adapters.notify import gate_notification

    client = _github_client(state)
    if client is None:
        return
    role = GATE_ROLE.get(stage)
    approver = (state.github.get("approvers") or {}).get(role, "") if role else ""
    n = gate_notification(stage, [])
    title = f"[p2r] Approve: {stage} ({state.feature})"
    art = _gate_artifact(cfg, stage)
    preview = ""
    if art and art.exists():
        text = art.read_text()
        clipped = text[:6000] + ("\n... (truncated)" if len(text) > 6000 else "")
        preview = f"\n\n<details><summary>Artifact preview ({art.name})</summary>\n\n```\n{clipped}\n```\n</details>\n"
    body = (
        f"**Stage:** {stage}\n**For:** {n.audience}\n\n{n.action}\n\n"
        f"Reviewer{' @' + approver if approver else ''}: comment `/approve` to clear this gate, "
        f"or `/request-changes <reason>` to send it back. Closing it yourself (as the approver) also approves.\n"
        f"Then the operator runs `prd-to-readout sync` to advance the workflow.{preview}"
    )
    try:
        with _working("Opening the GitHub approval issue..."):
            number, url = client.create_issue(title, body, assignee=approver or None)
        st = state.stage(stage)
        st.issue_number, st.issue_url = number, url
        console.print(f"  [green]GitHub gate:[/] opened issue #{number} -> {url}")
    except GitHubError as e:
        console.print(f"  [yellow]Could not open GitHub issue:[/] {e}")


def _resolve_approvers(blueprint, state: WorkflowState, *, interactive: bool = True) -> dict:
    """Resolve role->handle from the blueprint, then state, then an interactive prompt."""
    from .adapters.github import ROLES

    declared = {}
    if blueprint is not None:
        declared = {
            "product": blueprint.approvers.product,
            "engineering": blueprint.approvers.engineering,
            "data_science": blueprint.approvers.data_science,
        }
    existing = (state.github or {}).get("approvers", {})
    out = {}
    for role in ROLES:
        handle = (existing.get(role) or declared.get(role) or "").lstrip("@")
        if not handle and interactive:
            label = role.replace("_", " ")
            handle = typer.prompt(f"GitHub handle for the {label} approver (no @)").lstrip("@")
        out[role] = handle
    return out


def handle_errors(fn):
    """Turn provider/auth failures and gate violations into clean messages, not stacktraces."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        from .llm import LLMError

        try:
            return fn(*args, **kwargs)
        except (LLMError, GateError) as e:
            console.print(f"[bold red]Error:[/] {e}")
            raise typer.Exit(1) from None

    return wrapper


def _load_blueprint(cfg: Config):
    from .core.schemas import AnalyticsBlueprint

    if not cfg.paths.blueprint.exists():
        raise GateError("No analytics_blueprint.yaml yet. Run 'hypothesize <prd>' first.")
    return AnalyticsBlueprint.from_yaml(cfg.paths.blueprint.read_text())


def _load_tracking(cfg: Config):
    from .core.schemas import TrackingSchema

    if not cfg.paths.tracking_schema.exists():
        raise GateError("No tracking_schema.json yet. Run 'spec' first.")
    return TrackingSchema.model_validate_json(cfg.paths.tracking_schema.read_text())


# --------------------------------------------------------------------------- #
# stage workers (shared by `run` and the per-stage commands; no state changes)
# --------------------------------------------------------------------------- #
def _do_hypothesis(cfg: Config, llm, prd_text: str):
    from .agents import hypothesis_agent

    with _working("Reading your PRD and drafting the metrics plan (about 15 to 30s)..."):
        bp = hypothesis_agent.generate_blueprint(prd_text, llm)
    cfg.paths.ensure()
    cfg.paths.blueprint.write_text(bp.to_yaml())
    return bp


def _do_spec(cfg: Config, llm, blueprint):
    from .agents import logging_agent

    with _working("Designing the tracking spec and writing the engineer handoff..."):
        tracking = logging_agent.generate_tracking_schema(blueprint, llm)
    cfg.paths.tracking_schema.write_text(tracking.model_dump_json(indent=2))
    cfg.paths.spec_doc.write_text(logging_agent.render_spec_doc(blueprint, tracking))
    cfg.paths.snippets_dir.mkdir(parents=True, exist_ok=True)
    for fname, content in logging_agent.render_snippets(tracking).items():
        (cfg.paths.snippets_dir / fname).write_text(content)
    return tracking


def _ingest_events(cfg: Config, state: WorkflowState, blueprint, tracking):
    """Load events from the configured source (simulated preview or a real file)."""
    from .adapters.source import source_from_config
    from .core.duckdb_runner import DuckDBRunner

    source = source_from_config(
        state.source or {"kind": "simulated"}, blueprint, tracking,
        default_seed=cfg.seed, default_effect=cfg.effect_size,
    )
    runner = DuckDBRunner(cfg.paths.db)
    with _working(f"Loading events from the {source.kind} source..."):
        n = source.load(runner)
    return runner, n


def _do_pipeline(cfg: Config, llm, blueprint, tracking):
    from .agents import pipeline_agent
    from .core.duckdb_runner import DuckDBRunner

    runner = DuckDBRunner(cfg.paths.db)
    if not runner.table_exists("raw_events"):
        runner.close()
        raise GateError("No events ingested yet. Run 'verify-instrumentation' first.")
    with _working("Writing the SQL and testing it against your data (it retries until it runs)..."):
        sql, attempts = pipeline_agent.build_metrics_model(
            runner, blueprint, tracking, llm, max_attempts=cfg.max_fix_attempts, console=console
        )
    cfg.paths.models_dir.mkdir(parents=True, exist_ok=True)
    (cfg.paths.models_dir / "metrics_daily.sql").write_text(sql)
    runner.close()
    return sql, attempts


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _evaluate(cfg: Config, blueprint, tracking, state: WorkflowState):
    """Open the DB, compute corrected stats, and build the run context. Returns an open runner."""
    from .core import stats
    from .core.duckdb_runner import DuckDBRunner
    from .core.provenance import build_run_context
    from .core.state import STAGE_ORDER

    runner = DuckDBRunner(cfg.paths.db)
    if not runner.table_exists("metrics_daily"):
        runner.close()
        raise GateError("No metrics_daily table yet. Run 'build' first.")
    results = stats.evaluate_all(runner, blueprint, tracking)
    stats.apply_holm(results)  # correct for testing primary + guardrails together
    approvals = {s: state.stage(s).approver for s in STAGE_ORDER if state.stage(s).approver}
    ctx = build_run_context(
        state.source, results, blueprint,
        generated_at=_utc_now(), prd_hash=state.prd_hash, approvals=approvals,
    )
    return runner, results, ctx


def _do_readout(cfg: Config, llm, blueprint, tracking, state: WorkflowState) -> str:
    """The one-off launch decision document, READOUT.md."""
    from datetime import date

    from .agents import readout_agent

    runner, results, ctx = _evaluate(cfg, blueprint, tracking, state)
    runner.close()
    date_label = date.today().isoformat()
    window_label = f"{state.launch_date or 'n/a'} to {date_label}"
    stakeholders = ", ".join(sorted({v for v in ctx.approvals.values() if v})) or "PM, Eng, Data Science"
    with _working("Writing the launch readout..."):
        full = readout_agent.generate_readout(
            blueprint, results, ctx, llm,
            date_label=date_label, window_label=window_label, stakeholders=stakeholders,
        )
    cfg.paths.readout_doc.write_text(full)
    return full


def _do_pulse(cfg: Config, blueprint, tracking, state: WorkflowState) -> str:
    """The recurring monitoring document, DAILY_PULSE.md (deterministic, no LLM)."""
    from .agents import pulse_agent
    from .core import charts, health

    runner, results, ctx = _evaluate(cfg, blueprint, tracking, state)
    chart_text = charts.render_all(runner, blueprint)
    runner.close()
    alerts = []
    if blueprint.health_metrics and (state.source or {}).get("kind") == "simulated":
        series = health.simulate_health(
            blueprint.health_metrics, horizon_days=blueprint.experiment.horizon_days, seed=cfg.seed
        )
        alerts = health.detect_regressions(series, blueprint.health_metrics)
    full = pulse_agent.generate_pulse(blueprint, results, alerts, chart_text, ctx, generated_at=_utc_now())
    cfg.paths.report.write_text(full)
    return full


# --------------------------------------------------------------------------- #
# init
# --------------------------------------------------------------------------- #
@app.command()
def init(workdir: Path = typer.Option(Path.cwd(), "--workdir", "-w", help="Where to scaffold.")):
    """Set up a folder: a sample PRD, a guided .env, and the workflow state."""
    from importlib.resources import files

    cfg = Config.load(workdir=workdir)
    cfg.paths.ensure()
    sample = (files("prd_to_readout.samples") / "sample_prd.md").read_text()
    prd_path = cfg.workdir / "prd.md"
    if prd_path.exists():
        console.print(f"[yellow]prd.md already exists at {prd_path}, leaving it alone.[/]")
    else:
        prd_path.write_text(sample)
        _banner(f"Wrote a sample PRD to {prd_path}")

    env_path = cfg.workdir / ".env"
    if not env_path.exists():
        env_path.write_text(FRIENDLY_ENV)
        _banner(f"Wrote {env_path}")
    else:
        console.print("[yellow].env already exists, leaving it alone.[/]")

    state = _state(cfg)
    _save(state, cfg)

    # Re-load so the freshly written .env is reflected, then guide the user.
    cfg = Config.load(workdir=workdir)
    console.print("\n[bold]Setup[/]")
    _print_model_status(cfg)
    console.print("\n[bold]Next steps[/]")
    console.print(f"  1. Edit your PRD: [bold]{prd_path}[/]  (or keep the sample to try it out)")
    from .config import model_status
    if not model_status(cfg.model).key_present:
        console.print(f"  2. Add your API key to [bold]{env_path}[/]  (see the comments in that file)")
        console.print("  3. Run it:  [bold]prd-to-readout run prd.md[/]")
    else:
        console.print("  2. Run it:  [bold]prd-to-readout run prd.md[/]")
    console.print("\n[dim]Tip: 'prd-to-readout run prd.md --yes --preview' shows the whole flow on sample data.[/]")


# --------------------------------------------------------------------------- #
# status
# --------------------------------------------------------------------------- #
_STATUS_STYLE = {
    "pending": "dim", "awaiting_approval": "yellow", "approved": "green",
    "changes_requested": "red", "done": "bold green",
}


@app.command()
def status(workdir: Path = typer.Option(Path.cwd(), "--workdir", "-w")):
    """Show the workflow board: where each stage is and what to do next."""
    cfg = Config.load(workdir=workdir)
    if not cfg.paths.state.exists():
        console.print("[yellow]No workflow yet.[/] Run 'prd-to-readout init' or 'hypothesize <prd>'.")
        raise typer.Exit(0)
    state = _state(cfg)
    table = Table(title=f"prd-to-readout: {state.feature}", show_lines=False)
    table.add_column("Stage", style="bold")
    table.add_column("Status")
    table.add_column("Approver")
    table.add_column("Updated", style="dim")
    for i, name in enumerate(STAGE_ORDER, 1):
        st = state.stage(name)
        style = _STATUS_STYLE.get(st.status, "white")
        table.add_row(
            f"{i}. {STAGE_TITLES.get(name, name)}",
            f"[{style}]{st.status}[/]",
            st.approver or "",
            (st.updated_at or "").replace("T", " ").replace("+00:00", "Z"),
        )
    console.print(table)
    _print_model_status(cfg)
    _hint(state)


# --------------------------------------------------------------------------- #
# stage 1: hypothesize
# --------------------------------------------------------------------------- #
@app.command()
@handle_errors
def hypothesize(
    prd: Path = typer.Argument(..., exists=True, readable=True, help="Path to the PRD markdown."),
    workdir: Path = typer.Option(Path.cwd(), "--workdir", "-w"),
    model: str | None = typer.Option(None, "--model", "-m"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Auto-approve this stage's gate."),
):
    """Stage 1: PRD -> analytics_blueprint.yaml (then review & approve)."""
    cfg = _config(workdir, model, None)
    _require_model(cfg)
    cfg.paths.ensure()
    state = _state(cfg)
    prd_text = prd.read_text()
    state.prd_path = str(prd)
    state.prd_hash = hashlib.sha256(prd_text.encode()).hexdigest()[:12]

    bp = _do_hypothesis(cfg, _llm(cfg), prd_text)
    state.feature = bp.feature_name
    console.print(f"  primary metric: [cyan]{bp.primary_metric.name}[/]  "
                  f"guardrails: {', '.join(m.name for m in bp.guardrail_metrics) or 'none'}")
    console.print(f"  → {cfg.paths.blueprint}")
    _finish_stage(cfg, state, "hypothesis", [cfg.paths.blueprint], yes=yes)
    _hint(state)


# --------------------------------------------------------------------------- #
# stage 2: spec
# --------------------------------------------------------------------------- #
@app.command()
@handle_errors
def spec(
    workdir: Path = typer.Option(Path.cwd(), "--workdir", "-w"),
    model: str | None = typer.Option(None, "--model", "-m"),
    yes: bool = typer.Option(False, "--yes", "-y"),
):
    """Stage 2: blueprint -> tracking spec + snippets, handed off to an engineer."""
    cfg = _config(workdir, model, None)
    state = _state(cfg)
    workflow.ensure_can_run(state, "instrumentation")
    _require_model(cfg)
    blueprint = _load_blueprint(cfg)
    tracking = _do_spec(cfg, _llm(cfg), blueprint)
    console.print(f"  {len(tracking.events)} events → {cfg.paths.tracking_schema}")
    console.print(f"  engineer deliverable → {cfg.paths.spec_doc}, snippets/")
    _finish_stage(cfg, state, "instrumentation", [cfg.paths.spec_doc, cfg.paths.tracking_schema], yes=yes)
    _hint(state)


# --------------------------------------------------------------------------- #
# stage 3: verify-instrumentation  (Phase 4 makes the checks real)
# --------------------------------------------------------------------------- #
@app.command(name="verify-instrumentation")
@handle_errors
def verify_instrumentation(
    source: Path | None = typer.Option(
        None, "--source", "-s", help="Real events file (csv/parquet/json/jsonl). Omit for the simulated preview."
    ),
    simulate: bool = typer.Option(False, "--simulate", help="Force the simulated preview source."),
    force: bool = typer.Option(False, "--force", help="Advance even if QA fails."),
    workdir: Path = typer.Option(Path.cwd(), "--workdir", "-w"),
    yes: bool = typer.Option(False, "--yes", "-y"),
):
    """Stage 3: ingest events from the source and verify they match the spec."""
    from .core import instrumentation_qa

    cfg = _config(workdir, None, None)
    state = _state(cfg)
    workflow.ensure_can_run(state, "instrumentation_qa")
    blueprint = _load_blueprint(cfg)
    tracking = _load_tracking(cfg)

    if source is not None:
        state.source = {"kind": "file", "path": str(source)}
    elif simulate:
        state.source = {"kind": "simulated", "seed": cfg.seed, "effect": cfg.effect_size}

    runner, n = _ingest_events(cfg, state, blueprint, tracking)
    console.print(f"  ingested [cyan]{n}[/] events from source '{state.source.get('kind')}'")
    report = instrumentation_qa.run_qa(runner, blueprint, tracking)
    cfg.paths.qa_report.write_text(instrumentation_qa.render_qa_report(report, blueprint))
    runner.close()

    for c in report.checks:
        mark = "[green]✓[/]" if c.passed else ("[yellow]![/]" if not c.critical else "[red]✗[/]")
        console.print(f"  {mark} {c.name}" + (f"  [dim]{c.detail}[/]" if c.detail else ""))

    if not report.passed and not force:
        workflow.request_changes(state, "instrumentation_qa",
                                 note="QA failed; fix instrumentation or re-run with --force")
        _save(state, cfg)
        console.print(f"[bold red]Instrumentation QA failed.[/] See {cfg.paths.qa_report}")
        raise typer.Exit(1)

    # Data is flowing: this is the launch. The launch readout opens window_days later.
    if state.launch_date is None:
        from datetime import date
        state.launch_date = date.today().isoformat()
        console.print(f"  launch date set to [cyan]{state.launch_date}[/]; "
                      f"readout due in {state.readout_window_days} days")
    _finish_stage(cfg, state, "instrumentation_qa", [cfg.paths.qa_report, cfg.paths.db], yes=yes)
    _hint(state)


# --------------------------------------------------------------------------- #
# stage 4: build
# --------------------------------------------------------------------------- #
@app.command()
@handle_errors
def build(
    workdir: Path = typer.Option(Path.cwd(), "--workdir", "-w"),
    model: str | None = typer.Option(None, "--model", "-m"),
    yes: bool = typer.Option(False, "--yes", "-y"),
):
    """Stage 4: author + self-correct the aggregation SQL, then hand to a DS to review."""
    cfg = _config(workdir, model, None)
    state = _state(cfg)
    workflow.ensure_can_run(state, "pipeline")
    _require_model(cfg)
    blueprint = _load_blueprint(cfg)
    tracking = _load_tracking(cfg)
    sql, attempts = _do_pipeline(cfg, _llm(cfg), blueprint, tracking)
    console.print(f"  SQL passed after [cyan]{attempts}[/] attempt(s) → models/metrics_daily.sql")
    _finish_stage(cfg, state, "pipeline", [cfg.paths.models_dir / "metrics_daily.sql"], yes=yes)
    _hint(state)


# --------------------------------------------------------------------------- #
# stage 5: readout
# --------------------------------------------------------------------------- #
def _window_status(state: WorkflowState, window_days: int | None) -> tuple[bool, str]:
    from datetime import date

    w = window_days if window_days is not None else state.readout_window_days
    if not state.launch_date:
        return False, "launch date unknown (run verify-instrumentation first)"
    days = (date.today() - date.fromisoformat(state.launch_date)).days
    return days >= w, f"{days} of {w} days since launch ({state.launch_date})"


@app.command()
@handle_errors
def readout(
    workdir: Path = typer.Option(Path.cwd(), "--workdir", "-w"),
    model: str | None = typer.Option(None, "--model", "-m"),
    window_days: int | None = typer.Option(None, "--window-days", help="Override the readout window (default 14)."),
    force: bool = typer.Option(False, "--force", help="Generate now even if the window isn't reached."),
):
    """Stage 5: the one-off Launch Readout (READOUT.md), the ship/kill/iterate decision.

    Due at the launch window (two weeks post-launch by default). Use 'pulse' for
    ongoing monitoring before then.
    """
    cfg = _config(workdir, model, None)
    state = _state(cfg)
    workflow.ensure_can_run(state, "readout")
    if window_days is not None:
        state.readout_window_days = window_days
    blueprint = _load_blueprint(cfg)
    tracking = _load_tracking(cfg)

    if not force:
        ok, msg = _window_status(state, window_days)
        if not ok:
            console.print(f"[yellow]Launch readout not due yet:[/] {msg}.")
            console.print("Monitor with [bold]prd-to-readout pulse[/], or pass --force to generate now.")
            raise typer.Exit(0)

    _require_model(cfg)
    full = _do_readout(cfg, _llm(cfg), blueprint, tracking, state)
    _do_pulse(cfg, blueprint, tracking, state)  # refresh the monitor alongside the decision
    _finish_stage(cfg, state, "readout", [cfg.paths.readout_doc])
    console.print(Panel(Markdown(full), title="READOUT.md", border_style="green"))
    _hint(state)


@app.command()
@handle_errors
def pulse(workdir: Path = typer.Option(Path.cwd(), "--workdir", "-w")):
    """Recurring monitor: regenerate DAILY_PULSE.md (adoption + engagement + health).

    Cheap and deterministic (no LLM). Run it daily; schedule with 'schedule'.
    """
    cfg = _config(workdir, None, None)
    state = _state(cfg)
    if state.stage("pipeline").status not in ("approved", "done"):
        raise GateError("Approve 'build' before monitoring with pulse.")
    blueprint = _load_blueprint(cfg)
    tracking = _load_tracking(cfg)
    full = _do_pulse(cfg, blueprint, tracking, state)
    console.print(Panel(Markdown(full), title="DAILY_PULSE.md", border_style="cyan"))


# --------------------------------------------------------------------------- #
# gates: approve / request-changes
# --------------------------------------------------------------------------- #
def _resolve_stage(name: str) -> str:
    if name in STAGE_ORDER:  # exact match wins (e.g. 'instrumentation' vs 'instrumentation_qa')
        return name
    matches = [s for s in STAGE_ORDER if s.startswith(name)]
    if len(matches) != 1:
        raise typer.BadParameter(f"'{name}' is not a unique stage. Choose one of: {', '.join(STAGE_ORDER)}")
    return matches[0]


@app.command()
def approve(
    stage: str = typer.Argument(..., help=f"One of: {', '.join(STAGE_ORDER)}"),
    by: str = typer.Option("", "--by", help="Who is approving (for the audit trail)."),
    note: str = typer.Option("", "--note", "-n"),
    workdir: Path = typer.Option(Path.cwd(), "--workdir", "-w"),
):
    """Approve a stage's gate so the next stage can run."""
    cfg = Config.load(workdir=workdir)
    state = _state(cfg)
    name = _resolve_stage(stage)
    workflow.approve(state, name, by=by or None, note=note or None)
    _save(state, cfg)
    _banner(f"Approved '{name}'" + (f" by {by}" if by else ""))
    _hint(state)


@app.command(name="request-changes")
def request_changes(
    stage: str = typer.Argument(..., help=f"One of: {', '.join(STAGE_ORDER)}"),
    note: str = typer.Option(..., "--note", "-n", help="What needs to change."),
    by: str = typer.Option("", "--by"),
    workdir: Path = typer.Option(Path.cwd(), "--workdir", "-w"),
):
    """Send a stage back for rework."""
    cfg = Config.load(workdir=workdir)
    state = _state(cfg)
    name = _resolve_stage(stage)
    workflow.request_changes(state, name, by=by or None, note=note)
    _save(state, cfg)
    _banner(f"Requested changes on '{name}': {note}")
    _hint(state)


# --------------------------------------------------------------------------- #
# GitHub-native gates: gh-setup + sync
# --------------------------------------------------------------------------- #
def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-") or "prd-to-readout"


@app.command(name="gh-setup")
@handle_errors
def gh_setup(
    repo: str | None = typer.Option(None, "--repo", help="owner/name or name (default: the feature slug)."),
    create: bool = typer.Option(False, "--create", help="Create a new PRIVATE GitHub repo."),
    workdir: Path = typer.Option(Path.cwd(), "--workdir", "-w"),
):
    """Enable GitHub-native gates: create/select a private repo and assign approvers.

    Approver handles come from the PRD (blueprint). Any that are missing are asked
    for here before proceeding.
    """
    from .adapters.github import GitHubClient, GitHubError

    cfg = Config.load(workdir=workdir)
    state = _state(cfg)
    try:
        owner = GitHubClient.whoami()
    except GitHubError as e:
        raise GateError(str(e)) from None

    blueprint = _load_blueprint(cfg) if cfg.paths.blueprint.exists() else None
    approvers = _resolve_approvers(blueprint, state, interactive=True)

    name = repo or _slug(state.feature)
    if create:
        full = GitHubClient.create_private_repo(name)
        _banner(f"Created private repo {full}")
    else:
        full = name if "/" in name else f"{owner}/{name}"

    client = GitHubClient(full)
    for role, handle in approvers.items():
        if not handle:
            console.print(f"  [yellow]no handle for {role} approver[/]")
            continue
        if not client.user_exists(handle):
            console.print(f"  [yellow]warning: @{handle} not found on GitHub[/]")
            continue
        try:
            client.add_collaborator(handle)
            console.print(f"  invited [cyan]@{handle}[/] ({role})")
        except GitHubError as e:
            console.print(f"  [yellow]could not add @{handle}: {e}[/]")

    state.github = {"repo": full, "approvers": approvers}
    _save(state, cfg)
    _banner(f"GitHub gates enabled on {full}")
    console.print("Approvers must accept the repo invite. Gates now open issues; "
                  "run [bold]prd-to-readout sync[/] to pull their decisions.")


@app.command()
@handle_errors
def sync(workdir: Path = typer.Option(Path.cwd(), "--workdir", "-w")):
    """Pull gate decisions from GitHub issues into the local workflow."""
    from .adapters.github import GATE_ROLE, GitHubError, evaluate_issue

    cfg = Config.load(workdir=workdir)
    state = _state(cfg)
    client = _github_client(state)
    if client is None:
        raise GateError("No GitHub repo configured. Run 'prd-to-readout gh-setup' first.")

    changed = []
    for stage in STAGE_ORDER:
        st = state.stage(stage)
        if st.status != "awaiting_approval" or not st.issue_number:
            continue
        approver = (state.github.get("approvers") or {}).get(GATE_ROLE.get(stage, ""), "")
        try:
            issue = client.get_issue(st.issue_number)
        except GitHubError as e:
            console.print(f"  [yellow]#{st.issue_number}: {e}[/]")
            continue
        decision, note = evaluate_issue(issue, approver)
        if decision == "approved":
            workflow.approve(state, stage, by=approver or "github", note="via GitHub issue")
            try:
                client.close_issue(st.issue_number, comment="Approved via prd-to-readout. Gate cleared.")
            except GitHubError:
                pass
            changed.append(f"{stage}: approved by @{approver or 'github'}")
        elif decision == "changes_requested":
            workflow.request_changes(state, stage, by=approver or "github", note=note)
            changed.append(f"{stage}: changes requested ({note})")

    _save(state, cfg)
    if changed:
        for c in changed:
            _banner(c)
    else:
        console.print("No gate changes from GitHub.")
    _hint(state)


# --------------------------------------------------------------------------- #
# run: walk the stages, stopping at each gate unless --yes
# --------------------------------------------------------------------------- #
@app.command()
@handle_errors
def run(
    prd: Path = typer.Argument(..., exists=True, readable=True, help="Path to the PRD markdown."),
    workdir: Path = typer.Option(Path.cwd(), "--workdir", "-w"),
    model: str | None = typer.Option(None, "--model", "-m"),
    seed: int | None = typer.Option(None, "--seed"),
    effect: float = typer.Option(0.15, "--effect", help="Simulated lift (preview source)."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Auto-approve every gate."),
    preview: bool = typer.Option(False, "--preview", help="Use the simulated source (no real data)."),
):
    """Walk the whole workflow. Stops at each human gate unless --yes."""
    cfg = _config(workdir, model, seed)
    _require_model(cfg)
    cfg.effect_size = effect
    cfg.paths.ensure()
    state = _state(cfg)
    if preview or not state.source:
        state.source = {"kind": "simulated", "seed": cfg.seed, "effect": effect}
    llm = _llm(cfg)

    prd_text = prd.read_text()
    state.prd_path = str(prd)
    state.prd_hash = hashlib.sha256(prd_text.encode()).hexdigest()[:12]

    steps = [
        ("hypothesis", [cfg.paths.blueprint]),
        ("instrumentation", [cfg.paths.spec_doc, cfg.paths.tracking_schema]),
        ("instrumentation_qa", [cfg.paths.db]),
        ("pipeline", [cfg.paths.models_dir / "metrics_daily.sql"]),
        ("readout", [cfg.paths.readout_doc]),
    ]
    for stage, artifacts in steps:
        if state.stage(stage).status in ("approved", "done"):
            continue
        try:
            workflow.ensure_can_run(state, stage)
        except GateError as e:
            console.print(f"[yellow]Paused:[/] {e}")
            _save(state, cfg)
            _hint(state)
            return

        _banner(f"Stage: {STAGE_TITLES[stage]}")
        full = None
        if stage == "hypothesis":
            state.feature = _do_hypothesis(cfg, llm, prd_text).feature_name
        elif stage == "instrumentation":
            _do_spec(cfg, llm, _load_blueprint(cfg))
        elif stage == "instrumentation_qa":
            from datetime import date

            from .core import instrumentation_qa
            bp, tr = _load_blueprint(cfg), _load_tracking(cfg)
            runner, n = _ingest_events(cfg, state, bp, tr)
            qa = instrumentation_qa.run_qa(runner, bp, tr)
            cfg.paths.qa_report.write_text(instrumentation_qa.render_qa_report(qa, bp))
            runner.close()
            console.print(f"  ingested [cyan]{n}[/] events; QA {'passed' if qa.passed else 'FAILED'}")
            if not qa.passed:
                workflow.request_changes(state, "instrumentation_qa", note="QA failed")
                _save(state, cfg)
                console.print(f"[bold red]Paused:[/] instrumentation QA failed. See {cfg.paths.qa_report}")
                _hint(state)
                return
            if state.launch_date is None:
                state.launch_date = date.today().isoformat()
        elif stage == "pipeline":
            _, attempts = _do_pipeline(cfg, llm, _load_blueprint(cfg), _load_tracking(cfg))
            console.print(f"  SQL passed after {attempts} attempt(s)")
        elif stage == "readout":
            full = _do_readout(cfg, llm, _load_blueprint(cfg), _load_tracking(cfg), state)
            _do_pulse(cfg, _load_blueprint(cfg), _load_tracking(cfg), state)

        status_now = _finish_stage(cfg, state, stage, artifacts, yes=yes)
        if full is not None:
            console.print(Panel(Markdown(full), title="READOUT.md", border_style="green"))
        if status_now == "awaiting_approval":
            console.print(f"[yellow]Gate:[/] '{stage}' needs approval before continuing.")
            _hint(state)
            return

    _banner("Workflow complete.")
    _hint(state)


# --------------------------------------------------------------------------- #
# misc
# --------------------------------------------------------------------------- #
@app.command()
def feedback(
    vote: str = typer.Argument(..., help="up / down"),
    note: str = typer.Option("", "--note", "-n"),
    workdir: Path = typer.Option(Path.cwd(), "--workdir", "-w"),
):
    """Capture thumbs up/down on the latest readout to refine future context."""
    cfg = Config.load(workdir=workdir)
    cfg.paths.pulse_dir.mkdir(parents=True, exist_ok=True)
    vote_norm = "up" if vote.lower() in {"up", "+", "👍", "good"} else "down"
    with cfg.paths.feedback.open("a") as f:
        f.write(json.dumps({"vote": vote_norm, "note": note}) + "\n")
    _banner(f"Recorded 👍 ({vote_norm}). Thanks." if vote_norm == "up"
            else f"Recorded 👎 ({vote_norm}). Note saved.")


@app.command()
def schedule(
    cron: str = typer.Option("0 9 * * *", "--cron", help="Cron expression (default: 9am daily)."),
    workdir: Path = typer.Option(Path.cwd(), "--workdir", "-w"),
):
    """Print a cron/launchd snippet to refresh the monitor on a schedule.

    Schedules the recurring 'pulse' (adoption + health monitoring). The one-off
    launch readout is generated once, at the window, via 'readout'.
    """
    wd = workdir.resolve()
    cron_line = f"{cron} cd {wd} && prd-to-readout pulse -w {wd} >> {wd}/.pulse/pulse.log 2>&1"
    console.print("[bold]Add to your crontab[/] (run 'crontab -e'):\n")
    console.print(f"  {cron_line}\n")
    console.print("[dim]The launch readout is one-off: run 'prd-to-readout readout' at the 2-week window.[/]")
    console.print("[dim]On macOS you can also use launchd; see docs/scheduling.md.[/]")


@app.command()
def version():
    """Print the version."""
    console.print(f"prd-to-readout {__version__}")


if __name__ == "__main__":
    app()
