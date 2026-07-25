#!/usr/bin/env python3
"""Backfill missing judgment cards from archived daily snapshots and run bundles.

Reads Output/archive/framework_output + caselab, and daily_pipeline signal traces,
builds dated judgment cards for gaps, then refreshes judgment calibration report.

Usage:
    python3 scripts/commands/weekly/backfill_judgment_calibration.py
    python3 scripts/commands/weekly/backfill_judgment_calibration.py --dry-run
    python3 scripts/commands/weekly/backfill_judgment_calibration.py --force
    python3 scripts/commands/weekly/backfill_judgment_calibration.py --json

Output:
    Output/judgment/YYYY-MM-DD.json (missing dates only, unless --force)
    Output/judgment/calibration_report.json (refreshed)
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from workbench.judgment.layer import (
    build_judgment,
    load_caselab,
    load_hmm,
    load_k_gate,
    load_validation,
    load_x_gate,
    write_dated_outputs,
)

from scripts._runtime_io import ROOT, load_json, utc_now, write_json

ARCHIVE_FW = ROOT / "Output" / "archive" / "framework_output"
ARCHIVE_CASELAB = ROOT / "Output" / "archive" / "caselab"
CASELAB_DIR = ROOT / "Output" / "caselab"
JUDGMENT_DIR = ROOT / "Output" / "judgment"
RUNS_DIR = ROOT / "Output" / "runs"
REPORT_PATH = ROOT / "Output" / "caselab_runtime" / "backfill_judgment_report.json"

_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.json$")
_RUN_DATE_RE = re.compile(r"daily_pipeline_(\d{4})(\d{2})(\d{2})_")


def _dated_files(directory: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    if not directory.exists():
        return found
    for path in directory.glob("*.json"):
        match = _DATE_RE.match(path.name)
        if match:
            found[match.group(1)] = path
    return found


def _framework_from_signal_trace(data: dict[str, Any], date_str: str) -> dict[str, Any]:
    sigma = data.get("sigma_vector") or {}
    primary = data.get("primary_readout") or {}
    return {
        "schema_version": "workbench.framework_output.v3",
        "as_of": f"{date_str}T12:00:00+00:00",
        "status": data.get("framework_status", "active_full"),
        "basic": {
            "overall": data.get("overall", "ACTIVE_FULL"),
            "quality_status": data.get("quality_status", "FULL_PROXY_REDUCED"),
            "primary_market_space": primary.get("state", "UNKNOWN"),
        },
        "advanced": {
            "sigma_vector": sigma,
            "primary_readout": primary,
        },
        "provenance": {
            "source": "run_bundle_signal_trace",
            "backfill": True,
        },
    }


def discover_signal_trace_frameworks() -> dict[str, dict[str, Any]]:
    """Extract framework snapshots from daily_pipeline run bundles."""
    frameworks: dict[str, dict[str, Any]] = {}
    if not RUNS_DIR.exists():
        return frameworks

    for run_dir in sorted(RUNS_DIR.iterdir()):
        if not run_dir.is_dir():
            continue
        match = _RUN_DATE_RE.match(run_dir.name)
        if not match:
            continue
        date_str = f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
        trace_path = run_dir / "signal_trace.json"
        if not trace_path.exists():
            continue
        try:
            traces = json.loads(trace_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for entry in traces:
            data = entry.get("data") or {}
            if data.get("source") != "framework_output":
                continue
            frameworks[date_str] = _framework_from_signal_trace(data, date_str)
            break
    return frameworks


def framework_from_caselab(caselab: dict[str, Any], date_str: str) -> dict[str, Any] | None:
    """Build a minimal framework snapshot from CaseLab system_state."""
    state = caselab.get("system_state") or {}
    if state.get("M") is None and state.get("D") is None:
        return None
    x_val = state.get("X_agg", state.get("X"))
    return {
        "schema_version": "workbench.framework_output.v3",
        "as_of": f"{date_str}T12:00:00+00:00",
        "status": "active_full",
        "basic": {
            "overall": "ACTIVE_FULL",
            "quality_status": "FULL_PROXY_REDUCED",
            "primary_market_space": state.get("pattern", "UNKNOWN"),
        },
        "advanced": {
            "sigma_vector": {
                "M": state.get("M"),
                "D": state.get("D"),
                "K": state.get("K"),
                "X_agg": x_val,
            },
        },
        "provenance": {
            "source": "caselab_system_state",
            "backfill": True,
        },
    }


def discover_dates() -> list[str]:
    dates = set(_dated_files(ARCHIVE_FW))
    dates.update(_dated_files(ARCHIVE_CASELAB))
    dates.update(_dated_files(CASELAB_DIR))
    dates.update(discover_signal_trace_frameworks())
    return sorted(dates)


def _load_framework(date_str: str, signal_fw: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    archive_path = ARCHIVE_FW / f"{date_str}.json"
    if archive_path.exists():
        payload = load_json(archive_path)
        if payload:
            payload.setdefault("provenance", {})
            if isinstance(payload["provenance"], dict):
                payload["provenance"]["backfill"] = True
                payload["provenance"]["source"] = "archive_framework_output"
            return payload
    return signal_fw.get(date_str)


def _load_caselab_for_date(date_str: str) -> dict[str, Any] | None:
    for directory in (ARCHIVE_CASELAB, CASELAB_DIR):
        path = directory / f"{date_str}.json"
        if path.exists():
            return load_json(path)
    return load_caselab(date_str)


def _judgment_exists(date_str: str) -> bool:
    return (JUDGMENT_DIR / f"{date_str}.json").exists()


def backfill_judgment_calibration(
    *,
    dry_run: bool = False,
    force: bool = False,
    refresh_calibration: bool = True,
) -> dict[str, Any]:
    signal_fw = discover_signal_trace_frameworks()
    dates = discover_dates()
    hmm = load_hmm()
    k_gate = load_k_gate()
    x_gate = load_x_gate()
    validation = load_validation()

    created: list[str] = []
    skipped: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []

    for date_str in dates:
        if _judgment_exists(date_str) and not force:
            skipped.append({"date": date_str, "reason": "judgment_exists"})
            continue

        framework = _load_framework(date_str, signal_fw)
        caselab = _load_caselab_for_date(date_str)
        if not framework and caselab:
            framework = framework_from_caselab(caselab, date_str)
        if not framework:
            skipped.append({"date": date_str, "reason": "no_framework_snapshot"})
            continue
        try:
            card = build_judgment(framework, caselab, hmm, k_gate, x_gate, validation)
            card["provenance"] = {
                "source": "backfill_judgment_calibration",
                "backfilled_at": utc_now().isoformat(),
                "framework_source": (framework.get("provenance") or {}).get("source", "unknown"),
                "caselab_available": caselab is not None,
                "uses_current_gates": True,
            }
            if not dry_run:
                write_dated_outputs(card)
            created.append(date_str)
        except Exception as exc:  # noqa: BLE001 — collect per-date failures
            errors.append({"date": date_str, "error": str(exc)})

    calibration_summary: dict[str, Any] | None = None
    if refresh_calibration and not dry_run:
        from scripts.commands.weekly.judgment_replay_audit import (
            build_report,
            load_judgment_cards,
            load_market_series,
            write_report,
        )

        cards = load_judgment_cards()
        report = build_report(cards, load_market_series())
        write_report(report)
        calibration_summary = report.get("summary", {})

    report = {
        "schema_version": "backfill_judgment_calibration.v1",
        "generated_at": utc_now().isoformat(),
        "dry_run": dry_run,
        "force": force,
        "candidate_dates": len(dates),
        "created_count": len(created),
        "created_dates": created,
        "skipped": skipped,
        "errors": errors,
        "calibration_summary": calibration_summary,
    }

    if not dry_run:
        write_json(REPORT_PATH, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill judgment cards from archives and run bundles.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="Overwrite existing dated judgment cards.")
    parser.add_argument("--skip-calibration", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = backfill_judgment_calibration(
        dry_run=args.dry_run,
        force=args.force,
        refresh_calibration=not args.skip_calibration,
    )

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return

    print(
        f"Backfill: created {report['created_count']} card(s) "
        f"from {report['candidate_dates']} candidate date(s)"
    )
    if report["errors"]:
        print(f"Errors: {len(report['errors'])}")
    if report.get("calibration_summary"):
        summary = report["calibration_summary"]
        print(
            f"Calibration: {summary.get('evaluated_cards', 0)}/"
            f"{summary.get('total_cards', 0)} evaluated"
        )
    if not args.dry_run:
        print(f"Report: {REPORT_PATH}")


if __name__ == "__main__":
    main()
