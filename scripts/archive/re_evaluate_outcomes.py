#!/usr/bin/env python3
"""Re-evaluate past judgment outcomes with updated market data.

Reads eval_log.jsonl, recomputes SPY/HYG/TLT forward returns from the
updated cross-asset panel, and overwrites with actual outcomes.

Usage:
    python3 scripts/re_evaluate_outcomes.py
    python3 scripts/re_evaluate_outcomes.py --dry-run

Output:
    Output/evaluations/eval_log.jsonl  (overwritten with updated returns)
"""
from __future__ import annotations

import argparse
import json

import pandas as pd
from scripts._data_paths import resolve_cross_asset_panel_path
from scripts._runtime_io import ROOT, ensure_dir

EVAL_DIR = ROOT / "Output" / "evaluations"
EVAL_LOG_PATH = EVAL_DIR / "eval_log.jsonl"
ETF_PANEL = resolve_cross_asset_panel_path()

HORIZONS = {"1d": 1, "1w": 5, "1m": 21}
ETF_SYMBOLS = ("SPY", "HYG", "TLT")


def load_market_series() -> dict[str, pd.Series]:
    """Load SPY/HYG/TLT close-price series from the ETF panel."""
    if not ETF_PANEL.exists():
        return {}
    etf = pd.read_parquet(ETF_PANEL)
    etf["date"] = pd.to_datetime(etf["date"])
    series: dict[str, pd.Series] = {}
    for symbol in ETF_SYMBOLS:
        part = etf[etf["symbol"] == symbol].sort_values("date").drop_duplicates("date")
        if not part.empty:
            series[symbol] = part.set_index("date")["close"].astype(float)
    return series


def compute_forward_return(
    series: pd.Series, as_of: str, horizon_days: int,
) -> float | None:
    """Compute forward return (%) from as_of over horizon_days trading days."""
    clean = series.dropna().sort_index()
    if clean.empty:
        return None
    as_of_ts = pd.Timestamp(as_of)
    if clean.index.tz is not None and as_of_ts.tzinfo is None:
        as_of_ts = as_of_ts.tz_localize("UTC")
    pos = clean.index.searchsorted(as_of_ts, side="left")
    if pos >= len(clean):
        return None
    exit_pos = pos + horizon_days
    if exit_pos >= len(clean):
        return None
    entry = float(clean.iloc[pos])
    exit_ = float(clean.iloc[pos + horizon_days])
    if entry == 0:
        return None
    return round((exit_ / entry - 1.0) * 100.0, 4)


def classify_outcome(decision: str, confidence: str, spy_return: float | None) -> str:
    if spy_return is None:
        return "unverifiable"
    if decision in ("NO_TRADE", "WATCH_ONLY"):
        if spy_return <= 0:
            return "correct"
        elif spy_return < 0.5:
            return "neutral"
        else:
            return "incorrect"
    if decision in ("ACTIVE_WATCH", "WATCH"):
        return "neutral"
    if decision in ("TACTICAL_LONG", "HEDGE"):
        return "correct" if spy_return > 0 else "incorrect"
    if decision in ("TACTICAL_SHORT", "RISK_REDUCE"):
        return "correct" if spy_return < 0 else "incorrect"
    return "neutral"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not EVAL_LOG_PATH.exists():
        print("eval_log.jsonl not found")
        return

    # Load eval_log
    lines = EVAL_LOG_PATH.read_text(encoding="utf-8").strip().split("\n")
    records = [json.loads(line) for line in lines if line.strip()]
    print(f"Loaded {len(records)} eval_log records")

    # Load market data
    market = load_market_series()
    if not market:
        print("No market data available")
        return
    spy = market.get("SPY")
    print(f"SPY data: {len(spy)} rows, through {spy.index.max().date()}")

    # Re-evaluate
    updated = 0
    still_null = 0
    for r in records:
        # Get the judgment date from the record
        # The eval_log stores evaluated_at, but we need the original judgment date
        # Try to extract from eval_id (format: eval_YYYY-MM-DD_xxxx)
        eval_id = r.get("eval_id", "")
        parts = eval_id.split("_")
        if len(parts) >= 3:
            judgment_date = parts[1]  # YYYY-MM-DD
        else:
            judgment_date = r.get("evaluated_at", "")[:10]

        window = r.get("window", "1d")
        horizon = HORIZONS.get(window, 1)

        # Recompute returns
        returns = {}
        for sym, series in market.items():
            ret = compute_forward_return(series, judgment_date, horizon)
            returns[sym] = ret

        spy_return = returns.get("SPY")
        outcome = classify_outcome(
            r.get("decision", "UNKNOWN"),
            r.get("confidence", "unknown"),
            spy_return,
        )

        if spy_return is not None:
            updated += 1
        else:
            still_null += 1

        r["returns"] = returns
        r["outcome"] = outcome

    print(f"Re-evaluated: {updated} with returns, {still_null} still null")

    # Outcome distribution
    outcomes = {}
    for r in records:
        o = r.get("outcome", "unknown")
        outcomes[o] = outcomes.get(o, 0) + 1
    print(f"Outcome distribution: {outcomes}")

    if args.dry_run:
        print("(dry run, not writing)")
        return

    # Write back
    ensure_dir(EVAL_DIR)
    with EVAL_LOG_PATH.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Updated {EVAL_LOG_PATH}")


if __name__ == "__main__":
    main()
