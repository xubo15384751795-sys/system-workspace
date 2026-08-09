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
import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from scripts._runtime_io import ROOT, current_dir, ensure_dir

OUTPUT_DIR = ROOT / "Output"
CURRENT = current_dir()
QUALITY_DIR = OUTPUT_DIR / "quality"

# Phase 1.2: artifact mtime budgets derived from configs/freshness_policy.yaml
# (single source of truth), not hardcoded. Each artifact maps to its owning
# step's cadence (daily/weekly); the budget = acceptable_lag_days * 24 hours.
# This replaces the old hardcoded MAX_AGE_HOURS dict.
_POLICY_PATH = ROOT / "configs" / "freshness_policy.yaml"

# Map artifact name -> cadence. learning_summary is weekly (8d TTL); the rest
# of the current-readout chain is daily. System_index/readme/signal are daily
# display artifacts (24h = 1 day, the fresh_lag threshold for daily).
_ARTIFACT_CADENCE = {
    "harvester": "daily",
    "structural_replay": "daily",
    "framework_output": "daily",
    "judgment": "daily",
    "promotion_gate": "daily",
    "trade_decision": "daily",
    "risk_gate": "daily",
    "learning_summary": "weekly",  # weekly cadence (daily_run_sequence.yaml)
    "system_index": "daily",
    "readme_first": "daily",
    "signal_card": "daily",
    "signal_consensus": "daily",
    "work_brief": "daily",
}


def _load_max_age_hours_from_policy() -> dict[str, int]:
    """Derive per-artifact max-age-hours from freshness_policy.yaml.

    budget = frequency_thresholds[cadence].acceptable_lag_days * 24.
    Falls back to the policy's daily threshold if the cadence is unknown.
    """
    try:
        policy = yaml.safe_load(_POLICY_PATH.read_text(encoding="utf-8")) or {}
    except OSError:
        policy = {}
    thresholds = policy.get("frequency_thresholds", {}) or {}
    daily = (thresholds.get("daily") or {}).get("acceptable_lag_days", 10)
    weekly = (thresholds.get("weekly") or {}).get("acceptable_lag_days", 21)
    budgets: dict[str, int] = {}
    for name, cadence in _ARTIFACT_CADENCE.items():
        if cadence == "weekly":
            budgets[name] = int(weekly) * 24
        else:
            budgets[name] = int(daily) * 24
    return budgets


MAX_AGE_HOURS = _load_max_age_hours_from_policy()

def _load_content_freshness_registry(root: Path = ROOT) -> dict[str, dict[str, Any]]:
    """Compile content clocks from the canonical pipeline registry.

    Keeping these paths in Python recreated the exact "monitor path table drift"
    failure mode this validator is meant to prevent.
    """
    registry_path = root / "governance" / "daily_pipeline_registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    rows = registry.get("content_freshness", {}) or {}
    return {str(name): dict(config) for name, config in rows.items() if isinstance(config, dict)}


# Backward-compatible import surface for callers/tests; source of truth is YAML.
CONTENT_FRESHNESS = _load_content_freshness_registry()

# The "current outputs" chain — these must all be from the same run
CURRENT_OUTPUT_CHAIN = [
    "readme_first",
    "signal_card",
    "signal_consensus",
    "work_brief",
    "system_index",
]


def _chain_current() -> Path:
    """Current readout dir for closure/freshness checks (patchable via OUTPUT_DIR in tests)."""
    override = os.environ.get("CURRENT_OUTPUT_DIR")
    if override:
        return Path(override)
    return OUTPUT_DIR / "current"

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


def _last_trading_day(on: date) -> date:
    """Roll calendar date back to the most recent Mon–Fri session."""
    d = on
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def trading_days_behind(content_max: date, as_of: date) -> int:
    """Business days that content_max lags the last expected session as of as_of."""
    expected = _last_trading_day(as_of)
    if content_max >= expected:
        return 0
    return int(np.busday_count(content_max, expected))


def check_content_freshness(
    name: str,
    path: Path,
    date_column: str,
    max_trading_days_behind: int,
    now: datetime,
) -> dict[str, Any]:
    """Check parquet/CSV max(date) against a trading-day lag budget.

    Uses Pandera for column presence when available; lag math stays identical
    so publish-gate consumers keep the same status vocabulary.
    """
    if not path.exists():
        return {
            "name": name,
            "path": str(path),
            "check_type": "content",
            "status": "MISSING",
            "date_column": date_column,
            "max_date": None,
            "trading_days_behind": None,
            "max_trading_days_behind": max_trading_days_behind,
            "engine": "pandera",
        }

    try:
        import pandas as pd

        if path.suffix.lower() == ".csv":
            frame = pd.read_csv(path)
        else:
            frame = pd.read_parquet(path, columns=[date_column])
    except Exception as exc:  # noqa: BLE001 — report as MISSING/unreadable
        return {
            "name": name,
            "path": str(path),
            "check_type": "content",
            "status": "MISSING",
            "date_column": date_column,
            "max_date": None,
            "trading_days_behind": None,
            "max_trading_days_behind": max_trading_days_behind,
            "error": str(exc),
            "engine": "pandera",
        }

    try:
        import pandera.pandas as pa

        pa.DataFrameSchema(
            {date_column: pa.Column(nullable=False)},
            coerce=True,
            strict=False,
        ).validate(frame[[date_column]] if date_column in frame.columns else frame, lazy=True)
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001 — schema failure maps to MISSING
        return {
            "name": name,
            "path": str(path),
            "check_type": "content",
            "status": "MISSING",
            "date_column": date_column,
            "max_date": None,
            "trading_days_behind": None,
            "max_trading_days_behind": max_trading_days_behind,
            "error": f"pandera:{exc}",
            "engine": "pandera",
        }

    if frame.empty or date_column not in frame.columns:
        return {
            "name": name,
            "path": str(path),
            "check_type": "content",
            "status": "MISSING",
            "date_column": date_column,
            "max_date": None,
            "trading_days_behind": None,
            "max_trading_days_behind": max_trading_days_behind,
            "engine": "pandera",
        }

    max_ts = pd.to_datetime(frame[date_column]).max()
    max_d = max_ts.date() if hasattr(max_ts, "date") else date.fromisoformat(str(max_ts)[:10])
    as_of = now.date() if now.tzinfo is None else now.astimezone().date()
    behind = trading_days_behind(max_d, as_of)
    is_fresh = behind <= max_trading_days_behind

    return {
        "name": name,
        "path": str(path),
        "check_type": "content",
        "status": "FRESH" if is_fresh else "STALE",
        "date_column": date_column,
        "max_date": max_d.isoformat(),
        "trading_days_behind": behind,
        "max_trading_days_behind": max_trading_days_behind,
        "age_hours": None,
        "max_age_hours": None,
        "engine": "pandera",
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
        "readme_first": _chain_current() / "00_READ_ME_FIRST.md",
        "signal_card": _chain_current() / "signal_card.json",
        "signal_consensus": _chain_current() / "signal_consensus.json",
        "work_brief": _chain_current() / "work_brief.json",
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
            "later": ("readme_first", CURRENT / "00_READ_ME_FIRST.md"),
            "rule": "readme_first must be after system_index",
            "chain": "full",
        },
        # Current-output rules — always hard FAIL
        {
            "earlier": ("readme_first", CURRENT / "00_READ_ME_FIRST.md"),
            "later": ("signal_card", CURRENT / "signal_card.json"),
            "rule": "signal_card must be after readme_first",
            "chain": "current",
        },
        {
            "earlier": ("signal_card", CURRENT / "signal_card.json"),
            "later": ("signal_consensus", CURRENT / "signal_consensus.json"),
            "rule": "signal_consensus must be after signal_card",
            "chain": "current",
        },
        {
            "earlier": ("signal_consensus", CURRENT / "signal_consensus.json"),
            "later": ("work_brief", CURRENT / "work_brief.json"),
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
        ("framework_output", CURRENT / "framework_output.json", MAX_AGE_HOURS["framework_output"]),
        ("judgment", OUTPUT_DIR / "judgment" / "latest.json", MAX_AGE_HOURS["judgment"]),
        ("promotion_gate", OUTPUT_DIR / "judgment" / "promotion_gate.json", MAX_AGE_HOURS["promotion_gate"]),
        ("trade_decision", OUTPUT_DIR / "trade_decision" / "latest.json", MAX_AGE_HOURS["trade_decision"]),
        ("risk_gate", OUTPUT_DIR / "trade_decision" / "risk_gate.json", MAX_AGE_HOURS["risk_gate"]),
        ("learning_summary", OUTPUT_DIR / "system_learning" / "latest" / "comprehensive_summary.json", MAX_AGE_HOURS["learning_summary"]),
        ("system_index", ROOT / "Data" / "system_index" / "latest.json", MAX_AGE_HOURS["system_index"]),
        ("readme_first", CURRENT / "00_READ_ME_FIRST.md", MAX_AGE_HOURS["readme_first"]),
        ("signal_card", CURRENT / "signal_card.json", MAX_AGE_HOURS["signal_card"]),
        ("signal_consensus", CURRENT / "signal_consensus.json", MAX_AGE_HOURS["signal_consensus"]),
        ("work_brief", CURRENT / "work_brief.json", MAX_AGE_HOURS["work_brief"]),
    ]

    freshness_checks = [check_artifact_freshness(name, path, max_age, now) for name, path, max_age in artifacts]

    # Content freshness — payload max(date), not file mtime
    content_checks: list[dict[str, Any]] = []
    for name, cfg in CONTENT_FRESHNESS.items():
        content_checks.append(
            check_content_freshness(
                name,
                ROOT / cfg["path"],
                cfg["date_column"],
                int(cfg["max_trading_days_behind"]),
                now,
            )
        )
    freshness_checks.extend(content_checks)

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

    ge_suite: dict[str, Any] | None = None
    try:
        from orchestration.quality.ge_suite import (
            run_content_freshness_suite,
            write_ge_validation_artifact,
        )

        ge_suite = run_content_freshness_suite(root=ROOT)
        write_ge_validation_artifact(ge_suite, root=ROOT)
    except Exception as exc:  # noqa: BLE001 — GE is additive; never block report shape
        ge_suite = {"engine": "great_expectations+pandera", "success": None, "error": str(exc)}

    return {
        "schema_version": "freshness_validator.v3",
        "generated_at": now.isoformat(),
        "verdict": verdict,
        "stale_artifacts": [a["name"] for a in stale_artifacts],
        "missing_artifacts": [a["name"] for a in missing_artifacts],
        "ordering_issues": ordering_issues,
        "closure_chain_issues": closure_issues,
        "content_freshness": content_checks,
        "artifacts": freshness_checks,
        "ge_content_freshness": ge_suite,
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
        if artifact.get("check_type") == "content":
            behind = artifact.get("trading_days_behind")
            age = f"{behind}d behind" if behind is not None else "N/A"
            max_age = str(artifact.get("max_trading_days_behind", "N/A"))
        else:
            age = f"{artifact['age_hours']:.1f}" if artifact["age_hours"] is not None else "N/A"
            max_age = str(artifact["max_age_hours"]) if artifact.get("max_age_hours") is not None else "N/A"
        lines.append(f"| {artifact['name']} | {status_icon} {artifact['status']} | {age} | {max_age} |")

    if report.get("content_freshness"):
        lines += [
            "",
            "## Content Freshness",
            "",
            "| Artifact | Status | max(date) | Days behind | Budget |",
            "|---|---|---|---:|---:|",
        ]
        for item in report["content_freshness"]:
            status_icon = "✅" if item["status"] == "FRESH" else "❌" if item["status"] == "STALE" else "⚠️"
            lines.append(
                f"| {item['name']} | {status_icon} {item['status']} | "
                f"{item.get('max_date') or 'N/A'} | "
                f"{item.get('trading_days_behind') if item.get('trading_days_behind') is not None else 'N/A'} | "
                f"{item.get('max_trading_days_behind', 'N/A')} |"
            )

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


def main() -> int:
    """Run freshness validator.

    Returns 0 on PASS/WARN, 1 on FAIL (hard ordering/closure violations).
    A nonzero return propagates to the pipeline runner as status="failed"
    and to the publish gate (should_publish) as a block. Note: stale/missing
    content is WARN here (advisory at the validator level); the pre-consumption
    admission gate in _admission_gate.py enforces hard blocking for the
    specific consumers (paper_portfolio) that depend on fresh public components.
    """
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

    content_stale = [
        c for c in report.get("content_freshness", [])
        if c.get("status") == "STALE"
    ]
    if content_stale:
        from scripts._notify import notify_failure

        details = ", ".join(
            f"{c['name']} max={c.get('max_date')} behind={c.get('trading_days_behind')}d"
            for c in content_stale
        )
        notify_failure(
            "Content freshness STALE",
            details,
        )

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Freshness report: {paths['markdown']}")
        print(f"Verdict: {report['verdict']}")
        print(f"Stale: {len(report['stale_artifacts'])}")
        print(f"Missing: {len(report['missing_artifacts'])}")
        print(f"Ordering issues: {len(report['ordering_issues'])}")
        if report.get("content_freshness"):
            for c in report["content_freshness"]:
                print(
                    f"Content {c['name']}: {c['status']} "
                    f"(max={c.get('max_date')}, behind={c.get('trading_days_behind')})"
                )

    # Hard FAIL (ordering/closure violations) must be a non-zero exit so the
    # pipeline runner records status="failed" and the publish gate blocks.
    return 1 if report.get("verdict") == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
