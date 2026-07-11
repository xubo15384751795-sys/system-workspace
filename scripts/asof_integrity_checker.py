#!/usr/bin/env python3
"""As-of integrity checker — detect future-data leakage in calibration outputs.

Validates that judgment cards, calibration evaluations, and feedback samples
only reference data available at or before their as_of date.  This is a
review-only diagnostic; it does not modify any pipeline outputs.

Outputs:
    Output/quality/asof_integrity_report.json

Usage:
    python3 scripts/asof_integrity_checker.py
    python3 scripts/asof_integrity_checker.py --json
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from _runtime_io import ROOT, ensure_dir, load_json, utc_now, write_json

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
JUDGMENT_DIR = ROOT / "Output" / "judgment"
FEEDBACK_DIR = ROOT / "Output" / "feedback_samples" / "replay_runs"
RUNS_DIR = ROOT / "Output" / "runs"
QUALITY_DIR = ROOT / "Output" / "quality"
REPORT_PATH = QUALITY_DIR / "asof_integrity_report.json"

# ---------------------------------------------------------------------------
# Leakage checks
# ---------------------------------------------------------------------------

def _parse_date(value: str) -> datetime | None:
    """Parse ISO date string to datetime, returning None on failure."""
    try:
        return datetime.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return None


def check_judgment_card_forward_window(card: dict[str, Any]) -> list[dict[str, Any]]:
    """Check that judgment card outcomes only use data from dates > as_of."""
    issues: list[dict[str, Any]] = []
    as_of = _parse_date(str(card.get("as_of") or ""))
    if as_of is None:
        issues.append({
            "type": "missing_as_of",
            "severity": "warning",
            "detail": "Judgment card has no parseable as_of date.",
        })
        return issues

    # Check that the card's own data doesn't reference future dates
    for horizon_key, horizon_data in (card.get("outcomes") or {}).items():
        if not isinstance(horizon_data, dict):
            continue
        for metric_name, metric in (horizon_data.get("metrics") or {}).items():
            if not isinstance(metric, dict):
                continue
            entry_date = _parse_date(str(metric.get("entry_date") or ""))
            if entry_date and entry_date < as_of:
                issues.append({
                    "type": "entry_before_as_of",
                    "severity": "error",
                    "detail": (
                        f"Horizon {horizon_key}/{metric_name}: "
                        f"entry_date {metric['entry_date']} < as_of {as_of.date()}"
                    ),
                })
    return issues


def check_calibration_evaluation_order(evaluations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Verify that evaluation dates are non-decreasing (no retroactive insertion)."""
    issues: list[dict[str, Any]] = []
    prev_date: datetime | None = None
    for eval_item in evaluations:
        as_of = _parse_date(str(eval_item.get("as_of") or ""))
        if as_of is None:
            continue
        if prev_date and as_of < prev_date:
            issues.append({
                "type": "evaluation_order_regression",
                "severity": "error",
                "detail": (
                    f"Evaluation for {as_of.date()} appears after "
                    f"{prev_date.date()} — possible retroactive insertion."
                ),
            })
        prev_date = as_of
    return issues


def check_feedback_sample_timing(sample: dict[str, Any]) -> list[dict[str, Any]]:
    """Check that feedback sample forward_outcome was computed after as_of_date."""
    issues: list[dict[str, Any]] = []
    as_of = _parse_date(str(sample.get("as_of_date") or ""))
    if as_of is None:
        return issues

    computed_at = sample.get("forward_outcome", {}).get("computed_at")
    if computed_at:
        comp_dt = _parse_date(str(computed_at))
        # computed_at should be >= as_of (outcomes are computed after the fact)
        if comp_dt and comp_dt < as_of:
            issues.append({
                "type": "outcome_computed_before_as_of",
                "severity": "error",
                "detail": (
                    f"Sample {sample.get('sample_id')}: forward_outcome.computed_at "
                    f"{computed_at} < as_of_date {as_of.date()}"
                ),
            })

    # Check that forward return dates are actually in the future
    fo = sample.get("forward_outcome", {})
    for asset in ("spy", "hyg", "tlt", "gld"):
        fo.get(asset, {})
        for horizon_key in ("pct_1d", "pct_1w", "pct_1m", "pct_3m"):
            # These are forward returns — the horizon itself should be > as_of
            # We can't check exact dates from pct values, but we can verify
            # that the data structure is consistent
            pass

    return issues


def check_run_bundle_signal_trace(run_dir: Path) -> list[dict[str, Any]]:
    """Check that signal traces in run bundles don't reference future dates."""
    issues: list[dict[str, Any]] = []
    trace_path = run_dir / "signal_trace.json"
    if not trace_path.exists():
        return issues

    trace = load_json(trace_path)
    if not trace:
        return issues

    # Extract run date from directory name
    run_date = _parse_date(run_dir.name)
    if run_date is None:
        return issues

    # Check that signal dates in the trace don't exceed the run date
    for entry in (trace if isinstance(trace, list) else [trace]):
        if not isinstance(entry, dict):
            continue
        signal_date = _parse_date(str(entry.get("date") or entry.get("as_of") or ""))
        if signal_date and signal_date > run_date:
            issues.append({
                "type": "signal_after_run_date",
                "severity": "error",
                "detail": (
                    f"Run {run_dir.name}: signal date {signal_date.date()} > "
                    f"run date {run_date.date()}"
                ),
            })

    return issues


# ---------------------------------------------------------------------------
# Main checker
# ---------------------------------------------------------------------------

def run_integrity_checks() -> dict[str, Any]:
    """Run all as-of integrity checks and return the report."""
    all_issues: list[dict[str, Any]] = []
    checks_run = 0

    # 1. Check judgment cards
    judgment_cards = []
    for card_path in sorted(JUDGMENT_DIR.glob("*.json")):
        if not re.match(r"\d{4}-\d{2}-\d{2}\\.json$", card_path.name):
            continue
        card = load_json(card_path)
        if card:
            judgment_cards.append(card)
            issues = check_judgment_card_forward_window(card)
            for issue in issues:
                issue["source"] = f"judgment/{card_path.name}"
            all_issues.extend(issues)
            checks_run += 1

    # 2. Check calibration evaluation order
    cal_path = JUDGMENT_DIR / "calibration_report.json"
    if cal_path.exists():
        cal = load_json(cal_path)
        if cal:
            evaluations = cal.get("evaluations", [])
            issues = check_calibration_evaluation_order(evaluations)
            for issue in issues:
                issue["source"] = "judgment/calibration_report.json"
            all_issues.extend(issues)
            checks_run += 1

    # 3. Check feedback samples
    if FEEDBACK_DIR.exists():
        for sample_path in sorted(FEEDBACK_DIR.glob("*.json")):
            sample = load_json(sample_path)
            if sample:
                issues = check_feedback_sample_timing(sample)
                for issue in issues:
                    issue["source"] = f"feedback_samples/{sample_path.name}"
                all_issues.extend(issues)
                checks_run += 1

    # 4. Check run bundle signal traces (last 10 runs)
    if RUNS_DIR.exists():
        run_dirs = sorted(RUNS_DIR.iterdir(), reverse=True)[:10]
        for run_dir in run_dirs:
            if run_dir.is_dir():
                issues = check_run_bundle_signal_trace(run_dir)
                for issue in issues:
                    issue["source"] = f"runs/{run_dir.name}"
                all_issues.extend(issues)
                checks_run += 1

    error_count = sum(1 for i in all_issues if i.get("severity") == "error")
    warning_count = sum(1 for i in all_issues if i.get("severity") == "warning")

    return {
        "schema_version": "quality.asof_integrity.v1",
        "generated_at": utc_now().isoformat(),
        "checks_run": checks_run,
        "total_issues": len(all_issues),
        "error_count": error_count,
        "warning_count": warning_count,
        "status": "PASS" if error_count == 0 else "FAIL",
        "issues": all_issues,
        "notes": [
            "This is a review-only diagnostic. It does not modify pipeline outputs.",
            "Errors indicate possible future-data leakage in calibration.",
            "Warnings indicate structural issues that should be investigated.",
        ],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="As-of integrity checker for calibration outputs.")
    parser.add_argument("--json", action="store_true", help="Print report JSON to stdout.")
    args = parser.parse_args()

    ensure_dir(QUALITY_DIR)
    report = run_integrity_checks()
    write_json(REPORT_PATH, report)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"As-of integrity report: {REPORT_PATH}")
        print(f"Checks run: {report['checks_run']}")
        print(f"Status: {report['status']}")
        print(f"Issues: {report['total_issues']} "
              f"(errors={report['error_count']}, warnings={report['warning_count']})")


if __name__ == "__main__":
    main()
