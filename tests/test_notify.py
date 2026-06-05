from prd_to_readout.adapters import notify


def test_console_notifier_always_succeeds(capsys):
    ok = notify.ConsoleNotifier().send(
        notify.Notification("query", "data scientist", "SQL ready", "review it", ["x.sql"])
    )
    assert ok
    assert "data scientist" in capsys.readouterr().out


def test_slack_notifier_posts_payload(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=10):
        captured["url"] = req.full_url
        captured["data"] = req.data
        return object()

    monkeypatch.setattr(notify.urllib.request, "urlopen", fake_urlopen)
    n = notify.Notification("query", "ds", "SQL ready", "review", ["models/metrics_daily.sql"])
    ok = notify.SlackNotifier("https://hooks.slack.test/abc").send(n)
    assert ok
    assert captured["url"] == "https://hooks.slack.test/abc"
    assert "metrics_daily.sql" in captured["data"].decode()


def test_slack_failure_does_not_raise(monkeypatch):
    def boom(req, timeout=10):
        raise OSError("network down")

    monkeypatch.setattr(notify.urllib.request, "urlopen", boom)
    ok = notify.SlackNotifier("https://x").send(notify.Notification("query", "ds", "t", "a"))
    assert ok is False  # swallowed, workflow continues


def test_multinotifier_calls_every_channel_even_after_failure():
    # A failing channel must not suppress the ones after it (all() short-circuits).
    calls = []

    class Recording:
        def __init__(self, name, ok):
            self.name, self.ok = name, ok

        def send(self, n):
            calls.append(self.name)
            return self.ok

    m = notify.MultiNotifier([Recording("slack", False), Recording("email", True)])
    overall = m.send(notify.Notification("query", "ds", "t", "a"))
    assert calls == ["slack", "email"]   # email still called despite slack failing
    assert overall is False              # but the aggregate reports the failure


def test_build_notifier_selects_channels():
    assert len(notify.build_notifier({}).channels) == 1  # console only
    m = notify.build_notifier({"P2R_SLACK_WEBHOOK": "https://x"})
    assert any(isinstance(c, notify.SlackNotifier) for c in m.channels)
    m2 = notify.build_notifier({"P2R_SMTP_HOST": "smtp.x", "P2R_EMAIL_TO": "a@b.c"})
    assert any(isinstance(c, notify.EmailNotifier) for c in m2.channels)


def test_gate_notification_routes_to_right_human():
    eng = notify.gate_notification("logging", ["LOGGING_SPEC.md"])
    assert eng.audience == "engineer"
    assert "approve logging" in eng.action
    ds = notify.gate_notification("query", ["metrics_daily.sql"])
    assert ds.audience == "data scientist"
