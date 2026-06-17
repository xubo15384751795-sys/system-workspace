#!/usr/bin/env python3
"""Build Daily Run Summary — machine-readable run status.

Reads runtime events from Output/runtime_events/ and produces a summary
of the most recent daily run.

Usage:
    python3 scripts/build_daily_run_summary.py
    python3 scripts/build_daily_run_summary.py --json

Output:
    Output/runtime_events/latest_daily_run_summary.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RUNTIME_DIR = ROOT / "Output" / "runtime_events"
REGISTRY_PATH = ROOT / "governance" / "daily_pipeline_registry.yaml"


def _load_registry() -> dict[str, Any]:
    """Load the daily pipeline registry."""
    try:
        import yaml
        data = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
        return data.get("steps", {})
    except Exception:
        return {}


def _find_latest_run() -> Path | None:
    """Find the most recent daily run JSONL file."""
    if not RUNTIME_DIR.exists():
        return None
    jsonl_files = sorted(RUNTIME_DIR.glob("*.jsonl"), reverse=True)
    return jsonl_files[0] if jsonl_files else None


def _parse_run_events(path: Path) -> list[dict[str, Any]]:
    """Parse a JSONL runtime events file."""
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def build_summary(events: list[dict[str, Any]], registry: dict[str, Any]) -> dict[str, Any]:
    """Build a summary from run events and registry."""
    step_results: dict[str, str] = {}
    for event in events:
        name = event.get("step") or event.get("name", "")
        status = event.get("status", "unknown")
        if name:
            step_results[name] = status

    succeeded = [n for n, s in step_results.items() if s == "success"]
    failed = [n for n, s in step_results.items() if s == "failure"]
    skipped = [n for n, s in step_results.items() if s == "skipped"]

    blocked = [n for n, spec in registry.items() if spec.get("status") == "blocked"]
    compatibility = [n for n, spec in registry.items() if spec.get("status") == "compatibility"]
    experimental = [n for n, spec in registry.items() if spec.get("status") == "experimental"]

    # Core judgment steps that succeeded
    core_judgment_steps = [
        n for n, spec in registry.items()
        if spec.get("core_judgment_dependency") is True
    ]
    core_judgment_succeeded = [n for n in core_judgment_steps if n in succeeded]
    core_judgment_failed = [n for n in core_judgment_steps if n in failed]

    core_judgment_trustworthy = len(core_judgment_failed) == 0 and len(core_judgment_succeeded) > 0

    return {
        "schema_version": "daily_run_summary.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "run_date": events[0].get("date", "") if events else "",
        "total_steps": len(registry),
        "steps_succeeded": succeeded,
        "steps_failed": failed,
        "steps_skipped": skipped,
        "steps_blocked": blocked,
        "steps_compatibility": compatibility,
        "steps_experimental": experimental,
        "core_judgment_steps": core_judgment_steps,
        "core_judgment_succeeded": core_judgment_succeeded,
        "core_judgment_failed": core_judgment_failed,
        "core_judgment_trustworthy": core_judgment_trustworthy,
        "research_only_steps": experimental + blocked,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build daily run summary")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout")
    args = parser.parse_args()

    registry = _load_registry()
    latest = _find_latest_run()

    if latest is None:
        summary = {
            "schema_version": "daily_run_summary.v1",
            "generated_at": datetime.now(UTC).isoformat(),
            "error": "No runtime events found",
            "total_steps": len(registry),
        }
    else:
        events = _parse_run_events(latest)
        summary = build_summary(events, registry)

    # Write output
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RUNTIME_DIR / "latest_daily_run_summary.json"
    out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print(f"Daily run summary: {out_path}")
        if "error" in summary:
            print(f"  Status: {summary['error']}")
        else:
            print(f"  Succeeded: {len(summary['steps_succeeded'])}")
            print(f"  Failed: {len(summary['steps_failed'])}")
            print(f"  Blocked: {len(summary['steps_blocked'])}")
            print(f"  Core judgment trustworthy: {summary['core_judgment_trustworthy']}")


if __name__ == "__main__":
    main()
