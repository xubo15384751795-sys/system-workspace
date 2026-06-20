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

from _runtime_io import ROOT, ensure_dir
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
    "signal_card": 24,
    "signal_consensus": 24,
    "work_brief": 24,
}

# The "current outputs" chain — these must all be from the same run
CURRENT_OUTPUT_CHAIN = [
    "readme_first",
    "signal_card",
    "signal_consensus",
    "work_brief",
    "system_index",
]

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


def check_closure_chain(now: datetime) -> list[dict[str, Any]]:
    """Check that all current outputs are from the same run (closure chain).

    If any current output is significantly older than the others, it means
    a partial refresh happened — the chain is not closed.

    The "current output chain" consists of: readme_first, signal_card,
    work_brief, system_index. These should all be generated within a
    short window (< 5 minutes) of each other during a full pipeline run.
    """
    issues = []
    chain_paths = {
        "readme_first": OUTPUT_DIR / "current" / "00_READ_ME_FIRST.md",
        "signal_card": OUTPUT_DIR / "current" / "signal_card.json",
        "signal_consensus": OUTPUT_DIR / "current" / "signal_consensus.json",
        "work_brief": OUTPUT_DIR / "current" / "work_brief.json",
        "system_index": ROOT / "Data" / "system_index" / "latest.json",
    }

    # Collect mtimes for all chain members that exist
    mtimes: dict[str, datetime] = {}
    for name, path in chain_paths.items():
        mtime = get_file_mtime(path)
        if mtime is not None:
            mtimes[name] = mtime

    if len(mtimes) < 2:
        return issues  # Can't check chain with < 2 artifacts

    # Check if any artifact is more than 5 minutes older than the newest
    # This indicates a partial refresh (the chain is not closed)
    newest_name = max(mtimes, key=lambda k: mtimes[k])
    newest_time = mtimes[newest_name]
    # 30-minute tolerance: accounts for re-runs that update some artifacts
    # but not all within the same pipeline session
    max_gap_minutes = 30

    for name, mtime in mtimes.items():
        gap_minutes = (newest_time - mtime).total_seconds() / 60
        if gap_minutes > max_gap_minutes:
            issues.append({
                "rule": f"closure chain: {name} is {gap_minutes:.0f}min older than {newest_name}",
                "earlier": name,
                "earlier_time": mtime.isoformat(),
                "later": newest_name,
                "later_time": newest_time.isoformat(),
                "status": "CLOSURE_VIOLATION",
                "hint": (
                    f"Partial refresh detected: {name} was not updated in the same run "
                    f"as {newest_name}. Re-run the full pipeline to close the chain, "
                    f"or run: python3 scripts/build_{name}.py"
                ),
            })

    return issues


def check_temporal_ordering(now: datetime, *, mode: str = "standard") -> list[dict[str, Any]]:
    """Check that artifacts are in correct temporal order."""
    issues = []

    # Define expected ordering — the full pipeline chain
    ordering_rules = [
        # Full-chain rules — quick mode marks these as ADVISORY_EXPECTED
        {
            "earlier": ("judgment", OUTPUT_DIR / "judgment" / "latest.json"),
            "later": ("promotion_gate", OUTPUT_DIR / "judgment" / "promotion_gate.json"),
            "rule": "promotion_gate must be after judgment",
            "chain": "full",
        },
        {
            "earlier": ("promotion_gate", OUTPUT_DIR / "judgment" / "promotion_gate.json"),
            "later": ("trade_decision", OUTPUT_DIR / "trade_decision" / "latest.json"),
            "rule": "trade_decision must be after promotion_gate",
            "chain": "full",
        },
        {
            "earlier": ("trade_decision", OUTPUT_DIR / "trade_decision" / "latest.json"),
            "later": ("risk_gate", OUTPUT_DIR / "trade_decision" / "risk_gate.json"),
            "rule": "risk_gate must be after trade_decision",
            "chain": "full",
        },
        {
            "earlier": ("risk_gate", OUTPUT_DIR / "trade_decision" / "risk_gate.json"),
            "later": ("record_trade_decision", OUTPUT_DIR / "trade_ledger" / "latest.md"),
            "rule": "record_trade_decision must be after risk_gate",
            "chain": "full",
        },
        {
            "earlier": ("trade_decision", OUTPUT_DIR / "trade_decision" / "latest.json"),
            "later": ("learning_summary", OUTPUT_DIR / "system_learning" / "latest" / "comprehensive_summary.json"),
            "rule": "learning_summary must be after trade_decision",
            "chain": "full",
        },
        {
            "earlier": ("learning_summary", OUTPUT_DIR / "system_learning" / "latest" / "comprehensive_summary.json"),
            "later": ("system_index", ROOT / "Data" / "system_index" / "latest.json"),
            "rule": "system_index must be after learning_summary",
            "chain": "full",
        },
        {
            "earlier": ("system_index", ROOT / "Data" / "system_index" / "latest.json"),
            "later": ("readme_first", OUTPUT_DIR / "current" / "00_READ_ME_FIRST.md"),
            "rule": "readme_first must be after system_index",
            "chain": "full",
        },
        # Current-output rules — always hard FAIL
        {
            "earlier": ("readme_first", OUTPUT_DIR / "current" / "00_READ_ME_FIRST.md"),
            "later": ("signal_card", OUTPUT_DIR / "current" / "signal_card.json"),
            "rule": "signal_card must be after readme_first",
            "chain": "current",
        },
        {
            "earlier": ("signal_card", OUTPUT_DIR / "current" / "signal_card.json"),
            "later": ("signal_consensus", OUTPUT_DIR / "current" / "signal_consensus.json"),
            "rule": "signal_consensus must be after signal_card",
            "chain": "current",
        },
        {
            "earlier": ("signal_consensus", OUTPUT_DIR / "current" / "signal_consensus.json"),
            "later": ("work_brief", OUTPUT_DIR / "current" / "work_brief.json"),
            "rule": "work_brief must be after signal_consensus",
            "chain": "current",
        },
    ]

    for rule in ordering_rules:
        earlier_name, earlier_path = rule["earlier"]
        later_name, later_path = rule["later"]

        earlier_time = get_file_mtime(earlier_path)
        later_time = get_file_mtime(later_path)

        if earlier_time and later_time:
            # Skip ordering check if files are from different days (weekly vs daily steps)
            if earlier_time.date() != now.date() or later_time.date() != now.date():
                continue

            # Skip if both files were modified within 30 minutes of each other
            # (same pipeline run, minor ordering from re-runs or parallel steps)
            delta = abs((later_time - earlier_time).total_seconds())
            if delta < 1800:
                continue

            if later_time < earlier_time:
                chain = rule.get("chain", "full")
                # Cross-day ordering issues are advisory (weekly vs daily mix)
                is_advisory = (mode == "quick" and chain == "full") or earlier_time.date() != later_time.date()
                issues.append({
                    "rule": rule["rule"],
                    "earlier": earlier_name,
                    "earlier_time": earlier_time.isoformat(),
                    "later": later_name,
                    "later_time": later_time.isoformat(),
                    "status": "ADVISORY_EXPECTED" if is_advisory else "VIOLATION",
                    "hint": (
                        f"Ordering violation: {later_name} is older than {earlier_name}. "
                        f"Re-run: python3 scripts/run_work_cycle.py --mode standard"
                    ),
                })

    return issues


def build_freshness_report(now: datetime, *, mode: str = "standard") -> dict[str, Any]:
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
        ("signal_card", OUTPUT_DIR / "current" / "signal_card.json", MAX_AGE_HOURS["signal_card"]),
        ("signal_consensus", OUTPUT_DIR / "current" / "signal_consensus.json", MAX_AGE_HOURS["signal_consensus"]),
        ("work_brief", OUTPUT_DIR / "current" / "work_brief.json", MAX_AGE_HOURS["work_brief"]),
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
    ordering_issues = check_temporal_ordering(now, mode=mode)

    # Check closure chain — all current outputs must be from the same run
    closure_issues = check_closure_chain(now)

    # Determine overall verdict
    stale_artifacts = [a for a in freshness_checks if a["status"] == "STALE"]
    missing_artifacts = [a for a in freshness_checks if a["status"] == "MISSING"]

    # Only hard violations count toward FAIL; ADVISORY_EXPECTED is informational
    hard_ordering = [i for i in ordering_issues if i["status"] != "ADVISORY_EXPECTED"]
    if hard_ordering or closure_issues:
        verdict = "FAIL"
    elif stale_artifacts:
        verdict = "WARN"
    elif missing_artifacts:
        verdict = "WARN"
    else:
        verdict = "PASS"

    return {
        "schema_version": "freshness_validator.v2",
        "generated_at": now.isoformat(),
        "verdict": verdict,
        "stale_artifacts": [a["name"] for a in stale_artifacts],
        "missing_artifacts": [a["name"] for a in missing_artifacts],
        "ordering_issues": ordering_issues,
        "closure_chain_issues": closure_issues,
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

    if report.get("ordering_issues"):
        lines += [
            "",
            "## Ordering Issues",
            "",
        ]
        for issue in report["ordering_issues"]:
            lines.append(f"- ❌ {issue['rule']}")

    if report.get("closure_chain_issues"):
        lines += [
            "",
            "## Closure Chain Violations",
            "",
            "Current outputs are not from the same run. Re-run the full pipeline to close the chain.",
            "",
        ]
        for issue in report["closure_chain_issues"]:
            lines.append(f"- ❌ {issue['rule']}")
            if issue.get("hint"):
                lines.append(f"  - Fix: {issue['hint']}")

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
    ensure_dir(QUALITY_DIR)

    json_path = QUALITY_DIR / "freshness_report.json"
    md_path = QUALITY_DIR / "freshness_report.md"

    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(format_markdown(report), encoding="utf-8")

    return {"json": json_path, "markdown": md_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run freshness validator.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    parser.add_argument(
        "--mode", choices=["quick", "standard", "full"], default="standard",
        help="Validation mode: quick marks full-chain ordering as advisory.",
    )
    args = parser.parse_args()

    now = datetime.now(UTC)
    report = build_freshness_report(now, mode=args.mode)
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
