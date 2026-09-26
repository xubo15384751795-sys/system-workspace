#!/usr/bin/env python3
"""Strategy Lab — CLI entry point.

Run backtest comparing SPY 63-day momentum baseline vs baseline + System overlay.

Usage:
    python scripts/strategy_lab/run_backtest.py
    python scripts/strategy_lab/run_backtest.py --start 2010-01-01 --end 2025-12-31
    python scripts/strategy_lab/run_backtest.py --lookback 126
    python scripts/strategy_lab/run_backtest.py --shadow-card
    python scripts/strategy_lab/run_backtest.py --shadow-card --date 2026-06-18
    python scripts/strategy_lab/run_backtest.py --backfill

Output:
    Output/state/strategy_lab/backtest_report.md
    Output/state/strategy_lab/backtest_result.json
    Output/state/strategy_lab/shadow_cards/YYYY-MM-DD.json
"""
from __future__ import annotations

import argparse
import json
import sys

# Ensure scripts/ is on path for shared imports
from strategy_lab.backtest import run_comparison
from strategy_lab.data_loader import load_aligned
from strategy_lab.report import save_report
from strategy_lab.risk_gate import compute_position_series
from strategy_lab.shadow_card import (
    backfill_outcomes,
    generate_shadow_card,
    save_shadow_card,
)
from strategy_lab.strategies import (
    compute_baseline_position,
    compute_dynamic_lookback_position,
    compute_system_overlay_position,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Strategy Lab backtest")
    parser.add_argument("--start", type=str, default=None, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", type=str, default=None, help="End date YYYY-MM-DD")
    parser.add_argument("--lookback", type=int, default=63, help="Momentum lookback days (default 63)")
    parser.add_argument("--dynamic", action="store_true", help="Use dynamic lookback (vol-adaptive)")
    parser.add_argument("--shadow-card", action="store_true", help="Generate shadow decision card")
    parser.add_argument("--date", type=str, default=None, help="Date for shadow card (YYYY-MM-DD)")
    parser.add_argument("--backfill", action="store_true", help="Backfill shadow card outcomes")
    parser.add_argument("--cost-bps", type=float, default=3.0, help="One-way commission/spread bps")
    parser.add_argument("--slippage-bps", type=float, default=2.0, help="One-way slippage bps")
    parser.add_argument(
        "--bull-modulation",
        action="store_true",
        help="Raise velocity_threshold to 2.0 in calm bull regimes (63d mom>0, 21d vol<15 pct)",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON result to stdout")
    args = parser.parse_args()

    if args.backfill:
        n = backfill_outcomes()
        print(f"Backfilled outcomes for {n} shadow cards")
        return

    if args.shadow_card:
        card = generate_shadow_card(as_of=args.date)
        path = save_shadow_card(card)
        print(f"Shadow card saved to {path}")
        print(json.dumps(card, indent=2, ensure_ascii=False))
        return

    # ── Run backtest ─────────────────────────────────────────────────
    print(f"Loading data (start={args.start}, end={args.end})...")
    data = load_aligned(start=args.start, end=args.end)
    print(f"  {len(data)} trading days with aligned SPY + M/D/K/X data")

    if len(data) < 100:
        print("ERROR: Not enough data for meaningful backtest (need >= 100 days)")
        sys.exit(1)

    print(f"  Date range: {data.index[0].date()} → {data.index[-1].date()}")
    print()

    # Baseline: SPY momentum
    if args.dynamic:
        print("Computing dynamic lookback (vol-adaptive)...")
        baseline_pos = compute_dynamic_lookback_position(data["close"], data["return_1d"])
    else:
        print(f"Computing baseline (lookback={args.lookback}d)...")
        baseline_pos = compute_baseline_position(data["close"], lookback=args.lookback)

    # System overlay: risk gate
    print("Computing System risk gate overlay...")
    gate_kwargs: dict = {}
    if args.bull_modulation:
        gate_kwargs["bull_modulation"] = True
        print("  Bull modulation ON (threshold 1.5→2.0 in calm bulls)")
    signal_cols = [c for c in ["M", "D", "K", "X"] if c in data.columns]
    risk_pos = compute_position_series(
        data[signal_cols],
        close=data["close"],
        **gate_kwargs,
    )

    # Combined position
    overlay_pos = compute_system_overlay_position(baseline_pos, risk_pos["position_size"])

    # Run comparison (net of transaction costs)
    print(
        f"Running comparison (cost={args.cost_bps}bp + slippage={args.slippage_bps}bp "
        f"= {args.cost_bps + args.slippage_bps}bp one-way)..."
    )
    result = run_comparison(
        data["return_1d"],
        baseline_pos,
        overlay_pos,
        cost_bps=args.cost_bps,
        slippage_bps=args.slippage_bps,
    )
    result["config"] = {
        "lookback": args.lookback,
        "dynamic": bool(args.dynamic),
        "bull_modulation": bool(args.bull_modulation),
        "cost_bps": args.cost_bps,
        "slippage_bps": args.slippage_bps,
    }

    # Save report
    md_path, json_path = save_report(result)
    print()
    print(f"Report saved to {md_path}")
    print(f"JSON saved to {json_path}")

    # Print summary
    b = result["baseline"]
    o = result["overlay"]
    c = result["comparison"]
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Period: {b['start_date']} → {b['end_date']}")
    print(f"  Baseline total return: {b['total_return']:.2%}")
    print(f"  Overlay total return:  {o['total_return']:.2%}")
    print(f"  Return delta:          {c['return_delta']:+.2%}")
    print(f"  Baseline Sharpe:       {b['sharpe']:.3f}")
    print(f"  Overlay Sharpe:        {o['sharpe']:.3f}")
    print(f"  Sharpe delta:          {c['sharpe_delta']:+.3f}")
    print(f"  Baseline max DD:       {b['max_drawdown']:.2%}")
    print(f"  Overlay max DD:        {o['max_drawdown']:.2%}")
    print(f"  DD delta:              {c['max_dd_delta']:+.2%}")
    print(f"  Baseline time in mkt:  {b['time_in_market']:.2%}")
    print(f"  Overlay time in mkt:   {o['time_in_market']:.2%}")
    costs = result.get("costs") or {}
    if costs:
        print(f"  One-way friction:      {costs.get('one_way_bps')} bp")
        print(f"  Overlay total cost:    {costs.get('overlay_total_cost')}")

    if args.json:
        print()
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
