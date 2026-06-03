"""prd-to-readout command line interface.

The pipeline is a stateful, gated workflow. Each stage runs, writes its
artifacts, and parks at a human gate (approve / request-changes) unless --yes.
`status` shows the board; `run` walks the stages but stops at each gate.
"""

from __future__ import annotations

import functools
import hashlib
import json
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


def _state(cfg: Config) -> WorkflowState:
    feature = (cfg.workdir / "prd.md").stem if (cfg.workdir / "prd.md").exists() else cfg.workdir.name
    return WorkflowState.load_or_new(cfg.paths.state, feature)


def _save(state: WorkflowState, cfg: Config) -> None:
    state.save(cfg.paths.state)


def _hint(state: WorkflowState) -> None:
    console.print(f"\n[dim]Next:[/] {workflow.next_action(state)}")


def _finish_stage(cfg: Config, state: WorkflowState, stage: str, artifacts, *, yes: bool = False) -> str:
    """Complete a stage, persist state, and fire the handoff notification at the gate."""
    from .adapters.notify import build_notifier, gate_notification

    arts = [str(a) for a in artifacts]
    status_now = workflow.complete_stage(state, stage, arts, auto_yes=yes)
    _save(state, cfg)
    if status_now in ("awaiting_approval", "done"):
        build_notifier().send(gate_notification(stage, arts))
    return status_now


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

    bp = hypothesis_agent.generate_blueprint(prd_text, llm)
    cfg.paths.ensure()
    cfg.paths.blueprint.write_text(bp.to_yaml())
    return bp


def _do_spec(cfg: Config, llm, blueprint):
    from .agents import logging_agent

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
    n = source.load(runner)
    return runner, n


def _do_pipeline(cfg: Config, llm, blueprint, tracking):
    from .agents import pipeline_agent
    from .core.duckdb_runner import DuckDBRunner

    runner = DuckDBRunner(cfg.paths.db)
    if not runner.table_exists("raw_events"):
        runner.close()
        raise GateError("No events ingested yet. Run 'verify-instrumentation' first.")
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
    """Drop a sample PRD + .env template and initialize the workflow state."""
    from importlib.resources import files

    cfg = Config.load(workdir=workdir)
    cfg.paths.ensure()
    sample = (files("prd_to_readout.samples") / "sample_prd.md").read_text()
    prd_path = cfg.workdir / "prd.md"
    if prd_path.exists():
        console.print(f"[yellow]prd.md already exists at {prd_path}, leaving it alone.[/]")
    else:
        prd_path.write_text(sample)
        _banner(f"Wrote sample PRD to {prd_path}")
    env_path = cfg.workdir / ".env.example"
    if not env_path.exists():
        env_path.write_text("P2R_MODEL=claude-sonnet-4-6\nP2R_SEED=42\nANTHROPIC_API_KEY=sk-ant-...\n")
        _banner(f"Wrote {env_path}  (copy to .env and add your key)")
    state = _state(cfg)
    _save(state, cfg)
    console.print("\nNext: [bold]prd-to-readout hypothesize prd.md[/]   (or 'run prd.md')")


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
