from prd_to_readout.adapters import notify


def test_console_notifier_always_succeeds(capsys):
    ok = notify.ConsoleNotifier().send(
        notify.Notification("pipeline", "data scientist", "SQL ready", "review it", ["x.sql"])
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
    n = notify.Notification("pipeline", "ds", "SQL ready", "review", ["models/metrics_daily.sql"])
    ok = notify.SlackNotifier("https://hooks.slack.test/abc").send(n)
    assert ok
    assert captured["url"] == "https://hooks.slack.test/abc"
    assert "metrics_daily.sql" in captured["data"].decode()


def test_slack_failure_does_not_raise(monkeypatch):
    def boom(req, timeout=10):
        raise OSError("network down")

    monkeypatch.setattr(notify.urllib.request, "urlopen", boom)
    ok = notify.SlackNotifier("https://x").send(notify.Notification("pipeline", "ds", "t", "a"))
    assert ok is False  # swallowed, workflow continues


def test_build_notifier_selects_channels():
    assert len(notify.build_notifier({}).channels) == 1  # console only
    m = notify.build_notifier({"P2R_SLACK_WEBHOOK": "https://x"})
    assert any(isinstance(c, notify.SlackNotifier) for c in m.channels)
    m2 = notify.build_notifier({"P2R_SMTP_HOST": "smtp.x", "P2R_EMAIL_TO": "a@b.c"})
    assert any(isinstance(c, notify.EmailNotifier) for c in m2.channels)


def test_gate_notification_routes_to_right_human():
    eng = notify.gate_notification("instrumentation", ["LOGGING_SPEC.md"])
    assert eng.audience == "engineer"
    assert "approve instrumentation" in eng.action
    ds = notify.gate_notification("pipeline", ["metrics_daily.sql"])
    assert ds.audience == "data scientist"
