#!/usr/bin/env python3
"""Validate and render the repository-wide validation roadmap progress ledger."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from verity.runtime.runtime_io import ROOT

ROADMAP_PATH = ROOT / "governance" / "progress" / "validation_roadmap.yaml"
EVENTS_PATH = ROOT / "governance" / "progress" / "validation_progress_events.jsonl"
HUMAN_VIEW_PATH = ROOT / "PROJECT_PROGRESS.md"

EVENT_SCHEMA = "validation_progress_event.v1"
CRITERION_STATUSES = frozenset(
    {"not_started", "in_progress", "satisfied", "blocked", "failed"}
)


class RoadmapProgressError(ValueError):
    """Raised when roadmap definitions or progress events violate the contract."""


def load_roadmap(path: Path = ROADMAP_PATH) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RoadmapProgressError("roadmap must be a mapping")
    return data


def load_events(path: Path = EVENTS_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RoadmapProgressError(f"invalid JSON on event line {line_no}: {exc}") from exc
        if not isinstance(event, dict):
            raise RoadmapProgressError(f"event line {line_no} must be an object")
        events.append(event)
    return events


def _task_map(roadmap: dict[str, Any]) -> dict[str, dict[str, Any]]:
    tasks = roadmap.get("tasks", [])
    if not isinstance(tasks, list):
        raise RoadmapProgressError("tasks must be a list")
    by_id: dict[str, dict[str, Any]] = {}
    for task in tasks:
        task_id = str(task.get("id", ""))
        if not task_id or task_id in by_id:
            raise RoadmapProgressError(f"invalid or duplicate task id: {task_id!r}")
        by_id[task_id] = task
    return by_id


def validate_definition(roadmap: dict[str, Any]) -> None:
    if roadmap.get("schema_version") != "validation_roadmap.v1":
        raise RoadmapProgressError("unsupported roadmap schema")
    states = set(roadmap.get("states", []))
    transitions = roadmap.get("transitions", {})
    if not states or set(transitions) != states:
        raise RoadmapProgressError("transitions must define every state exactly once")
    for source, targets in transitions.items():
        unknown = set(targets) - states
        if unknown:
            raise RoadmapProgressError(f"{source} has unknown transition targets: {sorted(unknown)}")

    factors = roadmap.get("criterion_status_factors", {})
    if set(factors) != CRITERION_STATUSES:
        raise RoadmapProgressError("criterion_status_factors must define all criterion statuses")
    if any(not 0 <= float(value) <= 1 for value in factors.values()):
        raise RoadmapProgressError("criterion status factors must be between 0 and 1")

    tasks = _task_map(roadmap)
    overall_weight = sum(float(task.get("overall_weight", 0)) for task in tasks.values())
    if abs(overall_weight - 100) > 1e-9:
        raise RoadmapProgressError(f"task overall weights must sum to 100, got {overall_weight}")
    for task_id, task in tasks.items():
        criteria = task.get("criteria", [])
        criterion_ids = [str(item.get("id", "")) for item in criteria]
        if not criterion_ids or len(set(criterion_ids)) != len(criterion_ids):
            raise RoadmapProgressError(f"{task_id} has invalid criterion ids")
        weight = sum(float(item.get("weight", 0)) for item in criteria)
        if abs(weight - 100) > 1e-9:
            raise RoadmapProgressError(f"{task_id} criterion weights must sum to 100, got {weight}")


def validate_events(roadmap: dict[str, Any], events: list[dict[str, Any]]) -> None:
    tasks = _task_map(roadmap)
    states = set(roadmap["states"])
    transitions = roadmap["transitions"]
    seen_event_ids: set[str] = set()
    task_states: dict[str, str] = {}
    last_timestamp = ""

    for index, event in enumerate(events, start=1):
        event_id = str(event.get("event_id", ""))
        if not event_id or event_id in seen_event_ids:
            raise RoadmapProgressError(f"event {index} has missing or duplicate event_id")
        seen_event_ids.add(event_id)
        if event.get("schema_version") != EVENT_SCHEMA:
            raise RoadmapProgressError(f"{event_id} has unsupported schema")
        timestamp = str(event.get("occurred_at", ""))
        try:
            datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise RoadmapProgressError(f"{event_id} has invalid occurred_at") from exc
        if timestamp < last_timestamp:
            raise RoadmapProgressError("events must be ordered by occurred_at")
        last_timestamp = timestamp

        task_id = str(event.get("task_id", ""))
        if task_id not in tasks:
            raise RoadmapProgressError(f"{event_id} references unknown task {task_id}")
        if not str(event.get("actor", "")).strip():
            raise RoadmapProgressError(f"{event_id} must record an actor")
        if not str(event.get("reason", "")).strip():
            raise RoadmapProgressError(f"{event_id} must record a reason")
        if not isinstance(event.get("evidence", []), list):
            raise RoadmapProgressError(f"{event_id} evidence must be a list")
        if "blockers" in event and not isinstance(event["blockers"], list):
            raise RoadmapProgressError(f"{event_id} blockers must be a list")
        to_state = str(event.get("to_state", ""))
        if to_state not in states:
            raise RoadmapProgressError(f"{event_id} has unknown to_state {to_state}")
        event_type = event.get("event_type")
        current = task_states.get(task_id)
        if current is None:
            if event_type != "bootstrap" or event.get("from_state") is not None:
                raise RoadmapProgressError(f"{event_id} must bootstrap the task from null")
        else:
            if event_type == "evidence":
                if event.get("from_state") != current or to_state != current:
                    raise RoadmapProgressError(
                        f"{event_id} evidence must preserve current state {current}"
                    )
                if not event.get("evidence"):
                    raise RoadmapProgressError(f"{event_id} evidence event must cite evidence")
            elif event_type == "transition":
                if event.get("from_state") != current:
                    raise RoadmapProgressError(f"{event_id} from_state does not match current {current}")
                if to_state not in transitions[current]:
                    raise RoadmapProgressError(f"illegal transition for {task_id}: {current} -> {to_state}")
            else:
                raise RoadmapProgressError(f"{event_id} has unsupported event_type {event_type!r}")
        task_states[task_id] = to_state

        criterion_ids = {str(item["id"]) for item in tasks[task_id]["criteria"]}
        updates = event.get("criterion_updates", {})
        if not isinstance(updates, dict):
            raise RoadmapProgressError(f"{event_id} criterion_updates must be a mapping")
        unknown_criteria = set(updates) - criterion_ids
        if unknown_criteria:
            raise RoadmapProgressError(f"{event_id} has unknown criteria: {sorted(unknown_criteria)}")
        invalid_statuses = set(updates.values()) - CRITERION_STATUSES
        if invalid_statuses:
            raise RoadmapProgressError(f"{event_id} has invalid criterion statuses")


def build_snapshot(roadmap: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    validate_definition(roadmap)
    validate_events(roadmap, events)
    tasks = _task_map(roadmap)
    factors = {key: float(value) for key, value in roadmap["criterion_status_factors"].items()}
    state: dict[str, dict[str, Any]] = {}

    for task_id, task in tasks.items():
        state[task_id] = {
            "id": task_id,
            "title": task["title"],
            "phase": task["phase"],
            "owner": task["owner"],
            "roadmap_section": task["roadmap_section"],
            "overall_weight": float(task["overall_weight"]),
            "state": "PLANNED",
            "criteria": {
                str(item["id"]): {
                    "id": str(item["id"]),
                    "title": item["title"],
                    "weight": float(item["weight"]),
                    "status": "not_started",
                }
                for item in task["criteria"]
            },
            "blockers": [],
            "next_gate": "",
            "last_event_id": None,
            "last_updated": None,
            "evidence": [],
        }

    for event in events:
        current = state[event["task_id"]]
        current["state"] = event["to_state"]
        current["last_event_id"] = event["event_id"]
        current["last_updated"] = event["occurred_at"]
        if "blockers" in event:
            current["blockers"] = list(event["blockers"])
        if "next_gate" in event:
            current["next_gate"] = str(event["next_gate"])
        current["evidence"].extend(
            item for item in event.get("evidence", []) if item not in current["evidence"]
        )
        for criterion_id, status in event.get("criterion_updates", {}).items():
            current["criteria"][criterion_id]["status"] = status

    overall = 0.0
    phase_totals: dict[str, dict[str, float]] = {}
    for current in state.values():
        completion = sum(
            criterion["weight"] * factors[criterion["status"]]
            for criterion in current["criteria"].values()
        )
        current["completion_pct"] = round(completion, 1)
        overall += current["overall_weight"] * completion / 100
        phase = phase_totals.setdefault(current["phase"], {"weight": 0.0, "weighted": 0.0})
        phase["weight"] += current["overall_weight"]
        phase["weighted"] += current["overall_weight"] * completion / 100

    phases = {
        phase: round(values["weighted"] / values["weight"] * 100, 1)
        for phase, values in sorted(phase_totals.items())
    }
    latest = max((event["occurred_at"] for event in events), default=None)
    return {
        "schema_version": "validation_progress_snapshot.v1",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source_latest_event_at": latest,
        "overall_completion_pct": round(overall, 1),
        "remaining_pct": round(100 - overall, 1),
        "phase_completion_pct": phases,
        "tasks": list(state.values()),
    }


def render_markdown(snapshot: dict[str, Any]) -> str:
    lines = [
        "# Project Validation Progress",
        "",
        "> Generated from `governance/progress/validation_roadmap.yaml` and the append-only "
        "`governance/progress/validation_progress_events.jsonl` ledger. "
        "Do not edit percentages here.",
        "",
        f"- Overall completion: **{snapshot['overall_completion_pct']:.1f}%**",
        f"- Remaining: **{snapshot['remaining_pct']:.1f}%**",
        f"- Latest evidence event: `{snapshot['source_latest_event_at'] or 'none'}`",
        "",
        "## Phase summary",
        "",
        "| Phase | Completion |",
        "|---|---:|",
    ]
    for phase, completion in snapshot["phase_completion_pct"].items():
        lines.append(f"| {phase} | {completion:.1f}% |")

    lines.extend(
        [
            "",
            "## Workstreams",
            "",
            "| Task | State | Completion | Owner | Next gate |",
            "|---|---|---:|---|---|",
        ]
    )
    for task in snapshot["tasks"]:
        next_gate = str(task["next_gate"]).replace("|", "/")
        lines.append(
            f"| {task['id']} {task['title']} | `{task['state']}` | "
            f"{task['completion_pct']:.1f}% | {task['owner']} | {next_gate} |"
        )

    blocked = [task for task in snapshot["tasks"] if task["blockers"]]
    lines.extend(["", "## Current blockers", ""])
    if not blocked:
        lines.append("- None recorded.")
    for task in blocked:
        lines.append(f"### {task['id']} {task['title']}")
        lines.append("")
        lines.extend(f"- {blocker}" for blocker in task["blockers"])
        lines.append("")

    lines.extend(
        [
            "## Updating progress",
            "",
            "Validate and display:",
            "",
            "```bash",
            "./sys roadmap",
            "python3 scripts/roadmap_progress.py validate",
            "```",
            "",
            "Transitions and same-state evidence records must be appended through the "
            "state-machine command or an equivalent reviewed JSONL event. Generated "
            "percentages are evidence-derived.",
            "",
        ]
    )
    return "\n".join(lines)


def _parse_criterion_updates(values: list[str]) -> dict[str, str]:
    updates: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise RoadmapProgressError(f"criterion update must be ID=STATUS: {value}")
        criterion_id, status = value.split("=", 1)
        updates[criterion_id] = status
    return updates


def append_transition(
    roadmap: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    task_id: str,
    to_state: str,
    reason: str,
    actor: str,
    evidence: list[str],
    criterion_updates: dict[str, str],
    blockers: list[str] | None,
    next_gate: str | None,
    commit_sha: str | None,
    path: Path = EVENTS_PATH,
) -> dict[str, Any]:
    snapshot = build_snapshot(roadmap, events)
    current = next((task for task in snapshot["tasks"] if task["id"] == task_id), None)
    if current is None:
        raise RoadmapProgressError(f"unknown task: {task_id}")
    occurred_at = datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    event = {
        "schema_version": EVENT_SCHEMA,
        "event_id": f"{task_id.lower()}-{occurred_at.replace(':', '').replace('-', '')}",
        "occurred_at": occurred_at,
        "task_id": task_id,
        "event_type": "transition",
        "from_state": current["state"],
        "to_state": to_state,
        "actor": actor,
        "reason": reason,
        "commit_sha": commit_sha,
        "evidence": evidence,
        "criterion_updates": criterion_updates,
    }
    if blockers is not None:
        event["blockers"] = blockers
    if next_gate is not None:
        event["next_gate"] = next_gate
    validate_events(roadmap, [*events, event])
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
    return event


def append_evidence(
    roadmap: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    task_id: str,
    reason: str,
    actor: str,
    evidence: list[str],
    criterion_updates: dict[str, str],
    blockers: list[str] | None,
    next_gate: str | None,
    commit_sha: str | None,
    path: Path = EVENTS_PATH,
) -> dict[str, Any]:
    """Append evidence without claiming a roadmap state transition."""
    snapshot = build_snapshot(roadmap, events)
    current = next((task for task in snapshot["tasks"] if task["id"] == task_id), None)
    if current is None:
        raise RoadmapProgressError(f"unknown task: {task_id}")
    if not evidence:
        raise RoadmapProgressError("evidence event must cite at least one evidence item")
    occurred_at = datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    suffix = commit_sha[:12] if commit_sha else occurred_at.replace(":", "").replace("-", "")
    event = {
        "schema_version": EVENT_SCHEMA,
        "event_id": f"{task_id.lower()}-evidence-{suffix}",
        "occurred_at": occurred_at,
        "task_id": task_id,
        "event_type": "evidence",
        "from_state": current["state"],
        "to_state": current["state"],
        "actor": actor,
        "reason": reason,
        "commit_sha": commit_sha,
        "evidence": evidence,
        "criterion_updates": criterion_updates,
    }
    if blockers is not None:
        event["blockers"] = blockers
    if next_gate is not None:
        event["next_gate"] = next_gate
    validate_events(roadmap, [*events, event])
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
    return event


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("validate")
    status = sub.add_parser("status")
    status.add_argument("--json", action="store_true")
    render = sub.add_parser("render")
    render.add_argument("--output", type=Path, default=HUMAN_VIEW_PATH)
    transition = sub.add_parser("transition")
    transition.add_argument("task_id")
    transition.add_argument("to_state")
    transition.add_argument("--reason", required=True)
    transition.add_argument("--actor", required=True)
    transition.add_argument("--evidence", action="append", default=[])
    transition.add_argument("--criterion", action="append", default=[])
    transition.add_argument("--blocker", action="append")
    transition.add_argument("--next-gate")
    transition.add_argument("--commit-sha")
    evidence = sub.add_parser("evidence")
    evidence.add_argument("task_id")
    evidence.add_argument("--reason", required=True)
    evidence.add_argument("--actor", required=True)
    evidence.add_argument("--evidence", action="append", default=[])
    evidence.add_argument("--criterion", action="append", default=[])
    evidence.add_argument("--blocker", action="append")
    evidence.add_argument("--next-gate")
    evidence.add_argument("--commit-sha")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = args.command or "status"
    try:
        roadmap = load_roadmap()
        events = load_events()
        if command == "validate":
            snapshot = build_snapshot(roadmap, events)
            print(
                json.dumps(
                    {
                        "valid": True,
                        "tasks": len(snapshot["tasks"]),
                        "events": len(events),
                        "overall_completion_pct": snapshot["overall_completion_pct"],
                    },
                    indent=2,
                )
            )
            return 0
        if command == "transition":
            event = append_transition(
                roadmap,
                events,
                task_id=args.task_id,
                to_state=args.to_state,
                reason=args.reason,
                actor=args.actor,
                evidence=args.evidence,
                criterion_updates=_parse_criterion_updates(args.criterion),
                blockers=args.blocker,
                next_gate=args.next_gate,
                commit_sha=args.commit_sha,
            )
            print(json.dumps(event, ensure_ascii=False, indent=2))
            return 0
        if command == "evidence":
            event = append_evidence(
                roadmap,
                events,
                task_id=args.task_id,
                reason=args.reason,
                actor=args.actor,
                evidence=args.evidence,
                criterion_updates=_parse_criterion_updates(args.criterion),
                blockers=args.blocker,
                next_gate=args.next_gate,
                commit_sha=args.commit_sha,
            )
            print(json.dumps(event, ensure_ascii=False, indent=2))
            return 0
        snapshot = build_snapshot(roadmap, events)
        if command == "render":
            args.output.write_text(render_markdown(snapshot), encoding="utf-8")
            print(f"Generated {args.output}")
            return 0
        if getattr(args, "json", False):
            print(json.dumps(snapshot, ensure_ascii=False, indent=2))
        else:
            print(render_markdown(snapshot), end="")
        return 0
    except (OSError, RoadmapProgressError) as exc:
        print(f"roadmap progress: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
