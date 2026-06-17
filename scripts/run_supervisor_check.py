"""Run supervisor check — opencode's self-audit after each work cycle.

Reads current artifacts and governance policies, produces a structured
supervisor report.  This is the system's self-audit layer.

Usage:
    python3 scripts/run_supervisor_check.py
    python3 scripts/run_supervisor_check.py --json
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CURRENT = ROOT / "Output" / "current"
JUDGMENT = ROOT / "Output" / "judgment"
LEARNING = ROOT / "Output" / "system_learning" / "latest"
DEFERRED_PATH = ROOT / "governance" / "deferred_work_register.yaml"
DATA_AUTHORITY_PATH = ROOT / "governance" / "data_authority_registry.yaml"
SUPERVISOR_POLICY_PATH = ROOT / "governance" / "opencode_supervisor_policy.yaml"


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_yaml(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _check_work_cycle_completeness() -> dict[str, Any]:
    """Check if all declared artifacts exist."""
    required = [
        ("framework_output", CURRENT / "framework_output.json"),
        ("status", CURRENT / "status.json"),
        ("quality_validation", CURRENT / "quality_validation.json"),
        ("judgment", JUDGMENT / "latest.json"),
        ("work_brief", CURRENT / "work_brief.json"),
    ]
    missing = []
    for name, path in required:
        if not path.exists():
            missing.append(name)

    return {
        "status": "PASS" if not missing else "INCOMPLETE",
        "missing": missing,
        "total_required": len(required),
        "present": len(required) - len(missing),
    }


def _check_artifact_consistency() -> dict[str, Any]:
    """Check if artifact dates are consistent."""
    dates = {}
    for name, path, field in [
        ("framework_output", CURRENT / "framework_output.json", "as_of"),
        ("status", CURRENT / "status.json", "date"),
        ("judgment", JUDGMENT / "latest.json", "as_of"),
    ]:
        data = _load_json(path)
        if data and data.get(field):
            dates[name] = str(data[field])[:10]

    if not dates:
        return {"status": "NO_DATA", "dates": {}}

    unique_dates = set(dates.values())
    return {
        "status": "PASS" if len(unique_dates) <= 1 else "INCONSISTENT",
        "dates": dates,
        "unique_dates": list(unique_dates),
    }


def _check_unmarked_data() -> dict[str, Any]:
    """Check for non-Harvester data not marked research_only."""
    reg = _load_yaml(DATA_AUTHORITY_PATH)
    if not reg:
        return {"status": "NO_REGISTRY", "entries": 0}

    entries = reg.get("entries", [])
    unmarked = []
    for entry in entries:
        auth = entry.get("authority", "")
        if auth not in ("research_only_non_harvester", "non_harvester_transitional",
                        "legacy_runtime_store", "legacy_runtime_cache",
                        "migration_artifact", "export_only"):
            unmarked.append(entry.get("path", "unknown"))

    return {
        "status": "PASS" if not unmarked else "WARN",
        "total_entries": len(entries),
        "unmarked": unmarked,
    }


def _check_deferred_work_overdue() -> dict[str, Any]:
    """Check for deferred work past hard_deadline."""
    reg = _load_yaml(DEFERRED_PATH)
    if not reg:
        return {"status": "NO_REGISTRY"}

    today = datetime.now()
    overdue = []
    approaching = []
    for item in reg.get("items", []):
        hard_dl = item.get("hard_deadline")
        if not hard_dl:
            continue
        try:
            deadline = datetime.strptime(str(hard_dl), "%Y-%m-%d")
            days_left = (deadline - today).days
            if days_left < 0:
                overdue.append({
                    "id": item.get("id", "unknown"),
                    "days_overdue": -days_left,
                    "hard_deadline": str(hard_dl),
                })
            elif days_left <= 14:
                approaching.append({
                    "id": item.get("id", "unknown"),
                    "days_left": days_left,
                    "hard_deadline": str(hard_dl),
                })
        except ValueError:
            pass

    return {
        "status": "PASS" if not overdue else "OVERDUE",
        "overdue": overdue,
        "approaching_deadline": approaching,
    }


def _check_module_activity() -> dict[str, Any]:
    """Check which modules produced output recently."""
    now = datetime.now(UTC)
    active = []
    if CURRENT.exists():
        for item in CURRENT.iterdir():
            if item.is_file() and item.suffix in (".json", ".md"):
                mtime = datetime.fromtimestamp(item.stat().st_mtime, tz=UTC)
                age_hours = (now - mtime).total_seconds() / 3600
                if age_hours < 24:
                    active.append({
                        "artifact": item.name,
                        "age_hours": round(age_hours, 1),
                    })

    return {
        "status": "ACTIVE" if active else "IDLE",
        "active_artifacts": len(active),
        "artifacts": active[:10],
    }


def run_supervisor_check() -> dict[str, Any]:
    """Run all supervisor checks."""
    now = datetime.now(UTC)

    checks = {
        "work_cycle_completeness": _check_work_cycle_completeness(),
        "artifact_consistency": _check_artifact_consistency(),
        "unmarked_data": _check_unmarked_data(),
        "deferred_work_overdue": _check_deferred_work_overdue(),
        "module_activity": _check_module_activity(),
    }

    # Determine overall status
    statuses = [c.get("status", "UNKNOWN") for c in checks.values()]
    if "OVERDUE" in statuses:
        overall = "OVERDUE"
    elif "INCONSISTENT" in statuses or "INCOMPLETE" in statuses:
        overall = "FINDINGS"
    elif "WARN" in statuses:
        overall = "WARN"
    else:
        overall = "PASS"

    # Build review queue
    review_queue = []
    for item in checks["deferred_work_overdue"].get("overdue", []):
        review_queue.append({
            "source": "deferred_work_overdue",
            "id": item["id"],
            "severity": "high",
            "action": f"Overdue by {item['days_overdue']} days",
        })
    for item in checks["deferred_work_overdue"].get("approaching_deadline", []):
        review_queue.append({
            "source": "deadline_approaching",
            "id": item["id"],
            "severity": "medium",
            "action": f"{item['days_left']} days to deadline",
        })

    return {
        "timestamp": now.isoformat(),
        "overall_status": overall,
        "checks": checks,
        "review_queue": review_queue,
    }


def generate_markdown(results: dict[str, Any]) -> str:
    """Generate markdown supervisor report."""
    lines = [
        "# Supervisor Check",
        "",
        f"**Timestamp:** {results['timestamp']}",
        f"**Overall Status:** {results['overall_status']}",
        "",
        "---",
        "",
    ]

    status_icons = {
        "PASS": "✅", "ACTIVE": "✅", "NO_DATA": "⚪", "NO_REGISTRY": "⚪",
        "IDLE": "⚪", "INCOMPLETE": "⚠️", "INCONSISTENT": "⚠️",
        "WARN": "⚠️", "OVERDUE": "❌", "FINDINGS": "⚠️",
    }

    for check_name, check_data in results["checks"].items():
        icon = status_icons.get(check_data["status"], "❓")
        lines.append(f"## {icon} {check_name}")
        lines.append("")
        lines.append(f"**Status:** {check_data['status']}")
        lines.append("")

        # Show key details
        if check_data.get("missing"):
            lines.append(f"Missing: {', '.join(check_data['missing'])}")
            lines.append("")
        if check_data.get("dates"):
            lines.append("Dates:")
            for k, v in check_data["dates"].items():
                lines.append(f"  - {k}: {v}")
            lines.append("")
        if check_data.get("overdue"):
            lines.append("Overdue:")
            for item in check_data["overdue"]:
                lines.append(f"  - {item['id']}: {item['days_overdue']} days overdue")
            lines.append("")
        if check_data.get("approaching_deadline"):
            lines.append("Approaching deadline:")
            for item in check_data["approaching_deadline"]:
                lines.append(f"  - {item['id']}: {item['days_left']} days left")
            lines.append("")

    if results.get("review_queue"):
        lines += [
            "---",
            "",
            "## Review Queue",
            "",
        ]
        for item in results["review_queue"]:
            lines.append(f"- [{item['severity']}] {item['id']}: {item['action']}")
        lines.append("")

    lines += [
        "---",
        "",
        "*Generated by scripts/run_supervisor_check.py*",
        "*Authority: governance/opencode_supervisor_policy.yaml*",
    ]

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run supervisor check")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    results = run_supervisor_check()

    LEARNING.mkdir(parents=True, exist_ok=True)

    json_path = LEARNING / "supervisor_check.json"
    json_path.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    md_path = LEARNING / "supervisor_check.md"
    md_path.write_text(generate_markdown(results), encoding="utf-8")

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        print(generate_markdown(results))


if __name__ == "__main__":
    main()
