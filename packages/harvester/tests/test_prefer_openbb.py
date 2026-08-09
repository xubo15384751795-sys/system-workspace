from __future__ import annotations

from harvester.official import order_provider_priority, prefer_openbb


def test_prefer_openbb_force_off(monkeypatch) -> None:
    monkeypatch.setenv("HARVESTER_PREFER_OPENBB", "0")
    assert prefer_openbb() is False
    assert order_provider_priority(["fred", "openbb_fred"]) == ["fred", "openbb_fred"]


def test_prefer_openbb_force_on(monkeypatch) -> None:
    monkeypatch.setenv("HARVESTER_PREFER_OPENBB", "1")
    assert prefer_openbb() is True
    assert order_provider_priority(["fred", "openbb_fred", "cboe_direct"]) == [
        "openbb_fred",
        "fred",
        "cboe_direct",
    ]


def test_prefer_openbb_auto_without_openbb(monkeypatch) -> None:
    monkeypatch.setenv("HARVESTER_PREFER_OPENBB", "auto")
    import builtins

    real_import = builtins.__import__

    def blocker(name, *args, **kwargs):
        if name == "openbb" or name.startswith("openbb."):
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocker)
    assert prefer_openbb() is False
