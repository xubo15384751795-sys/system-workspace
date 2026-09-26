#!/usr/bin/env python3
"""Enrich agent run reports with world-model context before Obsidian write-back.

Usage:
    cd <verity-workspace>
    python3 -m caselab_context.enrich_agent_context --date 2026-06-16
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime

from caselab_context.enrich_signal import TICKER_CONTEXT_MAP, enrich_trade_signal
from caselab_context.paper_paths import paper_root
from system_runtime.paths import WorkspacePaths

PAPER_ROOT = paper_root()
REPORT_DIR = PAPER_ROOT / "data_pipeline" / "reports" / "agent-runs"
OUTPUT_DIR = PAPER_ROOT / "data_pipeline" / "reports" / "agent-runs-enriched"

SYSTEM_ROOT = WorkspacePaths.discover().root


def enrich_report(report: dict) -> dict:
    enriched_signals = []
    for signal in report.get("signals") or []:
        ticker = str(signal.get("ticker") or "").upper()
        if ticker not in TICKER_CONTEXT_MAP:
            enriched_signals.append({**signal, "world_model": None})
            continue
        world_model = enrich_trade_signal(ticker, signal)
        enriched_signals.append({**signal, "world_model": world_model})
    return {**report, "signals": enriched_signals, "enriched_at": datetime.now(UTC).isoformat()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Enrich agent reports with world-model context.")
    parser.add_argument("--date", default=None, help="Report date YYYY-MM-DD (default: today UTC).")
    args = parser.parse_args()

    date_str = args.date or datetime.now(UTC).strftime("%Y-%m-%d")
    report_path = REPORT_DIR / f"{date_str}.json"
    if not report_path.exists():
        print(f"No report: {report_path}")
        return 1

    report = json.loads(report_path.read_text(encoding="utf-8"))
    enriched = enrich_report(report)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{date_str}.json"
    out_path.write_text(json.dumps(enriched, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote enriched report: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
