from __future__ import annotations

import json

from scripts import _notify


def test_webhook_uses_owned_external_gateway(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _Response:
        status_code = 202

    class _Gateway:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, endpoint_id, content, *, headers, timeout_sec):
            captured["endpoint_id"] = endpoint_id
            captured["content"] = content
            captured["headers"] = headers
            captured["timeout_sec"] = timeout_sec
            return _Response()

    monkeypatch.setenv("NOTIFY_WEBHOOK_URL", "https://hooks.example.test/events")
    monkeypatch.setattr(_notify, "OwnedExternalHTTPGateway", lambda _endpoints: _Gateway())

    assert _notify._notify_webhook("title", "message") is True
    assert captured["endpoint_id"] == "notification_webhook"
    assert captured["headers"] == {"Content-Type": "application/json"}


def test_webhook_rejects_query_bearing_configuration(monkeypatch) -> None:
    monkeypatch.setenv("NOTIFY_WEBHOOK_URL", "https://hooks.example.test/events?token=secret")
    assert _notify._notify_webhook("title", "message") is False


def test_feishu_webhook_uses_native_text_payload(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _Response:
        status_code = 200

    class _Gateway:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, endpoint_id, content, *, headers, timeout_sec):
            captured["endpoint_id"] = endpoint_id
            captured["body"] = json.loads(content.decode("utf-8"))
            captured["headers"] = headers
            captured["timeout_sec"] = timeout_sec
            return _Response()

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv(
        "FEISHU_WEBHOOK_URL",
        "https://open.feishu.cn/open-apis/bot/v2/hook/test",
    )
    monkeypatch.setattr(_notify, "_suppression_reason", lambda: None)
    monkeypatch.setattr(_notify, "OwnedExternalHTTPGateway", lambda _endpoints: _Gateway())

    assert _notify.notify_feishu("title", "message") is True
    assert captured["endpoint_id"] == "feishu_webhook"
    assert captured["body"] == {
        "msg_type": "text",
        "content": {"text": "title\nmessage"},
    }


def test_telegram_uses_bot_api_payload(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _Response:
        status_code = 200

    class _Gateway:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, endpoint_id, content, *, headers, timeout_sec):
            captured["endpoint_id"] = endpoint_id
            captured["body"] = json.loads(content.decode("utf-8"))
            captured["headers"] = headers
            captured["timeout_sec"] = timeout_sec
            return _Response()

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123456789")
    monkeypatch.setattr(_notify, "_suppression_reason", lambda: None)
    monkeypatch.setattr(_notify, "OwnedExternalHTTPGateway", lambda _endpoints: _Gateway())

    assert _notify.notify_telegram("title", "message") is True
    assert captured["endpoint_id"] == "telegram_bot"
    assert captured["body"] == {
        "chat_id": "123456789",
        "text": "title\nmessage",
        "disable_web_page_preview": True,
    }


def test_daily_summary_prefers_telegram_sink(monkeypatch) -> None:
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(_notify, "_suppression_reason", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123456789")
    monkeypatch.setattr(
        _notify,
        "_notify_telegram",
        lambda title, message: sent.append((title, message)) or True,
    )

    assert _notify.notify_daily_run_summary(
        status="success",
        outcome={
            "run_id": "daily-001",
            "exit_code": 0,
            "publish_status": "COMMITTED",
        },
    ) is True
    assert sent[0][0] == "System daily_run 运行摘要"
    assert "run_id=daily-001" in sent[0][1]


def test_notification_redacts_urls_and_credentials_before_sinks(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _Response:
        status_code = 202

    class _Gateway:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, _endpoint_id, content, **_kwargs):
            captured["content"] = content
            return _Response()

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("NOTIFY_DISABLE", raising=False)
    monkeypatch.setenv("NOTIFY_WEBHOOK_URL", "https://hooks.example.test/events")
    monkeypatch.setattr(_notify, "_notify_observability", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(_notify, "_notify_desktop", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(_notify, "OwnedExternalHTTPGateway", lambda _endpoints: _Gateway())

    assert _notify.notify_failure(
        "failure https://private.example/?token=secret-value",
        "authorization=Bearer secret-value",
    ) is True
    body = captured["content"].decode("utf-8")
    assert "secret-value" not in body
    assert "private.example" not in body


def test_no_deviation_has_zero_side_effect(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        _notify,
        "notify_failure",
        lambda title, message, **_kw: calls.append((title, message)),
    )
    assert _notify.notify_deviations("health", []) is False
    assert calls == []


def test_deviation_is_compacted_and_reported(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        _notify,
        "notify_failure",
        lambda title, message, **_kw: calls.append((title, message)) or True,
    )
    assert _notify.notify_deviations("health", ["a", "b", "c", "d"]) is True
    assert calls == [("health", "a; b; c; +1 more")]


def test_daily_run_notification_uses_outcome_failure_without_failed_steps(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        _notify,
        "notify_deviations",
        lambda title, deviations, **_kw: calls.append((title, "; ".join(deviations))) or True,
    )

    _notify.notify_daily_run_result(
        status="success",
        failed_steps=[],
        warnings=[],
        outcome={
            "run_id": "blocked-late-admission",
            "exit_code": 4,
            "admission_verdict": "BLOCK",
            "publish_status": "NOT_PUBLISHED",
        },
    )

    assert calls == [
        (
            "System daily_run failed",
            "outcome; exit_code=4; admission=BLOCK; publish=NOT_PUBLISHED",
        )
    ]


class TestNotificationSandboxGuard:
    """Pipeline steps are exercised against sandbox fixtures. The notification
    must not escape into the operator's real notification centre carrying
    fixture dates — two callable-e2e tests were firing "Content freshness
    STALE / etf_panel behind=1118d" alerts on every full test run, burying
    genuine alerts.
    """

    def test_suppressed_under_pytest(self, monkeypatch, capsys) -> None:
        sent: list[tuple[str, str]] = []
        monkeypatch.setattr(
            _notify, "_notify_desktop", lambda t, m: sent.append((t, m)) or True
        )
        monkeypatch.setattr(
            _notify, "_notify_webhook", lambda t, m: sent.append((t, m)) or True
        )
        # pytest sets this for the duration of each test.
        assert _notify.notify_failure("Content freshness STALE", "etf_panel") is False
        assert sent == []
        # Suppressed, not swallowed.
        assert "NOTIFY[suppressed:pytest]" in capsys.readouterr().err

    def test_explicit_disable_env(self, monkeypatch, capsys) -> None:
        sent: list[tuple[str, str]] = []
        monkeypatch.setattr(
            _notify, "_notify_desktop", lambda t, m: sent.append((t, m)) or True
        )
        monkeypatch.setattr(
            _notify, "_notify_webhook", lambda t, m: sent.append((t, m)) or True
        )
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.setenv("NOTIFY_DISABLE", "1")
        assert _notify.notify_failure("t", "m") is False
        assert sent == []
        assert "NOTIFY[suppressed:NOTIFY_DISABLE]" in capsys.readouterr().err

    def test_explicit_disable_blocks_observability(self, monkeypatch) -> None:
        calls: list[tuple[str, str]] = []
        from system_runtime import observability

        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.setenv("NOTIFY_DISABLE", "1")
        monkeypatch.setattr(
            observability,
            "emit_alert",
            lambda title, message, **_kw: calls.append((title, message)),
        )

        _notify._notify_observability("t", "m")

        assert calls == []

    def test_sends_when_not_suppressed(self, monkeypatch) -> None:
        """The guard must not disable real operator notifications."""
        sent: list[tuple[str, str]] = []
        monkeypatch.setattr(
            _notify, "_notify_desktop", lambda t, m: sent.append((t, m)) or True
        )
        monkeypatch.setattr(_notify, "_notify_webhook", lambda t, m: False)
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("NOTIFY_DISABLE", raising=False)
        assert _notify.notify_failure("real alert", "ofr_fsi behind=17d") is True
        assert sent == [("real alert", "ofr_fsi behind=17d")]
