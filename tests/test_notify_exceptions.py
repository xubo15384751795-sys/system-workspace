from __future__ import annotations

from scripts import _notify


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
