#!/usr/bin/env python3
"""Freshness Validator — check artifact freshness and temporal ordering.

This script validates that key artifacts are fresh and in correct
temporal order. Stale artifacts cannot be displayed as ✅.

Usage:
    python3 scripts/freshness_validator.py
    python3 scripts/freshness_validator.py --json

Output:
    Output/quality/freshness_report.json
    Output/quality/freshness_report.md
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "Output"
QUALITY_DIR = OUTPUT_DIR / "quality"

# Maximum age before artifact is stale
MAX_AGE_HOURS = {
    "harvester": 48,
    "structural_replay": 48,
    "framework_output": 48,
    "judgment": 48,
    "promotion_gate": 48,
    "trade_decision": 48,
    "risk_gate": 48,
    "learning_summary": 72,
    "system_index": 24,
    "readme_first": 24,
}

# Evidence release TTL — see governance/architecture_reality_decisions.md §4
# See: configs/freshness_policy.yaml evidence_release section
EVIDENCE_RELEASE_TTL_HOURS = 3 * 24  # 3 days = 72 hours


def get_file_mtime(path: Path) -> datetime | None:
    """Get file modification time."""
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)


def check_artifact_freshness(
    name: str,
    path: Path,
    max_age_hours: int,
    now: datetime,
) -> dict[str, Any]:
    """Check if an artifact is fresh."""
    mtime = get_file_mtime(path)
    if mtime is None:
        return {
            "name": name,
            "path": str(path),
            "status": "MISSING",
            "age_hours": None,
            "max_age_hours": max_age_hours,
        }

    age_hours = (now - mtime).total_seconds() / 3600
    is_fresh = age_hours <= max_age_hours

    return {
        "name": name,
        "path": str(path),
        "status": "FRESH" if is_fresh else "STALE",
        "age_hours": round(age_hours, 1),
        "max_age_hours": max_age_hours,
        "last_modified": mtime.isoformat(),
    }


def check_temporal_ordering(now: datetime) -> list[dict[str, Any]]:
    """Check that artifacts are in correct temporal order."""
    issues = []

    # Define expected ordering
    ordering_rules = [
        {
            "earlier": ("judgment", OUTPUT_DIR / "judgment" / "latest.json"),
            "later": ("trade_decision", OUTPUT_DIR / "trade_decision" / "latest.json"),
            "rule": "trade_decision must be after judgment",
        },
        {
            "earlier": ("trade_decision", OUTPUT_DIR / "trade_decision" / "latest.json"),
            "later": ("risk_gate", OUTPUT_DIR / "trade_decision" / "risk_gate.json"),
            "rule": "risk_gate must be after trade_decision",
        },
        {
            "earlier": ("trade_decision", OUTPUT_DIR / "trade_decision" / "latest.json"),
            "later": ("learning_summary", OUTPUT_DIR / "system_learning" / "latest" / "comprehensive_summary.json"),
            "rule": "learning_summary must be after trade_decision",
        },
        {
            "earlier": ("learning_summary", OUTPUT_DIR / "system_learning" / "latest" / "comprehensive_summary.json"),
            "later": ("system_index", ROOT / "Data" / "system_index" / "latest.json"),
            "rule": "system_index must be after learning_summary",
        },
        {
            "earlier": ("system_index", ROOT / "Data" / "system_index" / "latest.json"),
            "later": ("readme_first", OUTPUT_DIR / "current" / "00_READ_ME_FIRST.md"),
            "rule": "readme_first must be after system_index",
        },
    ]

    for rule in ordering_rules:
        earlier_name, earlier_path = rule["earlier"]
        later_name, later_path = rule["later"]

        earlier_time = get_file_mtime(earlier_path)
        later_time = get_file_mtime(later_path)

        if earlier_time and later_time:
            if later_time < earlier_time:
                issues.append({
                    "rule": rule["rule"],
                    "earlier": earlier_name,
                    "earlier_time": earlier_time.isoformat(),
                    "later": later_name,
                    "later_time": later_time.isoformat(),
                    "status": "VIOLATION",
                })

    return issues


def build_freshness_report(now: datetime) -> dict[str, Any]:
    """Build complete freshness report."""
    # Check artifact freshness
    artifacts = [
        ("harvester", ROOT / "Data" / "harvester" / "exports" / "latest" / "catalog.json", MAX_AGE_HOURS["harvester"]),
        ("framework_output", OUTPUT_DIR / "current" / "framework_output.json", MAX_AGE_HOURS["framework_output"]),
        ("judgment", OUTPUT_DIR / "judgment" / "latest.json", MAX_AGE_HOURS["judgment"]),
        ("promotion_gate", OUTPUT_DIR / "judgment" / "promotion_gate.json", MAX_AGE_HOURS["promotion_gate"]),
        ("trade_decision", OUTPUT_DIR / "trade_decision" / "latest.json", MAX_AGE_HOURS["trade_decision"]),
        ("risk_gate", OUTPUT_DIR / "trade_decision" / "risk_gate.json", MAX_AGE_HOURS["risk_gate"]),
        ("learning_summary", OUTPUT_DIR / "system_learning" / "latest" / "comprehensive_summary.json", MAX_AGE_HOURS["learning_summary"]),
        ("system_index", ROOT / "Data" / "system_index" / "latest.json", MAX_AGE_HOURS["system_index"]),
        ("readme_first", OUTPUT_DIR / "current" / "00_READ_ME_FIRST.md", MAX_AGE_HOURS["readme_first"]),
    ]

    freshness_checks = [check_artifact_freshness(name, path, max_age, now) for name, path, max_age in artifacts]

    # Check evidence release freshness (3-day TTL)
    # See: governance/architecture_reality_decisions.md §4
    evidence_release = ROOT / "Data" / "harvester" / "exports" / "latest"
    if evidence_release.exists():
        er_check = check_artifact_freshness(
            "evidence_release", evidence_release, EVIDENCE_RELEASE_TTL_HOURS, now
        )
        freshness_checks.append(er_check)

    # Check temporal ordering
    ordering_issues = check_temporal_ordering(now)

    # Determine overall verdict
    stale_artifacts = [a for a in freshness_checks if a["status"] == "STALE"]
    missing_artifacts = [a for a in freshness_checks if a["status"] == "MISSING"]

    if ordering_issues:
        verdict = "FAIL"
    elif stale_artifacts:
        verdict = "WARN"
    elif missing_artifacts:
        verdict = "WARN"
    else:
        verdict = "PASS"

    return {
        "schema_version": "freshness_validator.v1",
        "generated_at": now.isoformat(),
        "verdict": verdict,
        "stale_artifacts": [a["name"] for a in stale_artifacts],
        "missing_artifacts": [a["name"] for a in missing_artifacts],
        "ordering_issues": ordering_issues,
        "artifacts": freshness_checks,
    }


def format_markdown(report: dict[str, Any]) -> str:
    """Format freshness report as markdown."""
    lines = [
        "# Freshness Report",
        "",
        f"**Generated:** {report['generated_at']}",
        f"**Verdict:** {report['verdict']}",
        "",
        "---",
        "",
        "## Artifacts",
        "",
        "| Artifact | Status | Age (h) | Max Age (h) |",
        "|---|---|---:|---:|",
    ]

    for artifact in report["artifacts"]:
        status_icon = "✅" if artifact["status"] == "FRESH" else "❌" if artifact["status"] == "STALE" else "⚠️"
        age = f"{artifact['age_hours']:.1f}" if artifact["age_hours"] is not None else "N/A"
        lines.append(f"| {artifact['name']} | {status_icon} {artifact['status']} | {age} | {artifact['max_age_hours']} |")

    if report["ordering_issues"]:
        lines += [
            "",
            "## Ordering Issues",
            "",
        ]
        for issue in report["ordering_issues"]:
            lines.append(f"- ❌ {issue['rule']}")

    if report["stale_artifacts"]:
        lines += [
            "",
            "## Stale Artifacts",
            "",
        ]
        for name in report["stale_artifacts"]:
            lines.append(f"- {name}")

    if report["missing_artifacts"]:
        lines += [
            "",
            "## Missing Artifacts",
            "",
        ]
        for name in report["missing_artifacts"]:
            lines.append(f"- {name}")

    lines += [
        "",
        "---",
        "",
        "*Stale artifacts cannot be displayed as ✅ in system index.*",
    ]

    return "\n".join(lines) + "\n"


def write_outputs(report: dict[str, Any]) -> dict[str, Path]:
    """Write freshness report outputs."""
    QUALITY_DIR.mkdir(parents=True, exist_ok=True)

    json_path = QUALITY_DIR / "freshness_report.json"
    md_path = QUALITY_DIR / "freshness_report.md"

    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(format_markdown(report), encoding="utf-8")

    return {"json": json_path, "markdown": md_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run freshness validator.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    args = parser.parse_args()

    now = datetime.now(UTC)
    report = build_freshness_report(now)
    paths = write_outputs(report)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Freshness report: {paths['markdown']}")
        print(f"Verdict: {report['verdict']}")
        print(f"Stale: {len(report['stale_artifacts'])}")
        print(f"Missing: {len(report['missing_artifacts'])}")
        print(f"Ordering issues: {len(report['ordering_issues'])}")


if __name__ == "__main__":
    main()
