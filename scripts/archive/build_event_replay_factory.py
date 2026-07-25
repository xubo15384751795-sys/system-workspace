#!/usr/bin/env python3
"""Event replay factory — historical window operator activations.

Reads governance/event_replay_windows.yaml and runs mechanism detectors
across each window using the Harvester benchmark panel.

Usage:
    python3 scripts/build_event_replay_factory.py
    python3 scripts/build_event_replay_factory.py --window svb_2023

Output:
    Output/sandbox/event_replay/<window_id>.json
    Output/sandbox/event_replay/summary.json
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from typing import Any

import pandas as pd
import yaml
from src.operators.mechanism import FundingPathStressDetector

from scripts._runtime_io import ROOT, ensure_dir, write_json

WINDOWS = ROOT / "governance" / "event_replay_windows.yaml"
PANEL = ROOT / "Data" / "harvester" / "exports" / "latest" / "data" / "benchmark_panel.parquet"
OUT_DIR = ROOT / "Output" / "sandbox" / "event_replay"

DETECTORS = {
    "FUNDING_PATH_STRESS": FundingPathStressDetector(),
}


def _load_windows() -> list[dict[str, Any]]:
    data = yaml.safe_load(WINDOWS.read_text(encoding="utf-8")) or {}
    return list(data.get("windows", []))


def _summarize_window(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {"days": 0, "max_activation": 0.0, "active_days": 0, "watch_days": 0}
    activations = [float(r.get("activation", 0)) for r in records]
    states = [r.get("state") for r in records]
    return {
        "days": len(records),
        "max_activation": round(max(activations), 4),
        "mean_activation": round(sum(activations) / len(activations), 4),
        "active_days": sum(1 for s in states if s == "active"),
        "watch_days": sum(1 for s in states if s == "watch"),
    }


def build(window_filter: str | None = None) -> dict[str, Any]:
    if not PANEL.exists():
        return {"error": "benchmark_panel missing", "windows": []}

    panel = pd.read_parquet(PANEL)
    windows = _load_windows()
    if window_filter:
        windows = [w for w in windows if w.get("id") == window_filter]

    ensure_dir(OUT_DIR)
    results: list[dict[str, Any]] = []

    for window in windows:
        wid = window["id"]
        ops = window.get("operators", ["FUNDING_PATH_STRESS"])
        window_payload: dict[str, Any] = {
            "window_id": wid,
            "label": window.get("label"),
            "start": window["start"],
            "end": window["end"],
            "notes": window.get("notes"),
            "operators": {},
        }
        for op_name in ops:
            det = DETECTORS.get(op_name)
            if det is None:
                continue
            records = [r.to_dict() for r in det.detect_range(panel, window["start"], window["end"])]
            window_payload["operators"][op_name] = {
                "records": records,
                "summary": _summarize_window(records),
            }
        out_path = OUT_DIR / f"{wid}.json"
        write_json(out_path, window_payload)
        results.append({"window_id": wid, "path": str(out_path.relative_to(ROOT)), "summary": window_payload["operators"]})

    summary = {
        "schema_version": "event_replay_factory.v1",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "panel_path": str(PANEL.relative_to(ROOT)),
        "windows": results,
    }
    write_json(OUT_DIR / "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Build event replay factory outputs.")
    parser.add_argument("--window", default=None, help="Single window id")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    summary = build(args.window)
    if summary.get("error"):
        print(summary["error"])
        return 1
    print(f"Event replay factory: {len(summary.get('windows', []))} window(s) → {OUT_DIR}")
    if args.json:
        print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
