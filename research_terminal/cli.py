#!/usr/bin/env python3
"""
Hermes Research Terminal - CLI

Usage:
    python -m research_terminal.cli --symbol GOOGL
    python -m research_terminal.cli --symbol NVDA --benchmark QQQ --start 2024-01-01
    python -m research_terminal.cli --symbol SPY --signals '[{"date":"2026-06-02","level":"HIGH","label":"AI CapEx"}]'
"""

import argparse
import json

from research_terminal.data.router import DataRouter
from research_terminal.strategies.engine import QuickBacktest
from research_terminal.report import generate_terminal_report


def main():
    parser = argparse.ArgumentParser(
        description="Hermes Research Terminal - Generate ticker research reports"
    )
    parser.add_argument(
        "--symbol", "-s", required=True,
        help="Ticker symbol (e.g., GOOGL, NVDA, SPY, BTC-USD)"
    )
    parser.add_argument(
        "--benchmark", "-b", default="SPY",
        help="Benchmark ticker (default: SPY)"
    )
    parser.add_argument(
        "--start", default="2024-01-01",
        help="Start date (default: 2024-01-01)"
    )
    parser.add_argument(
        "--end", default=None,
        help="End date (default: today)"
    )
    parser.add_argument(
        "--signals", default="[]",
        help='JSON array of signals: [{"date":"2026-06-02","level":"HIGH","label":"Event"}]'
    )
    parser.add_argument(
        "--themes", default="[]",
        help='JSON array of themes: ["AI CapEx","Cloud","Data Center"]'
    )

    args = parser.parse_args()

    # Parse signals and themes
    try:
        signals = json.loads(args.signals)
    except json.JSONDecodeError:
        signals = []

    try:
        themes = json.loads(args.themes)
    except json.JSONDecodeError:
        themes = []

    print("=" * 60)
    print(f"Hermes Research Terminal - {args.symbol}")
    print("=" * 60)

    # Generate report
    print(f"\n[1/3] Fetching {args.symbol} data...")
    print(f"[2/3] Running backtests vs {args.benchmark}...")
    print(f"[3/3] Generating report...")

    try:
        output_path = generate_terminal_report(
            symbol=args.symbol,
            start=args.start,
            end=args.end,
            benchmark=args.benchmark,
            signals=signals,
            themes=themes,
        )

        print(f"\n✅ Report generated: {output_path}")
        print(f"\nOpen in browser:")
        print(f"  open {output_path}")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
