from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from scripts import test_sentry_event as command
from system_runtime import observability as obs


def test_sentry_event_writes_sanitized_receipt(tmp_path: Path, monkeypatch) -> None:
    fake_sentry = SimpleNamespace(
        init=lambda **_kwargs: None,
        capture_exception=lambda _exc: None,
        flush=lambda **_kwargs: None,
        last_event_id=lambda: "event-123",
    )
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake_sentry)
    monkeypatch.setattr(obs, "_SENTRY_INITIALIZED", False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("OBSERVABILITY_DISABLE", raising=False)
    monkeypatch.delenv("NOTIFY_DISABLE", raising=False)
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.invalid/1")
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "test")

    receipt = tmp_path / "sentry-event.json"
    assert command.main(["--receipt", str(receipt)]) == 0

    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "system.sentry_event_receipt.v1"
    assert payload["event_id"] == "event-123"
    assert datetime.fromisoformat(payload["sent_at"]).tzinfo is not None
    assert payload["environment"] == "test"
    assert payload["source"] == "scripts.test_sentry_event"
    assert "example.invalid" not in receipt.read_text(encoding="utf-8")
