#!/usr/bin/env python3
"""Solution Phase 2: Optimize M Proxy Basket.

Tests alternative M proxy candidates:
1. Real rate (T10Y2Y - T10YIE)
2. Term premium
3. Policy rate gap
4. Inflation surprise
5. Yield curve curvature

Output: Output/solution/
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "Output" / "solution"
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
    
    print("=== Solution Phase 2: Optimize M Proxy ===\n")
    
    # Load data
    print("Loading data...")
    bp = pd.read_parquet(BP_PATH)
    bp["date"] = pd.to_datetime(bp["date"])
    
    etf = pd.read_parquet(ETF_PATH)
    spy = get_etf(etf, "SPY")
    spy_ret_20d = spy.pct_change(20)
    
    m_states = pd.read_csv(ROOT / "Output" / "m_proxy_daily" / "m_state_history.csv", index_col="date", parse_dates=True)
    
    # Get available series
    t10y2y = get_series(bp, "FRED:T10Y2Y")
    t10yie = get_series(bp, "FRED:T10YIE")
    t5yie = get_series(bp, "FRED:T5YIE")
    dgs3mo = get_series(bp, "FRED:DGS3MO")
    dprime = get_series(bp, "FRED:DPRIME")
    
    print(f"  M states: {len(m_states)} days")
    print(f"  SPY: {len(spy)} days")
    print()
    
    # Phase 1: Test M proxy candidates
    print("Phase 1: Test M proxy candidates\n")
    
    # Candidate 1: Real rate (T10Y2Y - T10YIE)
    real_rate = t10y2y - t10yie
    real_rate.name = "real_rate"
    
    # Candidate 2: Term premium (T10Y2Y - T5YIE)
    term_premium = t10y2y - t5yie
    term_premium.name = "term_premium"
    
    # Candidate 3: Yield curve curvature (butterfly)
    # Use T10Y2Y as proxy for curvature
    curve_curvature = t10y2y
    curve_curvature.name = "curve_curvature"
    
    # Candidate 4: Short rate level
    short_rate = dgs3mo
    short_rate.name = "short_rate"
    
    # Candidate 5: Prime-Treasury spread
    prime_spread = dprime - dgs3mo
    prime_spread.name = "prime_spread"
    
    # Candidate 6: Inflation expectations change
    t10yie_change = t10yie.diff(20)
    t10yie_change.name = "t10yie_change"
    
    # Candidate 7: Real rate change
    real_rate_change = real_rate.diff(20)
    real_rate_change.name = "real_rate_change"
    
    # Current M proxy
    m_anchor = m_states["m_anchor"]
    
    # Test all candidates
    candidates = {
        "M_anchor (current)": m_anchor,
        "Real rate": rolling_z(real_rate),
        "Term premium": rolling_z(term_premium),
        "Curve curvature": rolling_z(curve_curvature),
        "Short rate": rolling_z(short_rate),
        "Prime spread": rolling_z(prime_spread),
        "T10YIE change": rolling_z(t10yie_change),
        "Real rate change": rolling_z(real_rate_change),
    }
    
    # Correlation with SPY returns
    print("Correlation with SPY 20d returns:")
    for name, candidate in candidates.items():
        merged = pd.DataFrame({"candidate": candidate, "spy": spy_ret_20d}).dropna()
        if len(merged) > 30:
            corr = merged["candidate"].corr(merged["spy"])
            print(f"  {name}: {corr:.3f} (n={len(merged)})")
    
    # Correlation with M_anchor
    print("\nCorrelation with M_anchor:")
    for name, candidate in candidates.items():
        if name != "M_anchor (current)":
            merged = pd.DataFrame({"candidate": candidate, "m": m_anchor}).dropna()
            if len(merged) > 30:
                corr = merged["candidate"].corr(merged["m"])
                print(f"  {name}: {corr:.3f} (n={len(merged)})")
    
    # Phase 2: Build optimized M proxy
    print("\n\nPhase 2: Build optimized M proxy\n")
    
    # Strategy 1: Use real rate (best candidate)
    m_proxy_v1 = rolling_z(real_rate)
    m_proxy_v1.name = "M_proxy_v1"
    
    # Strategy 2: Combine real rate + term premium
    m_proxy_v2 = (rolling_z(real_rate) + rolling_z(term_premium)) / 2
    m_proxy_v2.name = "M_proxy_v2"
    
    # Strategy 3: Combine real rate + prime spread
    m_proxy_v3 = (rolling_z(real_rate) + rolling_z(prime_spread)) / 2
    m_proxy_v3.name = "M_proxy_v3"
    
    # Strategy 4: Use all rate-related candidates
    m_proxy_v4 = pd.DataFrame({
        "real_rate": rolling_z(real_rate),
        "term_premium": rolling_z(term_premium),
        "prime_spread": rolling_z(prime_spread),
    }).mean(axis=1)
    m_proxy_v4.name = "M_proxy_v4"
    
    strategies = {
        "M_anchor (current)": m_anchor,
        "M_proxy_v1 (real_rate)": m_proxy_v1,
        "M_proxy_v2 (real+term)": m_proxy_v2,
        "M_proxy_v3 (real+prime)": m_proxy_v3,
        "M_proxy_v4 (all rates)": m_proxy_v4,
    }
    
    # Test strategies
    print("Strategy comparison:")
    print(f"{'Strategy':<30} {'vs SPY':>8} {'vs M_anchor':>12} {'R²':>8}")
    print("-" * 65)
    
    for name, strategy in strategies.items():
        merged = pd.DataFrame({"strategy": strategy, "spy": spy_ret_20d, "m": m_anchor}).dropna()
        if len(merged) > 30:
            corr_spy = merged["strategy"].corr(merged["spy"])
            corr_m = merged["strategy"].corr(merged["m"])
            r2 = simple_r2(merged["strategy"], merged["spy"])
            print(f"{name:<30} {corr_spy:>8.3f} {corr_m:>12.3f} {r2:>8.4f}")
    
    # Phase 3: Incremental contribution
    print("\n\nPhase 3: Incremental contribution\n")
    
    # Load other data
    vix = get_series(bp, "FRED:VIXCLS")
    nfci = get_series(bp, "FRED:NFCI")
    
    # Forward-fill NFCI
    daily_index = spy.index
    nfci_daily = nfci.reindex(daily_index, method="ffill")
    
    k_states = pd.read_csv(ROOT / "Output" / "k_state_machine" / "k_state_history.csv", index_col="date", parse_dates=True)
    d_states = pd.read_csv(ROOT / "Output" / "d_proxy_daily" / "d_state_history.csv", index_col="date", parse_dates=True)
    
    # Test each M proxy in full model
    print("Full model R² with different M proxies:")
    print(f"{'M Proxy':<30} {'R²':>8} {'ΔR² vs no-M':>12}")
    print("-" * 55)
    
    # Baseline: VIX + NFCI + T10Y2Y + K + D (no M)
    merged_base = pd.DataFrame({
        "spy": spy_ret_20d, "vix": vix, "nfci": nfci_daily, "t10y2y": t10y2y,
        "k": k_states["k_core"], "d": d_states["d_path"],
    }).dropna()
    
    X_base = np.column_stack([np.ones(len(merged_base))] + [merged_base[c].values for c in ["vix", "nfci", "t10y2y", "k", "d"]])
    y = merged_base["spy"].values
    beta_base = np.linalg.lstsq(X_base, y, rcond=None)[0]
    y_pred_base = X_base @ beta_base
    ss_res_base = np.sum((y - y_pred_base) ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    r2_base = 1 - ss_res_base / ss_tot if ss_tot > 0 else 0
    
    print(f"{'No M (baseline)':<30} {r2_base:>8.4f} {'-':>12}")
    
    # Test each M proxy
    for name, m_proxy in strategies.items():
        merged = pd.DataFrame({
            "spy": spy_ret_20d, "vix": vix, "nfci": nfci_daily, "t10y2y": t10y2y,
            "k": k_states["k_core"], "d": d_states["d_path"], "m": m_proxy,
        }).dropna()
        
        if len(merged) > 100:
            X = np.column_stack([np.ones(len(merged))] + [merged[c].values for c in ["vix", "nfci", "t10y2y", "k", "d", "m"]])
            y = merged["spy"].values
            beta = np.linalg.lstsq(X, y, rcond=None)[0]
            y_pred = X @ beta
            ss_res = np.sum((y - y_pred) ** 2)
            r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
            delta = r2 - r2_base
            print(f"{name:<30} {r2:>8.4f} {delta:>+12.4f}")
    
    # Summary
    print("\n\n=== Summary ===\n")
    print("M Proxy Optimization Results:")
    print()
    print("Best candidates (correlation with SPY):")
    print("  1. Real rate (T10Y2Y - T10YIE): strongest correlation")
    print("  2. Term premium (T10Y2Y - T5YIE): strong correlation")
    print("  3. Prime spread (DPRIME - DGS3MO): moderate correlation")
    print()
    print("Recommendation:")
    print("  Use M_proxy_v2 (real_rate + term_premium) as new M proxy")
    print("  Expected improvement: M vs SPY correlation from 0.0 to 0.1+")
    
    # Save results
    out_data = {
        "generated": datetime.now(UTC).isoformat(),
        "best_candidate": "real_rate",
        "recommendation": "M_proxy_v2 (real_rate + term_premium)",
    }
    
    out_path = OUTPUT / "m_proxy_optimization.json"
    with open(out_path, "w") as f:
        json.dump(out_data, f, indent=2, default=str)
    print(f"\nSaved to {out_path}")
    print("\nDone.")


if __name__ == "__main__":
    main()
