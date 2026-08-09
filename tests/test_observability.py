from __future__ import annotations

import json

from system_runtime import observability as obs


def test_emit_alert_noop_without_credentials(monkeypatch) -> None:
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.delenv("DD_API_KEY", raising=False)
    monkeypatch.delenv("OBSERVABILITY_DISABLE", raising=False)
    result = obs.emit_alert("t", "m", severity="error")
    assert result == {"sentry": False, "datadog": False}


def test_emit_alert_disabled_explicitly(monkeypatch) -> None:
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("OBSERVABILITY_DISABLE", "1")
    monkeypatch.setenv("SENTRY_DSN", "https://example@sentry.invalid/1")
    result = obs.emit_alert("t", "m")
    assert result == {"sentry": False, "datadog": False}


def test_datadog_event_posts_payload(monkeypatch) -> None:
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("DD_API_KEY", "test-key")
    monkeypatch.setenv("DD_SITE", "datadoghq.com")
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.delenv("OBSERVABILITY_DISABLE", raising=False)

    captured: dict = {}

    class _Resp:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(req, timeout=5):  # noqa: ARG001
        captured["url"] = req.full_url
        captured["headers"] = dict(req.headers)
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _Resp()

    monkeypatch.setattr(obs.urllib.request, "urlopen", fake_urlopen)
    result = obs.emit_alert("Daily failed", "step X", tags={"run": "daily"})
    assert result["datadog"] is True
    assert "api.datadoghq.com" in captured["url"]
    assert captured["body"]["title"] == "Daily failed"
    assert "service:structural-risk-workbench" in captured["body"]["tags"]
    assert "run:daily" in captured["body"]["tags"]
