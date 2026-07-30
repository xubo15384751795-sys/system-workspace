from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from scripts import roadmap_progress as progress
from system_cli.app import build_parser

ROOT = Path(__file__).resolve().parents[1]


def _definition() -> dict:
    return yaml.safe_load(
        (ROOT / "governance" / "progress" / "validation_roadmap.yaml").read_text(
            encoding="utf-8"
        )
    )


def _events() -> list[dict]:
    return [
        json.loads(line)
        for line in (
            ROOT / "governance" / "progress" / "validation_progress_events.jsonl"
        )
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]


def test_live_progress_definition_and_events_validate() -> None:
    roadmap = _definition()
    events = _events()

    snapshot = progress.build_snapshot(roadmap, events)

    assert len(snapshot["tasks"]) == 9
    assert 0 < snapshot["overall_completion_pct"] < 100
    assert snapshot["remaining_pct"] == pytest.approx(
        100 - snapshot["overall_completion_pct"]
    )
    assert set(snapshot["phase_completion_pct"]) == {"P0", "P1", "P2"}


def test_completion_is_derived_from_criterion_statuses() -> None:
    roadmap = _definition()
    events = _events()
    snapshot = progress.build_snapshot(roadmap, events)
    p0_4 = next(task for task in snapshot["tasks"] if task["id"] == "P0-4")

    # satisfied: 10 + 10 + 15; in_progress contributes 50% of 15.
    assert p0_4["completion_pct"] == 42.5
    assert p0_4["state"] == "CI_GREEN"
    assert len(p0_4["blockers"]) == 3


def test_illegal_transition_is_rejected() -> None:
    roadmap = _definition()
    events = _events()
    bad = {
        "schema_version": progress.EVENT_SCHEMA,
        "event_id": "illegal-close",
        "occurred_at": "2026-07-30T16:00:00Z",
        "task_id": "P0-4",
        "event_type": "transition",
        "from_state": "CI_GREEN",
        "to_state": "CLOSED",
        "actor": "test",
        "reason": "must not skip operational evidence",
        "criterion_updates": {},
    }

    with pytest.raises(progress.RoadmapProgressError, match="illegal transition"):
        progress.validate_events(roadmap, [*events, bad])


def test_unknown_criterion_is_rejected() -> None:
    roadmap = _definition()
    events = _events()
    bad = {
        "schema_version": progress.EVENT_SCHEMA,
        "event_id": "unknown-criterion",
        "occurred_at": "2026-07-30T16:00:00Z",
        "task_id": "P1-1",
        "event_type": "transition",
        "from_state": "READY",
        "to_state": "IN_PROGRESS",
        "actor": "test",
        "reason": "bad update",
        "criterion_updates": {"made_up": "satisfied"},
    }

    with pytest.raises(progress.RoadmapProgressError, match="unknown criteria"):
        progress.validate_events(roadmap, [*events, bad])


def test_append_transition_writes_one_valid_event(tmp_path: Path) -> None:
    roadmap = _definition()
    events = _events()
    target = tmp_path / "events.jsonl"

    event = progress.append_transition(
        roadmap,
        events,
        task_id="P1-1",
        to_state="IN_PROGRESS",
        reason="Begin isolated PIT work.",
        actor="test",
        evidence=["https://example.test/evidence"],
        criterion_updates={"date_semantics": "satisfied"},
        blockers=[],
        next_gate="Build PIT fixtures.",
        commit_sha="abc123",
        path=target,
    )

    written = json.loads(target.read_text(encoding="utf-8"))
    assert written == event
    progress.validate_events(roadmap, [*events, event])


def test_markdown_contains_summary_blockers_and_update_command() -> None:
    snapshot = progress.build_snapshot(_definition(), _events())
    markdown = progress.render_markdown(snapshot)

    assert "# Project Validation Progress" in markdown
    assert "Overall completion" in markdown
    assert "P0-4 Freshness 与监控闭环" in markdown
    assert "12 current artifacts are stale" in markdown
    assert "./sys roadmap" in markdown


def test_committed_human_view_matches_generated_snapshot() -> None:
    snapshot = progress.build_snapshot(_definition(), _events())
    committed = (ROOT / "PROJECT_PROGRESS.md").read_text(encoding="utf-8")

    assert committed == progress.render_markdown(snapshot)


def test_system_cli_registers_roadmap_command() -> None:
    args = build_parser().parse_args(["roadmap"])
    assert args.command == "roadmap"
    assert args.arguments == []
