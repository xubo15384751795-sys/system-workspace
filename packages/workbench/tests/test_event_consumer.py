"""Tests for agents.harness.events.event_consumer.

Tests the consumption protocol: cursor tracking, event reading, dispatch.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.harness.events.event_consumer import (
    consume_and_dispatch,
    consume_new_events,
    dispatch_events,
)


# ── helpers ─────────────────────────────────────────────────────────────

def _write_event(events_dir: Path, date_str: str, events: list[dict]) -> None:
    """Write one or more JSONL event lines to an event file."""
    file_path = events_dir / f"events_{date_str}.jsonl"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("a", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")


def _make_event(etype: str = "tool_run", severity: str = "info", **kw) -> dict:
    return {
        "event_id": "test-id",
        "event_type": etype,
        "severity": severity,
        "timestamp": "2026-05-10T10:00:00Z",
        "subsystem": "test",
        "tool_id": "test_tool",
        "mode": "explore",
        "decision": "allow",
        "result": "pass",
        **kw,
    }


# ── consume_new_events ──────────────────────────────────────────────────

class TestConsumeNewEvents:
    def test_empty_dir_returns_empty_list(self, tmp_path):
        events_dir = tmp_path / "events"
        events_dir.mkdir()
        result = consume_new_events(events_dir=events_dir)
        assert result == []

    def test_reads_events_from_single_file(self, tmp_path):
        events_dir = tmp_path / "events"
        events_dir.mkdir()
        _write_event(events_dir, "2026-05-10", [
            _make_event(etype="tool_run"),
            _make_event(etype="permission_decision"),
        ])
        result = consume_new_events(events_dir=events_dir)
        assert len(result) == 2
        assert result[0]["event_type"] == "tool_run"
        assert result[1]["event_type"] == "permission_decision"

    def test_cursor_skips_already_read_events(self, tmp_path):
        events_dir = tmp_path / "events"
        events_dir.mkdir()
        _write_event(events_dir, "2026-05-10", [
            _make_event(etype="tool_run"),
        ])
        # First read — consumes the event
        first = consume_new_events(events_dir=events_dir)
        assert len(first) == 1
        # Second read — no new events
        second = consume_new_events(events_dir=events_dir)
        assert second == []

    def test_reset_re_reads_all_events(self, tmp_path):
        events_dir = tmp_path / "events"
        events_dir.mkdir()
        _write_event(events_dir, "2026-05-10", [
            _make_event(etype="tool_run"),
        ])
        consume_new_events(events_dir=events_dir)  # consume
        reset = consume_new_events(reset=True, events_dir=events_dir)
        assert len(reset) == 1

    def test_new_events_after_cursor(self, tmp_path):
        events_dir = tmp_path / "events"
        events_dir.mkdir()
        _write_event(events_dir, "2026-05-10", [
            _make_event(etype="tool_run"),
        ])
        consume_new_events(events_dir=events_dir)  # consume first
        # Append a second event
        _write_event(events_dir, "2026-05-10", [
            _make_event(etype="permission_decision"),
        ])
        second = consume_new_events(events_dir=events_dir)
        assert len(second) == 1
        assert second[0]["event_type"] == "permission_decision"

    def test_multiple_daily_files(self, tmp_path):
        events_dir = tmp_path / "events"
        events_dir.mkdir()
        _write_event(events_dir, "2026-05-09", [
            _make_event(etype="tool_run"),
        ])
        _write_event(events_dir, "2026-05-10", [
            _make_event(etype="hook_deny"),
        ])
        result = consume_new_events(events_dir=events_dir)
        assert len(result) == 2

    def test_malformed_line_skipped(self, tmp_path):
        events_dir = tmp_path / "events"
        events_dir.mkdir()
        path = events_dir / "events_2026-05-10.jsonl"
        path.write_text('{"event_type": "good"}\nnot-json\n{"event_type": "also_good"}\n', encoding="utf-8")
        result = consume_new_events(events_dir=events_dir)
        assert len(result) == 2


# ── dispatch_events ─────────────────────────────────────────────────────

class TestDispatchEvents:
    def test_empty_list(self):
        result = dispatch_events([])
        assert result["total"] == 0
        assert result["by_type"] == {}

    def test_groups_by_type(self):
        events = [
            _make_event(etype="tool_run"),
            _make_event(etype="tool_run"),
            _make_event(etype="hook_deny"),
        ]
        result = dispatch_events(events)
        assert result["by_type"]["tool_run"] == 2
        assert result["by_type"]["hook_deny"] == 1

    def test_groups_by_severity(self):
        events = [
            _make_event(severity="info"),
            _make_event(severity="warning"),
            _make_event(severity="warning"),
        ]
        result = dispatch_events(events)
        assert result["by_severity"]["info"] == 1
        assert result["by_severity"]["warning"] == 2

    def test_subsystem_filter(self):
        events = [
            _make_event(etype="tool_run", subsystem="alpha"),
            _make_event(etype="tool_run", subsystem="beta"),
        ]
        result = dispatch_events(events, subsystem_filter="alpha")
        assert result["total"] == 1

    def test_min_severity_filter(self):
        events = [
            _make_event(severity="info"),
            _make_event(severity="warning"),
            _make_event(severity="error"),
        ]
        result = dispatch_events(events, min_severity="warning")
        assert result["total"] == 2


# ── consume_and_dispatch ────────────────────────────────────────────────

class TestConsumeAndDispatch:
    def test_no_events_returns_message(self, tmp_path):
        events_dir = tmp_path / "events"
        events_dir.mkdir()
        result = consume_and_dispatch(events_dir=events_dir)
        assert "No new events" in result.get("message", "")

    def test_full_pipeline(self, tmp_path):
        events_dir = tmp_path / "events"
        events_dir.mkdir()
        _write_event(events_dir, "2026-05-10", [
            _make_event(etype="tool_run", subsystem="alpha"),
            _make_event(etype="hook_deny", subsystem="beta", severity="warning"),
        ])
        result = consume_and_dispatch(events_dir=events_dir)
        assert result["events_consumed"] == 2
        assert result["by_type"]["tool_run"] == 1
        assert result["by_type"]["hook_deny"] == 1
