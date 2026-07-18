#!/usr/bin/env python3
"""Build measurement_quality.json — K/X gate summary for Harvester data requests.

Aggregates k_measurement_gate and x_measurement_gate outputs with Harvester
release metadata.  Feeds evidence_grade_report and closes K/X data_request
quality tracking.

Usage:
    python3 scripts/commands/weekly/build_measurement_quality_report.py
    python3 scripts/commands/weekly/build_measurement_quality_report.py --json

Output:
    Output/current/measurement_quality.json
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts._data_paths import (
    HARVESTER_LATEST,
    resolve_benchmark_panel_path,
    resolve_cross_asset_panel_path,
)
from scripts._runtime_io import ROOT, current_dir, ensure_dir, load_json, write_json

K_GATE_PATH = ROOT / "Output" / "k_measurement" / "k_measurement_gate.json"
X_GATE_PATH = ROOT / "Output" / "x_measurement" / "x_measurement_gate.json"
OUTPUT_PATH = current_dir() / "measurement_quality.json"


def _harvester_release() -> dict[str, Any]:
    catalog_path = HARVESTER_LATEST / "catalog.json"
    if not catalog_path.exists():
        return {"release_id": None, "catalog_present": False}
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"release_id": None, "catalog_present": True, "parse_error": True}
    return {
        "release_id": catalog.get("release_id"),
        "catalog_present": True,
        "generated_at": catalog.get("generated_at"),
    }


def _gate_summary(path: Path, channel: str) -> dict[str, Any]:
    if not path.exists():
        return {"channel": channel, "present": False, "gate_verdict": "MISSING"}
    data = load_json(path)
    if not data:
        return {"channel": channel, "present": False, "gate_verdict": "MISSING"}
    tests = data.get("tests") or {}
    pass_count = sum(1 for t in tests.values() if t.get("status") == "PASS")
    return {
        "channel": channel,
        "present": True,
        "gate_verdict": data.get("gate_verdict", "UNKNOWN"),
        "tests_passed": pass_count,
        "tests_total": len(tests),
        "generated_at": data.get("generated_at"),
    }


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def build_report() -> dict[str, Any]:
    harvester = _harvester_release()
    k_summary = _gate_summary(K_GATE_PATH, "K")
    x_summary = _gate_summary(X_GATE_PATH, "X_agg")
    cross_asset = resolve_cross_asset_panel_path()
    benchmark = resolve_benchmark_panel_path()

    overall = "OK"
    if k_summary["gate_verdict"] not in ("PASS", "WATCH"):
        overall = "DEGRADED"
    if x_summary["gate_verdict"] not in ("PASS", "WATCH", "BACKGROUND_ONLY"):
        overall = "DEGRADED"
    if not cross_asset.exists() or not benchmark.exists():
        overall = "DEGRADED"

    return {
        "schema_version": "system.measurement_quality.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "overall_status": overall,
        "harvester": harvester,
        "inputs": {
            "benchmark_panel": _rel(benchmark),
            "cross_asset_panel": _rel(cross_asset),
            "benchmark_present": benchmark.exists(),
            "cross_asset_present": cross_asset.exists(),
        },
        "channels": {
            "K": k_summary,
            "X_agg": x_summary,
        },
        "data_request_status": {
            "K_measurement_quality": "fulfilled" if overall == "OK" else "in_progress",
            "X_agg_measurement_quality": "fulfilled" if overall == "OK" else "in_progress",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build measurement quality sidecar report.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    args = parser.parse_args()

    report = build_report()
    ensure_dir(OUTPUT_PATH.parent)
    write_json(OUTPUT_PATH, report)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Measurement quality: {report['overall_status']}")
        print(f"  K: {report['channels']['K']['gate_verdict']}")
        print(f"  X_agg: {report['channels']['X_agg']['gate_verdict']}")
        print(f"  Wrote: {OUTPUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
