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
