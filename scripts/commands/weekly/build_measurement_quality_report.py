#!/usr/bin/env python3
"""Build measurement_quality.json — live panel presence plus K/X research-only stamp.

K/X disk gates are archived artifacts, not live quality. A July PASS on disk
does not make overall OK and is not a fulfilled data request.

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

import scripts._data_paths as _dp
import scripts._runtime_io as _rio
from scripts._data_paths import (
    resolve_benchmark_panel_path,
    resolve_cross_asset_panel_path,
)
from scripts._runtime_io import current_dir, ensure_dir, load_json, write_json


def _k_gate_path() -> Path:
    return _rio.ROOT / "Output" / "k_measurement" / "k_measurement_gate.json"


def _x_gate_path() -> Path:
    return _rio.ROOT / "Output" / "x_measurement" / "x_measurement_gate.json"


def _output_path() -> Path:
    return current_dir() / "measurement_quality.json"


def _harvester_release() -> dict[str, Any]:
    catalog_path = _dp.HARVESTER_LATEST / "catalog.json"
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


def _archived_gate(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    data = load_json(path)
    if not data:
        return None
    tests = data.get("tests") or {}
    return {
        "path": _rel(path),
        "gate_verdict": data.get("gate_verdict", "UNKNOWN"),
        "tests_passed": sum(1 for item in tests.values() if item.get("status") == "PASS"),
        "tests_total": len(tests),
        "generated_at": data.get("generated_at"),
    }


def _research_only_channel(path: Path, channel: str) -> dict[str, Any]:
    """K/X are not live quality. Disk PASS stays archived, never gate_verdict."""
    return {
        "channel": channel,
        "present": False,
        "gate_verdict": "NOT_WIRED",
        "readout_role": "research_only",
        "theory_authority": "none",
        "operational_wiring": "denied",
        "archived_artifact": _archived_gate(path),
    }


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(_rio.ROOT))
    except ValueError:
        return str(path)


def build_report() -> dict[str, Any]:
    harvester = _harvester_release()
    k_summary = _research_only_channel(_k_gate_path(), "K")
    x_summary = _research_only_channel(_x_gate_path(), "X_agg")
    cross_asset = resolve_cross_asset_panel_path()
    benchmark = resolve_benchmark_panel_path()

    overall = "OK" if cross_asset.exists() and benchmark.exists() else "DEGRADED"

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
            "K_measurement_quality": "not_wired",
            "X_agg_measurement_quality": "research_only",
        },
    }


def write_report(
    report: dict[str, Any],
    *,
    output_path: Path | None = None,
) -> Path:
    """Write the report to an explicit current-output surface."""
    target = output_path or _output_path()
    ensure_dir(target.parent)
    write_json(target, report)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="Build measurement quality sidecar report.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    args = parser.parse_args()

    report = build_report()
    output_path = write_report(report)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Measurement quality: {report['overall_status']}")
        print(f"  K: {report['channels']['K']['gate_verdict']}")
        print(f"  X_agg: {report['channels']['X_agg']['gate_verdict']}")
        print(f"  Wrote: {_rel(output_path)}")


if __name__ == "__main__":
    main()
