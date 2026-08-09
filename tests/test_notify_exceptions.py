from __future__ import annotations

from scripts import _notify


def test_no_deviation_has_zero_side_effect(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(_notify, "notify_failure", lambda title, message: calls.append((title, message)))
    assert _notify.notify_deviations("health", []) is False
    assert calls == []


def test_deviation_is_compacted_and_reported(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        _notify,
        "notify_failure",
        lambda title, message: calls.append((title, message)) or True,
    )
    assert _notify.notify_deviations("health", ["a", "b", "c", "d"]) is True
    assert calls == [("health", "a; b; c; +1 more")]


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


def test_daily_run_hard_alert_is_deduplicated_until_recovery(monkeypatch, tmp_path, capsys) -> None:
    state = tmp_path / "daily_notification_state.json"
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(_notify, "_DAILY_NOTIFICATION_STATE", state)
    monkeypatch.setattr(
        _notify,
        "notify_deviations",
        lambda title, deviations: sent.append((title, "; ".join(deviations))) or True,
    )

    kwargs = {
        "status": "partial_failure",
        "failed_steps": [],
        "warnings": ["PUBLISH_BLOCKED: stale_artifacts=1"],
        "content_stale": ["etf_panel max=2026-08-03 behind=4d"],
        "publish_blocked": "stale_artifacts=1",
    }
    _notify.notify_daily_run_result(**kwargs)
    _notify.notify_daily_run_result(**kwargs)
    assert len(sent) == 1
    assert "deduplicated" in capsys.readouterr().err

    _notify.notify_daily_run_result(
        status="success",
        failed_steps=[],
        warnings=[],
        harvester_completed=True,
    )
    _notify.notify_daily_run_result(**kwargs)
    assert len(sent) == 2


def test_downstream_only_run_does_not_clear_hard_alert(monkeypatch, tmp_path) -> None:
    state = tmp_path / "daily_notification_state.json"
    monkeypatch.setattr(_notify, "_DAILY_NOTIFICATION_STATE", state)
    monkeypatch.setattr(_notify, "notify_deviations", lambda *_args: True)
    kwargs = {
        "status": "partial_failure",
        "failed_steps": ["harvester"],
        "warnings": [],
    }

    _notify.notify_daily_run_result(**kwargs)
    assert state.exists()

    _notify.notify_daily_run_result(
        status="success",
        failed_steps=[],
        warnings=["soft_fail:monitoring"],
        harvester_completed=False,
    )
    assert state.exists()

    _notify.notify_daily_run_result(
        status="success",
        failed_steps=[],
        warnings=[],
        harvester_completed=True,
    )
    assert not state.exists()
