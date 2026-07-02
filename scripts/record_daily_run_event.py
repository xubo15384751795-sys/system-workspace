#!/usr/bin/env python3
"""Record daily run event to Learning Hub — system memory.

Writes a structured event to Output/system_learning/events/ after each
pipeline run with: evidence grade, blockers, trade decision, run_id,
git_sha, and submodule pins.

Usage:
    python3 scripts/record_daily_run_event.py
    python3 scripts/record_daily_run_event.py --run-id <id>
    python3 scripts/record_daily_run_event.py --json

Output:
    Output/system_learning/events/run_events_YYYY-MM-DD.jsonl
"""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from _runtime_io import ROOT, current_dir, ensure_dir, load_json, utc_now

TRADE_DECISION_PATH = ROOT / "Output" / "trade_decision" / "latest.json"
EVIDENCE_GRADE_PATH = current_dir() / "evidence_grade_report.json"
STATUS_PATH = current_dir() / "status.json"
EVENTS_DIR = ROOT / "Output" / "system_learning" / "events"
PROMOTION_GATE_PATH = ROOT / "Output" / "judgment" / "promotion_gate.json"
HUB_EVENTS_DIR = ROOT / "Output" / "runtime_events"


def _get_git_sha() -> str:
    """Get current git SHA."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=str(ROOT), timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _get_submodule_pins() -> dict[str, str]:
    """Get submodule SHAs."""
    pins: dict[str, str] = {}
    for submodule in ["deformation-framework", "structural-risk-harvester", "system-learning-hub", "Workbench"]:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--short", f"HEAD:{submodule}"],
                capture_output=True, text=True, cwd=str(ROOT), timeout=5,
            )
            if result.returncode == 0:
                pins[submodule] = result.stdout.strip()
        except Exception:
            pins[submodule] = "unknown"
    return pins


def build_run_event(run_id: str | None = None) -> dict[str, Any]:
    """Build a run event record."""
    now = utc_now()
    trade_decision = load_json(TRADE_DECISION_PATH)
    evidence_grade = load_json(EVIDENCE_GRADE_PATH)
    status = load_json(STATUS_PATH)
    promotion_gate = load_json(PROMOTION_GATE_PATH)

    # Collect blockers from all sources
    blockers: list[dict[str, Any]] = []
    if evidence_grade:
        for b in evidence_grade.get("blockers", []):
            blockers.append({"code": b.get("code", ""), "category": b.get("category", ""),
                            "message": b.get("message", "")[:200]})
    if status:
        for b in status.get("promotion_gate", {}).get("blocking_reasons", []):
            if isinstance(b, str):
                blockers.append({"code": "status_blocker", "category": "promotion_gate", "message": b})
    if promotion_gate:
        for g in promotion_gate.get("blocked_gates", []):
            blockers.append({"code": f"pg_{g}", "category": "promotion_gate",
                            "message": f"Promotion gate blocked: {g}"})

    event = {
        "schema_version": "run_event.v1",
        "event_type": "pipeline_run",
        "event_id": run_id or f"run_{now.strftime('%Y%m%d_%H%M%S')}",
        "timestamp": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "evidence_grade": evidence_grade.get("grade", "D") if evidence_grade else "D",
        "trade_decision_grade": trade_decision.get("evidence_grade", "D") if trade_decision else "D",
        "trade_decision": trade_decision.get("decision", "UNKNOWN") if trade_decision else "UNKNOWN",
        "confidence": trade_decision.get("confidence", "unknown") if trade_decision else "unknown",
        "blockers": blockers,
        "git_sha": _get_git_sha(),
        "submodule_pins": _get_submodule_pins(),
        "paper_support": evidence_grade.get("paper_support_status", {}) if evidence_grade else {},
    }

    return event


def _event_fingerprint(event: dict[str, Any]) -> str:
    """Stable fingerprint for deduplicating unchanged run snapshots."""
    blocker_codes = sorted(
        b.get("code", "") for b in event.get("blockers", []) if isinstance(b, dict)
    )
    payload = {
        "evidence_grade": event.get("evidence_grade"),
        "trade_decision_grade": event.get("trade_decision_grade"),
        "trade_decision": event.get("trade_decision"),
        "confidence": event.get("confidence"),
        "blocker_codes": blocker_codes,
        "git_sha": event.get("git_sha"),
    }
    return json.dumps(payload, sort_keys=True)


def _read_last_event(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError:
        return None
    if not lines:
        return None
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError:
        return None


def record_event(event: dict[str, Any], *, force: bool = False, skip_if_unchanged: bool = False) -> Path | None:
    """Append event to daily JSONL file. Returns path, or None if skipped."""
    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    event_path = EVENTS_DIR / f"run_events_{date_str}.jsonl"
    hub_path = HUB_EVENTS_DIR / f"run_events_{date_str}.jsonl"

    if skip_if_unchanged and not force:
        last = _read_last_event(event_path)
        if last and _event_fingerprint(last) == _event_fingerprint(event):
            return None

    ensure_dir(EVENTS_DIR)
    ensure_dir(HUB_EVENTS_DIR)

    line = json.dumps(event, ensure_ascii=False) + "\n"

    # Write to system_learning/events/
    with event_path.open("a", encoding="utf-8") as f:
        f.write(line)

    # Also write to runtime_events/ for harness consumption
    with hub_path.open("a", encoding="utf-8") as f:
        f.write(line)

    return event_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Record daily run event to Learning Hub.")
    parser.add_argument("--run-id", default=None, help="Override run ID.")
    parser.add_argument("--json", action="store_true", help="Print event to stdout.")
    parser.add_argument("--force", action="store_true", help="Always append, even if unchanged.")
    parser.add_argument(
        "--skip-if-unchanged",
        action="store_true",
        help="Skip append when the latest event for today has the same fingerprint.",
    )
    args = parser.parse_args()

    event = build_run_event(args.run_id)
    path = record_event(
        event,
        force=args.force,
        skip_if_unchanged=args.skip_if_unchanged,
    )

    if args.json:
        print(json.dumps(event, indent=2, ensure_ascii=False))
    elif path is None:
        print("Run event unchanged — skipped append.")
        print(f"  Grade: {event['evidence_grade']} (trade: {event['trade_decision_grade']})")
        print(f"  Decision: {event['trade_decision']} ({event['confidence']})")
    else:
        print(f"Run event recorded: {path}")
        print(f"  Grade: {event['evidence_grade']} (trade: {event['trade_decision_grade']})")
        print(f"  Decision: {event['trade_decision']} ({event['confidence']})")
        print(f"  Blockers: {len(event['blockers'])}")
        print(f"  Git SHA: {event['git_sha']}")
        print(f"  Submodule pins: {event['submodule_pins']}")


if __name__ == "__main__":
    main()
