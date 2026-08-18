#!/usr/bin/env python3
"""Refresh improvement_queue.md from the Hub parquet ledger.

Keeps Output/system_learning/latest/improvement_queue.md separate from
Output/current/NEXT_ACTIONS.md (promotion-gate driven agent actions).

Usage:
    python3 scripts/refresh_improvement_queue_report.py
"""
from __future__ import annotations

import pandas as pd
from system_learning.reports.writer import render_improvement_queue_report

from scripts._runtime_io import ROOT, ensure_dir, surface_dir, utc_now

LEDGER_PATH = ROOT / "Data" / "system_learning" / "ledgers" / "improvement_queue.parquet"
REPORT_PATH = surface_dir("system_learning") / "latest" / "improvement_queue.md"


def _render(improvements: pd.DataFrame, generated_at: str) -> str:
    return render_improvement_queue_report(improvements, generated_at)


def main() -> None:
    generated_at = utc_now().isoformat()
    if not LEDGER_PATH.is_file():
        ensure_dir(REPORT_PATH.parent)
        REPORT_PATH.write_text(
            "# Improvement Queue\n\n"
            f"Generated: {generated_at}\n\n"
            "No improvement ledger found.\n",
            encoding="utf-8",
        )
        print(f"Improvement queue report (empty ledger): {REPORT_PATH}")
        return

    improvements = pd.read_parquet(LEDGER_PATH)
    content = _render(improvements, generated_at)
    ensure_dir(REPORT_PATH.parent)
    REPORT_PATH.write_text(content, encoding="utf-8")
    print(f"Improvement queue report: {REPORT_PATH} ({len(improvements)} items)")


if __name__ == "__main__":
    main()
