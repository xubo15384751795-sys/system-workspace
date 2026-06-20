"""Signal Monitor — daily tracking of M+K prediction accuracy.

Reads M/D/K/X signals from structural_replay output and compares
with SPX forward returns. Outputs rolling agreement rates and
alerts when accuracy drops below threshold.

Usage:
    python scripts/signal_monitor.py
    python scripts/signal_monitor.py --json
    python scripts/signal_monitor.py --window 60

Exit codes:
    0 — signal accuracy above threshold
    1 — signal accuracy below threshold (degraded)
    2 — insufficient data
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from _constants import TRADING_DAYS_PER_YEAR
from _runtime_io import ROOT, ensure_dir, write_json

# ── Paths ───────────────────────────────────────────────────────────
SIGNALS_PATH = ROOT / "Output" / "sandbox" / "structural_replay_v2" / "all_signals.parquet"
BENCHMARK_PATH = ROOT / "Data" / "harvester" / "exports" / "latest" / "data" / "benchmark_panel.parquet"
OUTPUT_DIR = ROOT / "Output" / "signal_monitor"
ALERT_THRESHOLD = 0.55       # minimum acceptable agreement rate
MIN_SAMPLE = 30              # minimum days for a valid window
DEFAULT_WINDOW = 30           # default rolling window


def load_signals() -> pd.DataFrame | None:
    """Load M+K signal from structural replay output."""
    if not SIGNALS_PATH.exists():
        return None
    df = pd.read_parquet(SIGNALS_PATH)
    df.index = pd.to_datetime(df.index)
    cols = [c for c in ["channel_M", "channel_K"] if c in df.columns]
    if not cols:
        return None
    signals = df[cols].copy()
    signals.columns = [c.replace("channel_", "") for c in cols]
    # Composite: M+K average
    if "M" in signals.columns and "K" in signals.columns:
        signals["MK"] = (signals["M"] + signals["K"]) / 2
    return signals


def load_spx() -> pd.Series | None:
    """Load SPX close prices from benchmark panel."""
    if not BENCHMARK_PATH.exists():
        return None
    bp = pd.read_parquet(BENCHMARK_PATH)
    spx = bp[bp["series_id"] == "CBOE:SPX"].copy()
    if spx.empty:
        return None
    spx["date"] = pd.to_datetime(spx["date"])
    spx = spx.set_index("date").sort_index()
    return spx["value"].astype(float)


def compute_agreement(
    signals: pd.DataFrame,
    spx: pd.Series,
    horizon: int = 5,
    window: int = DEFAULT_WINDOW,
) -> dict:
    """Compute rolling direction agreement rates.

    Args:
        signals: DataFrame with M, K, MK columns.
        spx: SPX close price series.
        horizon: Forward return horizon in trading days.
        window: Rolling window size in trading days.

    Returns:
        Dict with rolling stats, current state, and alerts.
    """
    spx_ret = spx.pct_change(horizon).shift(-horizon)
    merged = signals.join(spx_ret.rename("ret"), how="inner").dropna()
    merged["market_up"] = merged["ret"] > 0

    if len(merged) < MIN_SAMPLE:
        return {"status": "INSUFFICIENT_DATA", "available_days": len(merged)}

    results = {}
    for col in ["M", "K", "MK"]:
        if col not in merged.columns:
            continue
        # Signal direction: negative = relief (bullish), positive = stress (bearish)
        signal_bullish = merged[col] < 0
        agreement = (signal_bullish == merged["market_up"])

        # Rolling agreement
        rolling_agree = agreement.rolling(window, min_periods=MIN_SAMPLE).mean()

        # Current values
        current = rolling_agree.iloc[-1] if not rolling_agree.empty else None
        latest_signal = "relief" if merged[col].iloc[-1] < 0 else "stress"
        latest_value = float(merged[col].iloc[-1])

        # Overall (last window days)
        tail_agree = agreement.iloc[-window:].mean() if len(agreement) >= window else agreement.mean()

        results[col] = {
            "current_rolling_agreement": round(float(current), 4) if current is not None else None,
            "last_{window}_day_agreement": round(float(tail_agree), 4),
            "latest_signal": latest_signal,
            "latest_value": round(latest_value, 4),
            "sample_days": len(merged),
            "degraded": bool(current is not None and current < ALERT_THRESHOLD),
        }

    # Composite alert
    mk = results.get("MK", {})
    degraded = mk.get("degraded", False)
    current_agree = mk.get("current_rolling_agreement")

    return {
        "status": "DEGRADED" if degraded else "OK",
        "alert_threshold": ALERT_THRESHOLD,
        "rolling_window": window,
        "forward_horizon_days": horizon,
        "channels": results,
        "timestamp": datetime.now(UTC).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Signal accuracy monitor")
    parser.add_argument("--json", action="store_true", help="Output JSON only")
    parser.add_argument("--window", type=int, default=DEFAULT_WINDOW, help="Rolling window size")
    parser.add_argument("--horizon", type=int, default=5, help="Forward return horizon (days)")
    args = parser.parse_args()

    signals = load_signals()
    if signals is None:
        if args.json:
            print(json.dumps({"status": "ERROR", "message": "No signal data found"}))
        else:
            print("ERROR: No signal data found at", SIGNALS_PATH)
        return 2

    spx = load_spx()
    if spx is None:
        if args.json:
            print(json.dumps({"status": "ERROR", "message": "No SPX data found"}))
        else:
            print("ERROR: No SPX data found at", BENCHMARK_PATH)
        return 2

    result = compute_agreement(signals, spx, horizon=args.horizon, window=args.window)

    # Save to output
    ensure_dir(OUTPUT_DIR)
    write_json(OUTPUT_DIR / "latest.json", result)
    # Append to history
    history_path = OUTPUT_DIR / "history.jsonl"
    with history_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False, default=str) + "\n")

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"Signal Monitor — {result['timestamp'][:10]}")
        print(f"Status: {result['status']}")
        print(f"Window: {result['rolling_window']}d, Horizon: {result['forward_horizon_days']}d")
        print()
        for ch, data in result.get("channels", {}).items():
            agree = data.get("current_rolling_agreement", "N/A")
            if isinstance(agree, float):
                agree = f"{agree:.1%}"
            flag = " ⚠️ DEGRADED" if data.get("degraded") else ""
            print(f"  {ch}: {agree} agreement, signal={data['latest_signal']} ({data['latest_value']:.2f}){flag}")

    return 1 if result["status"] == "DEGRADED" else 0


if __name__ == "__main__":
    sys.exit(main())
