#!/usr/bin/env python3
"""Weekly walk-forward validation — out-of-sample signal diagnostics.

Runs rolling-origin out-of-sample validation on M/D/K/X channel signals
against realized SPY forward returns.  This is a **weekly, validation-only**
script — it is NOT part of the daily core pipeline and its outputs are
review-only.  It does not change any thresholds, weights, or signals.

Output:
    Output/state/validation/walk_forward_report.json

Usage:
    python3 scripts/commands/weekly/weekly_walk_forward_validation.py
    python3 scripts/commands/weekly/weekly_walk_forward_validation.py --json
"""
from __future__ import annotations

import argparse
import json
import math
from typing import Any

import numpy as np
import pandas as pd

from verity.runtime._data_paths import resolve_cross_asset_panel_path
from verity.runtime.runtime_io import ROOT, ensure_dir, utc_now, write_json

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SIGNALS_PATH = ROOT / "Output" / "state" / "sandbox" / "structural_replay_v2" / "all_signals.parquet"
ETF_PANEL_PATH = resolve_cross_asset_panel_path()
VALIDATION_DIR = ROOT / "Output" / "state" / "validation"
REPORT_PATH = VALIDATION_DIR / "walk_forward_report.json"

# ---------------------------------------------------------------------------
# Config — live weekly WalkForward settings (validation-only).
# Authority: governance/ml_validation_policy.yaml (Output/state/validation/walk_forward_report.json).
# ---------------------------------------------------------------------------
TRAIN_WINDOW = 252      # 1 year training window
TEST_WINDOW = 63        # ~3 months test window
THRESHOLD_QUANTILE = 0.8
MIN_TRAIN = 126         # half year minimum
FORWARD_HORIZON = 5     # 5 trading days forward return for target

CHANNEL_COLUMNS = {
    "M": "channel_M",
    "D": "channel_D_contraction",
    "K": "channel_K",
    "X": "channel_X_agg",
}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_spy_returns() -> pd.Series:
    """Load SPY close prices and compute forward returns."""
    if not ETF_PANEL_PATH.exists():
        return pd.Series(dtype=float)
    panel = pd.read_parquet(ETF_PANEL_PATH)
    panel["date"] = pd.to_datetime(panel["date"])
    spy = panel[panel["symbol"] == "SPY"].sort_values("date").drop_duplicates("date")
    if spy.empty:
        return pd.Series(dtype=float)
    close = spy.set_index("date")["close"].astype(float).sort_index()
    # Forward return: close[t+5] / close[t] - 1
    forward_ret = close.shift(-FORWARD_HORIZON) / close - 1.0
    return forward_ret.dropna()


def _load_channel_signals() -> pd.DataFrame:
    """Load M/D/K/X channel signals."""
    if not SIGNALS_PATH.exists():
        return pd.DataFrame()
    signals = pd.read_parquet(SIGNALS_PATH)
    signals.index = pd.to_datetime(signals.index)
    available = {k: v for k, v in CHANNEL_COLUMNS.items() if v in signals.columns}
    if not available:
        return pd.DataFrame()
    channels = signals[[v for v in available.values()]].rename(
        columns={v: k for k, v in available.items()}
    )
    return channels.sort_index()


# ---------------------------------------------------------------------------
# Walk-forward engine
# ---------------------------------------------------------------------------

def _directional_accuracy(signal: pd.Series, target: pd.Series) -> float:
    """Compute fraction of times signal sign matches target sign."""
    aligned = pd.concat([signal.rename("s"), target.rename("t")], axis=1).dropna()
    if aligned.empty:
        return 0.0
    match = (aligned["s"] * aligned["t"] > 0) | ((aligned["s"] == 0) & (aligned["t"] == 0))
    return float(match.mean())


def _mse(signal: pd.Series, target: pd.Series) -> float:
    """Mean squared error between signal and target."""
    aligned = pd.concat([signal.rename("s"), target.rename("t")], axis=1).dropna()
    if aligned.empty:
        return float("nan")
    return float(((aligned["s"] - aligned["t"]) ** 2).mean())


def _r2_oos(signal: pd.Series, target: pd.Series) -> float:
    """Out-of-sample R-squared (can be negative if worse than mean prediction)."""
    aligned = pd.concat([signal.rename("s"), target.rename("t")], axis=1).dropna()
    if aligned.empty:
        return float("nan")
    ss_res = ((aligned["t"] - aligned["s"]) ** 2).sum()
    ss_tot = ((aligned["t"] - aligned["t"].mean()) ** 2).sum()
    if ss_tot == 0:
        return 0.0
    return float(1.0 - ss_res / ss_tot)


def _pct_above_threshold(signal: pd.Series, threshold: float) -> float:
    """Fraction of signal values above threshold."""
    clean = signal.dropna()
    if clean.empty:
        return 0.0
    return float((clean >= threshold).mean())


def rolling_walk_forward(
    signal: pd.Series,
    target: pd.Series,
    channel_name: str,
) -> list[dict[str, Any]]:
    """Run rolling-origin walk-forward validation for a single channel."""
    aligned = pd.concat([signal.rename("signal"), target.rename("target")], axis=1).dropna()
    if len(aligned) < MIN_TRAIN + TEST_WINDOW:
        return []

    # Verify no future leakage: signal index must be sorted
    if not aligned.index.is_monotonic_increasing:
        return []

    results = []
    start = MIN_TRAIN

    while start < len(aligned):
        train_start = max(0, start - TRAIN_WINDOW)
        train = aligned.iloc[train_start:start]
        test = aligned.iloc[start:start + TEST_WINDOW]

        if train.empty or test.empty:
            break

        # Threshold from training set
        threshold = float(train["signal"].quantile(THRESHOLD_QUANTILE))

        # Evaluate on test set
        test_signal = test["signal"]
        test_target = test["target"]

        dir_acc = _directional_accuracy(test_signal, test_target)
        mse = _mse(test_signal, test_target)
        r2 = _r2_oos(test_signal, test_target)

        # Binary signal: above threshold = stress warning
        binary_pred = test_signal >= threshold
        binary_target = test_target < 0  # negative return = stress
        tp = int((binary_pred & binary_target).sum())
        fp = int((binary_pred & ~binary_target).sum())
        fn = int((~binary_pred & binary_target).sum())
        _tn = int((~binary_pred & ~binary_target).sum())
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0

        results.append({
            "channel": channel_name,
            "train_start": str(train.index[0].date()),
            "train_end": str(train.index[-1].date()),
            "test_start": str(test.index[0].date()),
            "test_end": str(test.index[-1].date()),
            "train_days": len(train),
            "test_days": len(test),
            "threshold": round(threshold, 6),
            "direction_accuracy": round(dir_acc, 4),
            "mse": round(mse, 8) if not math.isnan(mse) else None,
            "r2_oos": round(r2, 4) if not math.isnan(r2) else None,
            "binary_precision": round(precision, 4),
            "binary_recall": round(recall, 4),
            "warn_fraction": round(float(binary_pred.mean()), 4),
        })

        start += TEST_WINDOW

    return results


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------

def build_walk_forward_report() -> dict[str, Any]:
    """Build the weekly walk-forward validation report."""
    spy_returns = _load_spy_returns()
    channels = _load_channel_signals()

    if spy_returns.empty or channels.empty:
        return {
            "schema_version": "validation.walk_forward.v1",
            "generated_at": utc_now().isoformat(),
            "status": "no_data",
            "error": "Missing signal or market data for walk-forward validation.",
        }

    # Align on common dates
    common_idx = channels.index.intersection(spy_returns.index)
    if len(common_idx) < MIN_TRAIN + TEST_WINDOW:
        return {
            "schema_version": "validation.walk_forward.v1",
            "generated_at": utc_now().isoformat(),
            "status": "insufficient_data",
            "error": f"Only {len(common_idx)} common dates; need at least {MIN_TRAIN + TEST_WINDOW}.",
        }

    channels = channels.loc[common_idx]
    target = spy_returns.loc[common_idx]

    # Run walk-forward for each channel
    all_results: dict[str, list[dict[str, Any]]] = {}
    channel_summaries: dict[str, dict[str, Any]] = {}

    for channel_name in channels.columns:
        signal = channels[channel_name]
        window_results = rolling_walk_forward(signal, target, channel_name)
        all_results[channel_name] = window_results

        if window_results:
            dir_accs = [r["direction_accuracy"] for r in window_results]
            r2s = [r["r2_oos"] for r in window_results if r["r2_oos"] is not None]
            channel_summaries[channel_name] = {
                "windows": len(window_results),
                "avg_direction_accuracy": round(float(np.mean(dir_accs)), 4),
                "std_direction_accuracy": round(float(np.std(dir_accs)), 4),
                "avg_r2_oos": round(float(np.mean(r2s)), 4) if r2s else None,
                "avg_binary_precision": round(
                    float(np.mean([r["binary_precision"] for r in window_results])), 4
                ),
                "avg_binary_recall": round(
                    float(np.mean([r["binary_recall"] for r in window_results])), 4
                ),
            }

    # Best channel by direction accuracy
    best_channel = None
    best_dir_acc = 0.0
    for ch, summary in channel_summaries.items():
        if summary["avg_direction_accuracy"] > best_dir_acc:
            best_dir_acc = summary["avg_direction_accuracy"]
            best_channel = ch

    return {
        "schema_version": "validation.walk_forward.v1",
        "generated_at": utc_now().isoformat(),
        "status": "complete",
        "config": {
            "train_window": TRAIN_WINDOW,
            "test_window": TEST_WINDOW,
            "threshold_quantile": THRESHOLD_QUANTILE,
            "min_train": MIN_TRAIN,
            "forward_horizon_days": FORWARD_HORIZON,
            "target": "SPY forward return",
        },
        "channel_summaries": channel_summaries,
        "best_channel": best_channel,
        "best_direction_accuracy": best_dir_acc,
        "window_details": all_results,
        "notes": [
            "Review-only diagnostic. Does not affect pipeline outputs or thresholds.",
            "Walk-forward uses rolling-origin: train on past, test on future.",
            "Direction accuracy > 0.5 suggests signal has some predictive content.",
            "R2_OOS > 0 means signal beats mean prediction; < 0 means worse.",
            "Binary signal: stress warning when channel value >= 80th percentile of training window.",
        ],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Weekly walk-forward validation.")
    parser.add_argument("--json", action="store_true", help="Print report JSON to stdout.")
    args = parser.parse_args()

    ensure_dir(VALIDATION_DIR)
    report = build_walk_forward_report()
    write_json(REPORT_PATH, report)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Walk-forward report: {REPORT_PATH}")
        print(f"Status: {report['status']}")
        for ch, summary in report.get("channel_summaries", {}).items():
            print(f"  {ch}: dir_acc={summary['avg_direction_accuracy']:.3f}, "
                  f"R2_OOS={summary.get('avg_r2_oos', 'N/A')}")


if __name__ == "__main__":
    main()
