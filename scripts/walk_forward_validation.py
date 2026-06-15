#!/usr/bin/env python3
"""Walk-Forward Validation — Phase 2 of Empirical Validation.

Tests out-of-sample prediction ability using rolling window approach.

Output: Output/walk_forward_validation/
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "Output" / "walk_forward_validation"
BP_PATH = ROOT / "Data" / "harvester" / "exports" / "latest" / "data" / "benchmark_panel.parquet"
ETF_PATH = ROOT / "Data" / "panels" / "cross_asset_daily_panel.parquet"


def rolling_z(s: pd.Series, w: int = 252) -> pd.Series:
    mu = s.rolling(w, min_periods=60).mean()
    sig = s.rolling(w, min_periods=60).std().replace(0, np.nan)
    return ((s - mu) / sig).clip(-5, 5)


def get_series(bp: pd.DataFrame, sid: str) -> pd.Series:
    s = bp[bp["series_id"] == sid].sort_values("date").drop_duplicates("date").set_index("date")["value"]
    s = s[~s.index.duplicated(keep="last")]
    s.index = pd.to_datetime(s.index)
    return s


def get_etf(etf: pd.DataFrame, sym: str) -> pd.Series:
    s = etf[etf["symbol"] == sym].drop_duplicates(subset="date", keep="last")
    s["date"] = pd.to_datetime(s["date"])
    s = s.set_index("date")["close"].sort_index()
    s = s[~s.index.duplicated(keep="last")]
    return s


def walk_forward_predict(y, X_dict, train_window=252*5, test_window=252):
    """Walk-forward prediction using rolling window.
    
    Returns DataFrame with actual and predicted values.
    """
    results = []
    
    # Align all series
    df = pd.DataFrame({"y": y, **X_dict}).dropna()
    if len(df) < train_window + test_window:
        return pd.DataFrame()
    
    dates = df.index
    n = len(df)
    
    for i in range(train_window, n, test_window):
        # Train window
        train_start = max(0, i - train_window)
        train_end = i
        test_start = i
        test_end = min(i + test_window, n)
        
        if test_start >= n:
            break
        
        train = df.iloc[train_start:train_end]
        test = df.iloc[test_start:test_end]
        
        # Build model
        X_cols = [c for c in df.columns if c != "y"]
        X_train = train[X_cols].values
        y_train = train["y"].values
        
        # Add constant
        X_train_aug = np.column_stack([np.ones(len(X_train)), X_train])
        
        # Fit
        try:
            beta = np.linalg.lstsq(X_train_aug, y_train, rcond=None)[0]
        except:
            continue
        
        # Predict
        X_test = test[X_cols].values
        X_test_aug = np.column_stack([np.ones(len(X_test)), X_test])
        y_pred = X_test_aug @ beta
        
        for j, (date, actual, predicted) in enumerate(zip(test.index, test["y"].values, y_pred)):
            results.append({"date": date, "actual": actual, "predicted": predicted})
    
    return pd.DataFrame(results).set_index("date")


def evaluate_predictions(df):
    """Evaluate prediction performance."""
    if len(df) == 0:
        return {}
    
    actual = df["actual"].values
    predicted = df["predicted"].values
    
    # Remove NaN/Inf
    mask = np.isfinite(actual) & np.isfinite(predicted)
    actual = actual[mask]
    predicted = predicted[mask]
    
    if len(actual) < 30:
        return {}
    
    # RMSE
    rmse = np.sqrt(np.mean((actual - predicted) ** 2))
    
    # MAE
    mae = np.mean(np.abs(actual - predicted))
    
    # Direction accuracy
    direction_actual = np.sign(actual)
    direction_predicted = np.sign(predicted)
    direction_accuracy = np.mean(direction_actual == direction_predicted)
    
    # R2 (out-of-sample)
    ss_res = np.sum((actual - predicted) ** 2)
    ss_tot = np.sum((actual - actual.mean()) ** 2)
    r2_oos = 1 - ss_res / ss_tot if ss_tot > 0 else 0
    
    # Correlation
    corr = np.corrcoef(actual, predicted)[0, 1]
    
    return {
        "n": len(actual),
        "rmse": round(rmse, 6),
        "mae": round(mae, 6),
        "direction_accuracy": round(direction_accuracy, 4),
        "r2_oos": round(r2_oos, 4),
        "corr": round(corr, 4),
    }


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    
    print("Loading data...")
    bp = pd.read_parquet(BP_PATH)
    bp["date"] = pd.to_datetime(bp["date"])
    
    etf = pd.read_parquet(ETF_PATH)
    
    k_states = pd.read_csv(ROOT / "Output" / "k_state_machine" / "k_state_history.csv", index_col="date", parse_dates=True)
    m_states = pd.read_csv(ROOT / "Output" / "m_proxy_daily" / "m_state_history.csv", index_col="date", parse_dates=True)
    d_states = pd.read_csv(ROOT / "Output" / "d_proxy_daily" / "d_state_history.csv", index_col="date", parse_dates=True)
    
    spy = get_etf(etf, "SPY")
    spy_ret_20d = spy.pct_change(20)
    
    # Benchmark series
    vix = get_series(bp, "FRED:VIXCLS")
    nfci = get_series(bp, "FRED:NFCI")
    t10y2y = get_series(bp, "FRED:T10Y2Y")
    
    print(f"  SPY: {len(spy)} days")
    print(f"  K: {len(k_states)}d, M: {len(m_states)}d, D: {len(d_states)}d\n")
    
    # Define models
    models = {
        "VIX-only": {"vix": vix},
        "NFCI-only": {"nfci": nfci},
        "T10Y2Y-only": {"t10y2y": t10y2y},
        "K-only": {"k": k_states["k_core"]},
        "D-only": {"d": d_states["d_path"]},
        "M-only": {"m": m_states["m_anchor"]},
        "K+D+M": {"k": k_states["k_core"], "d": d_states["d_path"], "m": m_states["m_anchor"]},
        "VIX+NFCI+T10Y2Y": {"vix": vix, "nfci": nfci, "t10y2y": t10y2y},
        "Full": {"vix": vix, "nfci": nfci, "t10y2y": t10y2y, "k": k_states["k_core"], "d": d_states["d_path"], "m": m_states["m_anchor"]},
    }
    
    # Walk-forward validation
    print("=== Walk-Forward Validation ===\n")
    print("Train window: 5 years (1260 days)")
    print("Test window: 1 year (252 days)")
    print("Target: SPY 20-day forward return\n")
    
    all_results = {}
    for model_name, X_dict in models.items():
        print(f"Model: {model_name}")
        pred_df = walk_forward_predict(spy_ret_20d, X_dict, train_window=252*5, test_window=252)
        eval_result = evaluate_predictions(pred_df)
        all_results[model_name] = eval_result
        
        if eval_result:
            print(f"  N={eval_result['n']}, RMSE={eval_result['rmse']:.4f}, "
                  f"Dir.Acc={eval_result['direction_accuracy']:.2%}, "
                  f"R²_OOS={eval_result['r2_oos']:.4f}, "
                  f"Corr={eval_result['corr']:.4f}")
        else:
            print("  Insufficient data")
        print()
    
    # Summary table
    print("=== Summary Table ===\n")
    print(f"{'Model':<25} {'N':>5} {'RMSE':>8} {'Dir.Acc':>8} {'R²_OOS':>8} {'Corr':>8}")
    print("-" * 70)
    for model_name, eval_result in all_results.items():
        if eval_result:
            print(f"{model_name:<25} {eval_result['n']:>5} {eval_result['rmse']:>8.4f} "
                  f"{eval_result['direction_accuracy']:>7.2%} {eval_result['r2_oos']:>8.4f} "
                  f"{eval_result['corr']:>8.4f}")
    
    # Save results
    out_data = {
        "generated": datetime.now(UTC).isoformat(),
        "config": {
            "train_window": 1260,
            "test_window": 252,
            "target": "SPY 20d forward return",
        },
        "models": all_results,
    }
    
    out_path = OUTPUT / "walk_forward_results.json"
    with open(out_path, "w") as f:
        json.dump(out_data, f, indent=2, default=str)
    print(f"\nSaved to {out_path}")
    print("\nDone.")


if __name__ == "__main__":
    main()
