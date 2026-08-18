from __future__ import annotations

import json
import sys
from types import SimpleNamespace

from system_runtime import observability as obs


def test_sentry_message_trace_redacts_urls_and_credentials(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _Scope:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def set_tag(self, key, value):
            captured.setdefault("tags", {})[key] = value

    fake_sentry = SimpleNamespace(
        init=lambda **_kwargs: None,
        push_scope=lambda: _Scope(),
        capture_message=lambda message, *, level: captured.update(
            message=message, level=level
        ),
    )
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake_sentry)
    monkeypatch.setattr(obs, "_SENTRY_INITIALIZED", False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("OBSERVABILITY_DISABLE", raising=False)
    monkeypatch.delenv("NOTIFY_DISABLE", raising=False)
    monkeypatch.setenv("SENTRY_DSN", "https://example@sentry.invalid/1")

    obs.capture_message(
        "failure https://private.example/?token=secret-value",
        tags={"token": "secret-value", "run": "daily"},
    )

    assert "secret-value" not in str(captured)
    assert "private.example" not in str(captured)
    assert captured["level"] == "error"
    assert captured["tags"] == {
        "run": "daily",
    }


def test_observability_attribute_allowlist_drops_payload_and_unknown_keys() -> None:
    safe = obs._sanitize_tags(
        {
            "run-id": "daily-001",
            "market_payload": '{"SPY": 1.0}',
            "token": "secret-value",
            "url": "https://private.example/path?token=secret-value",
        }
    )
    assert safe == {"run_id": "daily-001"}


def test_sentry_exception_trace_redacts_credentials(monkeypatch) -> None:
    captured: dict[str, object] = {}
    fake_sentry = SimpleNamespace(
        init=lambda **_kwargs: None,
        capture_exception=lambda exc: captured.update(exception=exc),
    )
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake_sentry)
    monkeypatch.setattr(obs, "_SENTRY_INITIALIZED", False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("OBSERVABILITY_DISABLE", raising=False)
    monkeypatch.delenv("NOTIFY_DISABLE", raising=False)
    monkeypatch.setenv("SENTRY_DSN", "https://example@sentry.invalid/1")

    obs.capture_exception(RuntimeError("authorization=secret-value"))

    assert "secret-value" not in str(captured["exception"])


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


def test_emit_alert_disabled_by_notify_switch(monkeypatch) -> None:
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("NOTIFY_DISABLE", "1")
    monkeypatch.setenv("DD_API_KEY", "must-not-send")
    monkeypatch.setenv("SENTRY_DSN", "https://example@sentry.invalid/1")

    result = obs.emit_alert("t", "m")

    assert result == {"sentry": False, "datadog": False}


def test_disabled_observability_makes_no_remote_call(monkeypatch) -> None:
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("OBSERVABILITY_DISABLE", "1")
    monkeypatch.setenv("DD_API_KEY", "must-not-send")
    def fail_remote_call(*_args, **_kwargs):
        raise AssertionError("remote call")

    monkeypatch.setattr(obs, "OwnedExternalHTTPGateway", fail_remote_call)

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
        status_code = 202

    class _Gateway:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, endpoint_id, content, *, headers, timeout_sec):
            captured["endpoint_id"] = endpoint_id
            captured["headers"] = dict(headers)
            captured["body"] = json.loads(content.decode("utf-8"))
            captured["timeout_sec"] = timeout_sec
            return _Resp()

    monkeypatch.setattr(obs, "OwnedExternalHTTPGateway", lambda _endpoints: _Gateway())
    result = obs.emit_alert(
        "Daily failed https://private.example/?token=secret-value",
        "step token=secret-value",
        tags={"run": "daily", "token": "secret-value"},
    )
    assert result["datadog"] is True
    assert captured["endpoint_id"] == "datadog_events"
    assert captured["body"]["title"] == "Daily failed [redacted-url]"
    assert "service:structural-risk-workbench" in captured["body"]["tags"]
    assert "run:daily" in captured["body"]["tags"]
    assert "secret-value" not in json.dumps(captured["body"])


def test_exporter_failure_is_visible_without_leaking_exception(monkeypatch, caplog) -> None:
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("DD_API_KEY", "test-key")
    monkeypatch.setenv("DD_SITE", "datadoghq.com")
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.delenv("OBSERVABILITY_DISABLE", raising=False)

    class _Gateway:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            raise obs.ExternalGatewayError("sink failure")

    monkeypatch.setattr(obs, "OwnedExternalHTTPGateway", lambda _endpoints: _Gateway())
    with caplog.at_level("WARNING", logger=obs.logger.name):
        result = obs.emit_alert("title", "message")

    assert result["datadog"] is False
    assert "datadog event failed: ExternalGatewayError" in caplog.text
    assert "sink failure" not in caplog.text
