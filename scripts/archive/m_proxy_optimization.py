#!/usr/bin/env python3
"""M Proxy Optimization — Improve M proxy correlation with SPY.

Tests different M proxy constructions:
1. Component weights
2. Component combinations
3. Alternative series

Output: Output/m_proxy_optimized/
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "Output" / "m_proxy_optimized"
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


def simple_r2(x, y):
    df = pd.DataFrame({"x": x, "y": y}).dropna()
    if len(df) < 30:
        return None
    r = stats.linregress(df["x"].values, df["y"].values)
    return r.rvalue ** 2


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    
    print("=== M Proxy Optimization ===\n")
    
    # Load data
    print("Loading data...")
    bp = pd.read_parquet(BP_PATH)
    bp["date"] = pd.to_datetime(bp["date"])
    
    etf = pd.read_parquet(ETF_PATH)
    spy = get_etf(etf, "SPY")
    spy_ret_20d = spy.pct_change(20)
    
    # Get available series
    t10y2y = get_series(bp, "FRED:T10Y2Y")
    t10yie = get_series(bp, "FRED:T10YIE")
    t5yie = get_series(bp, "FRED:T5YIE")
    dgs3mo = get_series(bp, "FRED:DGS3MO")
    dprime = get_series(bp, "FRED:DPRIME")
    dff = get_series(bp, "FRED:DFF")
    
    print(f"  SPY: {len(spy)} days")
    print()
    
    # Phase 1: Test individual components
    print("Phase 1: Test individual components\n")
    
    components = {
        "T10Y2Y": rolling_z(t10y2y),
        "T10YIE": rolling_z(t10yie),
        "T5YIE": rolling_z(t5yie),
        "DGS3MO": rolling_z(dgs3mo),
        "DPRIME": rolling_z(dprime),
        "DFF": rolling_z(dff),
        "Real rate": rolling_z(dgs3mo - t10yie),
        "Term premium": rolling_z(t10y2y - t5yie),
        "T10Y2Y change": rolling_z(t10y2y.diff(20)),
        "T10YIE change": rolling_z(t10yie.diff(20)),
        "Real rate change": rolling_z((dgs3mo - t10yie).diff(20)),
    }
    
    print(f"{'Component':<25} {'vs SPY':>8}")
    print("-" * 40)
    
    component_corr = {}
    for name, comp in components.items():
        merged = pd.DataFrame({"comp": comp, "spy": spy_ret_20d}).dropna()
        if len(merged) > 30:
            corr = merged["comp"].corr(merged["spy"])
            component_corr[name] = corr
            print(f"{name:<25} {corr:>8.3f}")
    
    # Phase 2: Test combinations
    print("\n\nPhase 2: Test combinations\n")
    
    # Find best components
    sorted_corr = sorted(component_corr.items(), key=lambda x: abs(x[1]), reverse=True)
    print("Top 5 components (by absolute correlation):")
    for name, corr in sorted_corr[:5]:
        print(f"  {name}: {corr:.3f}")
    
    print()
    
    # Test combinations
    print("Combination candidates:")
    print(f"{'Combination':<30} {'vs SPY':>8}")
    print("-" * 45)
    
    combinations = {
        "T10Y2Y + T10YIE": (rolling_z(t10y2y) + rolling_z(t10yie)) / 2,
        "T10Y2Y + Real rate": (rolling_z(t10y2y) + rolling_z(dgs3mo - t10yie)) / 2,
        "T10Y2Y + Term premium": (rolling_z(t10y2y) + rolling_z(t10y2y - t5yie)) / 2,
        "Real rate + Term premium": (rolling_z(dgs3mo - t10yie) + rolling_z(t10y2y - t5yie)) / 2,
        "T10Y2Y + T10YIE + Real rate": (rolling_z(t10y2y) + rolling_z(t10yie) + rolling_z(dgs3mo - t10yie)) / 3,
        "T10Y2Y + Real rate + Term premium": (rolling_z(t10y2y) + rolling_z(dgs3mo - t10yie) + rolling_z(t10y2y - t5yie)) / 3,
        "All rate components": pd.DataFrame({
            "t10y2y": rolling_z(t10y2y),
            "t10yie": rolling_z(t10yie),
            "real": rolling_z(dgs3mo - t10yie),
            "term": rolling_z(t10y2y - t5yie),
        }).mean(axis=1),
        "T10YIE change + Real rate change": (rolling_z(t10yie.diff(20)) + rolling_z((dgs3mo - t10yie).diff(20))) / 2,
    }
    
    best_combination = None
    best_corr = 0
    
    for name, combo in combinations.items():
        merged = pd.DataFrame({"combo": combo, "spy": spy_ret_20d}).dropna()
        if len(merged) > 30:
            corr = merged["combo"].corr(merged["spy"])
            print(f"{name:<30} {corr:>8.3f}")
            if abs(corr) > abs(best_corr):
                best_corr = corr
                best_combination = name
    
    print(f"\nBest combination: {best_combination} (corr={best_corr:.3f})")
    
    # Phase 3: Optimize weights
    print("\n\nPhase 3: Optimize weights\n")
    
    # Use the best components
    top_components = [name for name, _ in sorted_corr[:3]]
    print(f"Using top 3 components: {top_components}")
    
    # Build component matrix
    comp_matrix = pd.DataFrame({name: components[name] for name in top_components}).dropna()
    comp_matrix["spy"] = spy_ret_20d
    comp_matrix = comp_matrix.dropna()
    
    if len(comp_matrix) > 100:
        # Simple weight optimization (equal weight vs correlation-weighted)
        X = comp_matrix[top_components].values
        y = comp_matrix["spy"].values
        
        # Correlation weights
        corrs = [component_corr[name] for name in top_components]
        total_abs_corr = sum(abs(c) for c in corrs)
        corr_weights = [abs(c) / total_abs_corr for c in corrs]
        
        # Weighted combination
        m_weighted = pd.Series(
            np.dot(X, corr_weights),
            index=comp_matrix.index
        )
        
        corr_weighted = m_weighted.corr(comp_matrix["spy"])
        print(f"Correlation-weighted M: {corr_weighted:.3f}")
        
        # Equal-weight combination
        m_equal = comp_matrix[top_components].mean(axis=1)
        corr_equal = m_equal.corr(comp_matrix["spy"])
        print(f"Equal-weight M: {corr_equal:.3f}")
        
        # OLS weights
        X_aug = np.column_stack([np.ones(len(X)), X])
        beta = np.linalg.lstsq(X_aug, y, rcond=None)[0]
        m_ols = pd.Series(X_aug @ beta, index=comp_matrix.index)
        corr_ols = m_ols.corr(comp_matrix["spy"])
        print(f"OLS-weighted M: {corr_ols:.3f}")
        print(f"  OLS weights: intercept={beta[0]:.4f}, " + ", ".join(f"{name}={w:.4f}" for name, w in zip(top_components, beta[1:])))
    
    # Phase 4: Build optimized M proxy
    print("\n\nPhase 4: Build optimized M proxy\n")
    
    # Use the best combination found
    if best_combination in combinations:
        m_optimized = combinations[best_combination]
    else:
        m_optimized = m_weighted
    
    # Test against current M proxy
    m_current = pd.read_csv(ROOT / "Output" / "m_proxy_daily" / "m_state_history.csv", index_col="date", parse_dates=True)["m_anchor"]
    
    merged = pd.DataFrame({
        "m_current": m_current,
        "m_optimized": m_optimized,
        "spy": spy_ret_20d,
    }).dropna()
    
    print(f"Current M vs SPY: {merged['m_current'].corr(merged['spy']):.3f}")
    print(f"Optimized M vs SPY: {merged['m_optimized'].corr(merged['spy']):.3f}")
    print(f"Improvement: {merged['m_optimized'].corr(merged['spy']) - merged['m_current'].corr(merged['spy']):+.3f}")
    
    # Phase 5: Summary
    print("\n\n=== Summary ===\n")
    print("M Proxy Optimization Results:")
    print()
    print(f"Best component: {sorted_corr[0][0]} (corr={sorted_corr[0][1]:.3f})")
    print(f"Best combination: {best_combination} (corr={best_corr:.3f})")
    print()
    print("Recommendation:")
    print(f"  Use {best_combination} as M proxy")
    print(f"  Expected correlation: {best_corr:.3f}")
    print(f"  Current correlation: {merged['m_current'].corr(merged['spy']):.3f}")
    
    # Save results
    out_data = {
        "generated": datetime.now(UTC).isoformat(),
        "best_component": sorted_corr[0][0],
        "best_component_corr": round(sorted_corr[0][1], 4),
        "best_combination": best_combination,
        "best_combination_corr": round(best_corr, 4),
        "current_corr": round(merged['m_current'].corr(merged['spy']), 4),
        "optimized_corr": round(merged['m_optimized'].corr(merged['spy']), 4),
    }
    
    out_path = OUTPUT / "m_proxy_optimization_results.json"
    with open(out_path, "w") as f:
        json.dump(out_data, f, indent=2, default=str)
    print(f"\nSaved to {out_path}")
    print("\nDone.")


if __name__ == "__main__":
    main()
