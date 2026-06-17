#!/usr/bin/env python3
"""Proxy Validation — Phase 1 of Empirical Validation.

Validates proxy baskets against latent variables:
1. Correlation analysis
2. Incremental contribution (vs single-factor benchmarks)
3. Stability across sub-samples

Output: Output/proxy_validation/
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "Output" / "proxy_validation"
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


def multi_reg_r2(x1, x2, y):
    """Multiple regression R2."""
    df = pd.DataFrame({"x1": x1, "x2": x2, "y": y}).dropna()
    if len(df) < 30:
        return None
    X = np.column_stack([np.ones(len(df)), df["x1"].values, df["x2"].values])
    yr = df["y"].values
    beta = np.linalg.lstsq(X, yr, rcond=None)[0]
    y_pred = X @ beta
    ss_res = np.sum((yr - y_pred) ** 2)
    ss_tot = np.sum((yr - yr.mean()) ** 2)
    return 1 - ss_res / ss_tot if ss_tot > 0 else 0


def simple_r2(x, y):
    """Simple regression R2."""
    df = pd.DataFrame({"x": x, "y": y}).dropna()
    if len(df) < 30:
        return None
    r = stats.linregress(df["x"].values, df["y"].values)
    return r.rvalue ** 2


def run_validation(name, proxy, benchmarks, spy_ret):
    """Run full validation for one proxy."""
    print(f"=== {name} Proxy Validation ===\n")
    results = {}

    # 1. Correlation
    print("Correlation with benchmarks:")
    for bname, bseries in benchmarks.items():
        merged = pd.DataFrame({"proxy": proxy, "ref": bseries}).dropna()
        if len(merged) > 30:
            corr = merged["proxy"].corr(merged["ref"])
            print(f"  {name} vs {bname}: {corr:.3f} (n={len(merged)})")
            results[f"corr_{bname}"] = round(corr, 4)

    # 2. Incremental contribution
    print(f"\nIncremental contribution (vs SPY 20d return):")
    for bname, bseries in benchmarks.items():
        merged = pd.DataFrame({"spy": spy_ret, "base": bseries, "proxy": proxy}).dropna()
        if len(merged) > 100:
            r2_base = simple_r2(merged["base"], merged["spy"])
            r2_ext = multi_reg_r2(merged["base"], merged["proxy"], merged["spy"])
            if r2_base is not None and r2_ext is not None:
                delta = r2_ext - r2_base
                print(f"  vs {bname}: base R²={r2_base:.4f}, extended R²={r2_ext:.4f}, ΔR²={delta:+.4f}")
                results[f"delta_r2_vs_{bname}"] = round(delta, 4)
                results[f"r2_base_vs_{bname}"] = round(r2_base, 4)
                results[f"r2_ext_vs_{bname}"] = round(r2_ext, 4)

    # 3. Stability
    print(f"\nStability across sub-samples:")
    for start, end in [("1993-01-01","2000-01-01"), ("2000-01-01","2010-01-01"),
                        ("2010-01-01","2020-01-01"), ("2020-01-01","2026-12-31")]:
        sub = proxy[(proxy.index >= start) & (proxy.index <= end)].dropna()
        if len(sub) > 0:
            print(f"  {start[:4]}-{end[:4]}: mean={sub.mean():.3f}, std={sub.std():.3f}, n={len(sub)}")

    return results


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
    skew = rolling_z(get_series(bp, "CBOE:SKEW"))
    vvix = rolling_z(get_series(bp, "CBOE:VVIX"))

    print(f"  BP: {len(bp):,} rows")
    print(f"  SPY: {len(spy)} days ({spy.index.min().strftime('%Y-%m-%d')} to {spy.index.max().strftime('%Y-%m-%d')})")
    print(f"  K: {len(k_states)}d, M: {len(m_states)}d, D: {len(d_states)}d\n")

    # K proxy validation
    k_benchmarks = {"VIX": vix, "SKEW": skew, "VVIX": vvix}
    k_results = run_validation("K", k_states["k_core"], k_benchmarks, spy_ret_20d)

    # D proxy validation
    d_benchmarks = {"NFCI": nfci, "NFCI_Lev": get_series(bp, "FRED:NFCILEVERAGE")}
    d_results = run_validation("D", d_states["d_path"], d_benchmarks, spy_ret_20d)

    # M proxy validation
    m_benchmarks = {"T10Y2Y": t10y2y, "T10YIE": get_series(bp, "FRED:T10YIE")}
    m_results = run_validation("M", m_states["m_anchor"], m_benchmarks, spy_ret_20d)

    # Combined model
    print("\n=== Combined Model: SPY ~ VIX + NFCI + T10Y2Y + K + D + M ===\n")
    merged = pd.DataFrame({
        "spy": spy_ret_20d, "vix": vix, "nfci": nfci, "t10y2y": t10y2y,
        "k": k_states["k_core"], "d": d_states["d_path"], "m": m_states["m_anchor"],
    }).dropna()
    print(f"Common dates: {len(merged)}")

    if len(merged) > 100:
        y = merged["spy"].values

        # Single-factor baselines
        for factor in ["vix", "nfci", "t10y2y", "k", "d", "m"]:
            r2 = simple_r2(merged[factor], merged["spy"])
            if r2 is not None:
                print(f"  {factor}-only R²: {r2:.4f}")

        # Full model
        X = np.column_stack([np.ones(len(merged)), merged["vix"].values, merged["nfci"].values,
                             merged["t10y2y"].values, merged["k"].values, merged["d"].values, merged["m"].values])
        beta = np.linalg.lstsq(X, y, rcond=None)[0]
        y_pred = X @ beta
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = np.sum((y - y.mean()) ** 2)
        r2_full = 1 - ss_res / ss_tot
        print(f"\n  Full model R²: {r2_full:.4f}")
        labels = ["const", "vix", "nfci", "t10y2y", "k", "d", "m"]
        print(f"  Coefficients:")
        for l, b in zip(labels, beta):
            print(f"    {l}: {b:.6f}")

    # Summary
    print("\n=== Summary ===\n")
    all_results = {"generated": datetime.now(UTC).isoformat(), "k_proxy": k_results, "d_proxy": d_results, "m_proxy": m_results}
    for name, res in [("K", k_results), ("D", d_results), ("M", m_results)]:
        print(f"{name} proxy:")
        for key, val in res.items():
            print(f"  {key}: {val}")
        print()

    out_path = OUTPUT / "proxy_validation_results.json"
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"Saved to {out_path}")
    print("\nDone.")


if __name__ == "__main__":
    main()
