"""Notification adapters: how the workflow hands off to humans at a gate.

Notifications ARE the handoff mechanism (the engineer gets the spec, the DS gets
the SQL to review). Reference channels use only the stdlib (urllib for Slack
webhooks, smtplib for email); a console echo always fires so nothing is silent.
New channels (GitHub, Linear, PagerDuty) implement the same `Notifier` protocol.
"""

from __future__ import annotations

import json
import os
import smtplib
import urllib.request
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol, runtime_checkable

from rich.console import Console

_console = Console()


@dataclass
class Notification:
    stage: str
    audience: str           # who needs to act, e.g. "engineer", "data scientist"
    title: str
    action: str             # the human action requested
    artifacts: list[str] = field(default_factory=list)

    def as_text(self) -> str:
        arts = "\n".join(f"  - {a}" for a in self.artifacts) or "  (none)"
        return (
            f"[prd-to-readout] {self.title}\n"
            f"For: {self.audience}\n"
            f"Action: {self.action}\n"
            f"Artifacts:\n{arts}"
        )


@runtime_checkable
class Notifier(Protocol):
    def send(self, n: Notification) -> bool: ...


class ConsoleNotifier:
    """Always-on echo so a gate is never silent, even with no channel configured."""

    def send(self, n: Notification) -> bool:
        _console.print(
            f"[bold cyan]🔔 Handoff →[/] [bold]{n.audience}[/]: {n.title}\n"
            f"   [dim]{n.action}[/]"
        )
        for a in n.artifacts:
            _console.print(f"   [dim]• {a}[/]")
        return True


class SlackNotifier:
    """POST to a Slack incoming webhook (P2R_SLACK_WEBHOOK)."""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(self, n: Notification) -> bool:
        payload = json.dumps({"text": n.as_text()}).encode()
        req = urllib.request.Request(
            self.webhook_url, data=payload, headers={"Content-Type": "application/json"}
        )
        try:
            urllib.request.urlopen(req, timeout=10)  # noqa: S310 - user-provided webhook
            return True
        except Exception as e:  # noqa: BLE001 - notifications must never break the workflow
            _console.print(f"[yellow]Slack notification failed:[/] {e}")
            return False


class EmailNotifier:
    """Send via SMTP (P2R_SMTP_HOST/PORT/USER/PASSWORD, P2R_EMAIL_FROM/TO)."""

    def __init__(self, host: str, port: int, user: str, password: str, sender: str, to: str):
        self.host, self.port, self.user, self.password = host, port, user, password
        self.sender, self.to = sender, to

    def send(self, n: Notification) -> bool:
        msg = EmailMessage()
        msg["Subject"] = f"[prd-to-readout] {n.title}"
        msg["From"] = self.sender
        msg["To"] = self.to
        msg.set_content(n.as_text())
        try:
            with smtplib.SMTP(self.host, self.port, timeout=15) as s:
                s.starttls()
                if self.user:
                    s.login(self.user, self.password)
                s.send_message(msg)
            return True
        except Exception as e:  # noqa: BLE001
            _console.print(f"[yellow]Email notification failed:[/] {e}")
            return False


class MultiNotifier:
    """Fan out to every configured channel (console always included)."""

    def __init__(self, channels: list[Notifier]):
        self.channels = channels

    def send(self, n: Notification) -> bool:
        # Materialize first: all(generator) short-circuits, which would skip every
        # channel after one that fails (a Slack outage must not drop the email).
        results = [c.send(n) for c in self.channels]
        return all(results)


def build_notifier(env: dict | None = None) -> MultiNotifier:
    """Assemble notifier from the environment: console + Slack and/or email if configured."""
    env = env if env is not None else os.environ
    channels: list[Notifier] = [ConsoleNotifier()]
    if env.get("P2R_SLACK_WEBHOOK"):
        channels.append(SlackNotifier(env["P2R_SLACK_WEBHOOK"]))
    if env.get("P2R_SMTP_HOST") and env.get("P2R_EMAIL_TO"):
        channels.append(
            EmailNotifier(
                host=env["P2R_SMTP_HOST"],
                port=int(env.get("P2R_SMTP_PORT", 587)),
                user=env.get("P2R_SMTP_USER", ""),
                password=env.get("P2R_SMTP_PASSWORD", ""),
                sender=env.get("P2R_EMAIL_FROM", env.get("P2R_SMTP_USER", "prd-to-readout@localhost")),
                to=env["P2R_EMAIL_TO"],
            )
        )
    return MultiNotifier(channels)


# Per-gate message templates: stage -> (audience, title, action).
_GATE_MESSAGES = {
    "metric": ("PM / data scientist", "Metric plan ready for review",
                   "Read METRIC_PLAN.md, then: prd-to-readout approve metric"),
    "logging": ("engineer", "Logging spec ready to implement",
                        "Implement the events in LOGGING_SPEC.md, ship them, then: prd-to-readout approve logging"),
    "logging_qa": ("data scientist", "Logging QA complete",
                           "Review LOGGING_QA.md, then: prd-to-readout approve logging_qa"),
    "query": ("data scientist", "Aggregation SQL ready for review",
                 "Review models/metrics_daily.sql for correctness, then: prd-to-readout approve query"),
    "readout": ("stakeholders", "Readout published",
                "See DAILY_PULSE.md for the latest results."),
}


def gate_notification(stage: str, artifacts: list[str]) -> Notification:
    audience, title, action = _GATE_MESSAGES[stage]
    return Notification(stage=stage, audience=audience, title=title, action=action, artifacts=artifacts)
