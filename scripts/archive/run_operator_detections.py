#!/usr/bin/env python3
"""Run mechanism operator detectors on the latest Harvester panel.

Research-only — writes operator activations without affecting core judgment.

Usage:
    python3 scripts/run_operator_detections.py
    python3 scripts/run_operator_detections.py --as-of 2023-03-10

Output:
    Output/current/operator_activations.json
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
from typing import Any

import pandas as pd
from _runtime_io import ROOT, current_dir, ensure_dir, write_json
from _workspace_imports import add_framework_root  # noqa: E402

add_framework_root()

from src.operators.mechanism import (  # noqa: E402
    ActivationRecord,
    FundingPathStressDetector,
)

PANEL = ROOT / "Data" / "harvester" / "exports" / "latest" / "data" / "benchmark_panel.parquet"
OUT = current_dir() / "operator_activations.json"


def _load_panel() -> pd.DataFrame:
    if not PANEL.exists():
        return pd.DataFrame()
    return pd.read_parquet(PANEL)


def run_detections(as_of: str | None = None) -> dict[str, Any]:
    panel = _load_panel()
    if panel.empty:
        return {
            "schema_version": "operator_activations.v1",
            "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "error": "benchmark_panel missing",
            "allowed_to_affect_core_judgment": False,
            "activations": [],
        }

    if as_of is None:
        as_of = str(pd.to_datetime(panel["date"].max()).date())

    detectors = [FundingPathStressDetector()]
    records: list[ActivationRecord] = []
    for det in detectors:
        records.append(det.detect(panel, as_of))

    return {
        "schema_version": "operator_activations.v1",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "as_of_date": as_of,
        "panel_path": str(PANEL.relative_to(ROOT)),
        "allowed_to_affect_core_judgment": False,
        "activations": [r.to_dict() for r in records],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run mechanism operator detectors.")
    parser.add_argument("--as-of", dest="as_of", default=None)
    args = parser.parse_args()

    payload = run_detections(args.as_of)
    ensure_dir(OUT.parent)
    write_json(OUT, payload)
    print(f"Wrote: {OUT}")
    if payload.get("error"):
        return 1
    for act in payload.get("activations", []):
        print(f"  {act['operator']}: {act['state']} (activation={act['activation']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
