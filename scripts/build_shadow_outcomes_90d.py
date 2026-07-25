#!/usr/bin/env python3
"""Build Strategy Lab 90-day shadow outcomes summary.

Backfills forward returns on recent shadow cards, then aggregates evaluation
stats for promotion tracking.

Usage:
    python3 scripts/build_shadow_outcomes_90d.py
    python3 scripts/build_shadow_outcomes_90d.py --days 90 --json

Output:
    Output/strategy_lab/shadow_outcomes_90d.json
"""
from __future__ import annotations

import argparse
import json

from strategy_lab.shadow_card import (  # noqa: E402
    backfill_outcomes,
    build_90d_outcomes_summary,
    save_90d_outcomes_summary,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build 90-day shadow outcomes summary.")
    parser.add_argument("--days", type=int, default=90, help="Rolling window in days")
    parser.add_argument("--skip-backfill", action="store_true", help="Skip outcome backfill")
    parser.add_argument("--json", action="store_true", help="Print summary JSON to stdout")
    args = parser.parse_args()

    if not args.skip_backfill:
        updated = backfill_outcomes(days=args.days)
        print(f"Backfilled {updated} shadow card(s)")

    summary = build_90d_outcomes_summary(days=args.days)
    path = save_90d_outcomes_summary(summary)
    print(f"Shadow outcomes summary: {path}")

    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print(f"  Cards in window: {summary.get('cards_total', 0)}")
        print(f"  With 20d outcome: {summary.get('cards_with_20d_outcome', 0)}")
        print(f"  Correct rate: {summary.get('correct_rate', 'N/A')}")


if __name__ == "__main__":
    main()
