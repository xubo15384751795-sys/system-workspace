#!/usr/bin/env python3
"""Benchmark Comparison — Phase 5 of Empirical Validation.

Compares System prediction ability against benchmark models:
1. Statistical tests (DM test, etc.)
2. Economic significance (Sharpe, information ratio)
3. Regime-specific performance

Output: Output/benchmark_comparison/
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "Output" / "benchmark_comparison"
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


def diebold_mariano_test(e1, e2, h=1):
    """Diebold-Mariano test for equal predictive ability.
    
    H0: E[d_t] = 0 where d_t = e1_t^2 - e2_t^2
    H1: E[d_t] != 0
    
    Returns: (dm_stat, p_value)
    """
    d = e1 ** 2 - e2 ** 2
    n = len(d)
    
    if n < 30:
        return None, None
    
    d_mean = d.mean()
    
    # Newey-West variance estimation
    gamma_0 = np.var(d, ddof=1)
    
    # Simple variance (no HAC for simplicity)
    var_d = gamma_0 / n
    
    if var_d <= 0:
        return None, None
    
    dm_stat = d_mean / np.sqrt(var_d)
    p_value = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    
    return round(dm_stat, 4), round(p_value, 4)


def compute_strategy_returns(predictions, actual_returns, threshold=0):
    """Compute strategy returns based on predictions.
    
    Long when predicted > threshold, short otherwise.
    """
    strategy = np.where(predictions > threshold, actual_returns, -actual_returns)
    return strategy


def compute_metrics(returns):
    """Compute performance metrics."""
    if len(returns) < 30:
        return {}
    
    returns = returns[np.isfinite(returns)]
    
    mean_ret = returns.mean()
    std_ret = returns.std()
    sharpe = mean_ret / std_ret if std_ret > 0 else 0
    
    # Annualize (assuming 20-day returns)
    ann_ret = mean_ret * 12.6  # ~252/20
    ann_vol = std_ret * np.sqrt(12.6)
    ann_sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    
    # Max drawdown
    cumulative = np.cumsum(returns)
    running_max = np.maximum.accumulate(cumulative)
    drawdown = running_max - cumulative
    max_dd = drawdown.max()
    
    # Win rate
    win_rate = (returns > 0).mean()
    
    return {
        "n": len(returns),
        "mean": round(mean_ret, 6),
        "std": round(std_ret, 6),
        "sharpe": round(sharpe, 4),
        "ann_ret": round(ann_ret, 4),
        "ann_vol": round(ann_vol, 4),
        "ann_sharpe": round(ann_sharpe, 4),
        "max_dd": round(max_dd, 4),
        "win_rate": round(win_rate, 4),
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
    
    print(f"  SPY: {len(spy)}d")
    print(f"  K: {len(k_states)}d, M: {len(m_states)}d, D: {len(d_states)}d\n")
    
    # Align all data
    merged = pd.DataFrame({
        "spy_ret": spy_ret_20d,
        "vix": vix,
        "nfci": nfci,
        "t10y2y": t10y2y,
        "k": k_states["k_core"],
        "d": d_states["d_path"],
        "m": m_states["m_anchor"],
        "k_state": k_states["state"],
    }).dropna()
    
    print(f"Common dates: {len(merged)}\n")
    
    # 1. Prediction comparison
    print("=== Prediction Comparison ===\n")
    
    # Generate predictions (simple sign-based)
    models = {
        "VIX": -merged["vix"],  # High VIX -> negative prediction
        "NFCI": -merged["nfci"],  # High NFCI -> negative prediction
        "T10Y2Y": merged["t10y2y"],
        "K": merged["k"],
        "D": -merged["d"],
        "M": -merged["m"],
        "K+D+M": (merged["k"] - merged["d"] - merged["m"]) / 3,
        "VIX+NFCI+T10Y2Y": (-merged["vix"] - merged["nfci"] + merged["t10y2y"]) / 3,
        "Full": (-merged["vix"] - merged["nfci"] + merged["t10y2y"] + merged["k"] - merged["d"] - merged["m"]) / 6,
    }
    
    actual = merged["spy_ret"].values
    
    # Compute strategy returns
    strategy_results = {}
    for model_name, pred in models.items():
        pred_vals = pred.values
        strategy_ret = compute_strategy_returns(pred_vals, actual)
        metrics = compute_metrics(strategy_ret)
        strategy_results[model_name] = metrics
        
        if metrics:
            print(f"{model_name}:")
            print(f"  Ann.Ret={metrics['ann_ret']:.2%}, Ann.Sharpe={metrics['ann_sharpe']:.3f}, "
                  f"Win={metrics['win_rate']:.2%}, MaxDD={metrics['max_dd']:.2%}")
    
    # 2. DM test
    print("\n=== Diebold-Mariano Test ===\n")
    print("H0: Models have equal predictive ability")
    print("H1: First model is better\n")
    
    # Compare K vs benchmarks
    k_pred = models["K"].values
    for bench_name in ["VIX", "NFCI", "T10Y2Y"]:
        bench_pred = models[bench_name].values
        e_k = actual - k_pred
        e_bench = actual - bench_pred
        dm_stat, p_val = diebold_mariano_test(e_k, e_bench)
        if dm_stat is not None:
            better = "K" if dm_stat < 0 else bench_name
            print(f"K vs {bench_name}: DM={dm_stat:.3f}, p={p_val:.3f} -> {better} better")
    
    # Compare K+D+M vs VIX+NFCI+T10Y2Y
    kdm_pred = models["K+D+M"].values
    vnt_pred = models["VIX+NFCI+T10Y2Y"].values
    e_kdm = actual - kdm_pred
    e_vnt = actual - vnt_pred
    dm_stat, p_val = diebold_mariano_test(e_kdm, e_vnt)
    if dm_stat is not None:
        better = "K+D+M" if dm_stat < 0 else "VIX+NFCI+T10Y2Y"
        print(f"K+D+M vs VIX+NFCI+T10Y2Y: DM={dm_stat:.3f}, p={p_val:.3f} -> {better} better")
    
    # Compare Full vs VIX+NFCI+T10Y2Y
    full_pred = models["Full"].values
    e_full = actual - full_pred
    dm_stat, p_val = diebold_mariano_test(e_full, e_vnt)
    if dm_stat is not None:
        better = "Full" if dm_stat < 0 else "VIX+NFCI+T10Y2Y"
        print(f"Full vs VIX+NFCI+T10Y2Y: DM={dm_stat:.3f}, p={p_val:.3f} -> {better} better")
    
    # 3. Regime-specific performance
    print("\n=== Regime-Specific Performance ===\n")
    
    for state_name in ["K0_NORMAL", "K1_COMPRESSION", "K2_CORE_PRESSURE"]:
        mask = merged["k_state"] == state_name
        sub = merged[mask]
        if len(sub) > 100:
            print(f"{state_name} (n={len(sub)}):")
            for model_name in ["VIX", "K", "K+D+M", "Full"]:
                pred_vals = models[model_name].loc[sub.index].values
                actual_vals = sub["spy_ret"].values
                strategy_ret = compute_strategy_returns(pred_vals, actual_vals)
                metrics = compute_metrics(strategy_ret)
                if metrics:
                    print(f"  {model_name}: Ann.Ret={metrics['ann_ret']:.2%}, Sharpe={metrics['ann_sharpe']:.3f}")
            print()
    
    # 4. Summary
    print("=== Summary ===\n")
    print("Benchmark Comparison Results:")
    print()
    for model_name, metrics in strategy_results.items():
        if metrics:
            print(f"  {model_name}: Ann.Ret={metrics['ann_ret']:.2%}, Sharpe={metrics['ann_sharpe']:.3f}, Win={metrics['win_rate']:.2%}")
    
    # Save results
    out_data = {
        "generated": datetime.now(UTC).isoformat(),
        "strategy_results": strategy_results,
    }
    
    out_path = OUTPUT / "benchmark_comparison_results.json"
    with open(out_path, "w") as f:
        json.dump(out_data, f, indent=2, default=str)
    print(f"\nSaved to {out_path}")
    print("\nDone.")


if __name__ == "__main__":
    main()
