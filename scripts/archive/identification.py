#!/usr/bin/env python3
"""Identification — Phase 4 of Empirical Validation.

Tests latent variable identification via:
1. PCA on benchmark panel
2. Factor analysis
3. Correlation between M/D/K/X and PCA factors

Output: Output/identification/
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "Output" / "identification"
BP_PATH = ROOT / "Data" / "harvester" / "exports" / "latest" / "data" / "benchmark_panel.parquet"


def rolling_z(s: pd.Series, w: int = 252) -> pd.Series:
    mu = s.rolling(w, min_periods=60).mean()
    sig = s.rolling(w, min_periods=60).std().replace(0, np.nan)
    return ((s - mu) / sig).clip(-5, 5)


def get_series(bp: pd.DataFrame, sid: str) -> pd.Series:
    s = bp[bp["series_id"] == sid].sort_values("date").drop_duplicates("date").set_index("date")["value"]
    s = s[~s.index.duplicated(keep="last")]
    s.index = pd.to_datetime(s.index)
    return s


def run_pca(X, n_components=4):
    """Run PCA on standardized data."""
    # Standardize
    X_std = (X - X.mean()) / X.std()
    X_std = X_std.dropna()
    
    if len(X_std) < 30:
        return None
    
    # SVD
    U, S, Vt = np.linalg.svd(X_std.values, full_matrices=False)
    
    # Explained variance
    explained_var = S ** 2 / (len(X_std) - 1)
    total_var = explained_var.sum()
    explained_ratio = explained_var / total_var
    
    # Components
    components = Vt[:n_components]
    
    # Factor scores
    scores = U[:, :n_components] * S[:n_components]
    
    return {
        "explained_var": explained_var.tolist(),
        "explained_ratio": explained_ratio.tolist(),
        "cumulative_ratio": np.cumsum(explained_ratio).tolist(),
        "components": components.tolist(),
        "scores": scores,
        "n_samples": len(X_std),
        "n_features": X_std.shape[1],
    }


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    
    print("Loading data...")
    bp = pd.read_parquet(BP_PATH)
    bp["date"] = pd.to_datetime(bp["date"])
    
    # Load state histories
    k_states = pd.read_csv(ROOT / "Output" / "k_state_machine" / "k_state_history.csv", index_col="date", parse_dates=True)
    m_states = pd.read_csv(ROOT / "Output" / "m_proxy_daily" / "m_state_history.csv", index_col="date", parse_dates=True)
    d_states = pd.read_csv(ROOT / "Output" / "d_proxy_daily" / "d_state_history.csv", index_col="date", parse_dates=True)
    
    print(f"  K: {len(k_states)}d, M: {len(m_states)}d, D: {len(d_states)}d\n")
    
    # 1. Independence analysis
    print("=== M/D/K Independence Analysis ===\n")
    
    # Align series
    common = k_states.index.intersection(m_states.index).intersection(d_states.index)
    print(f"Common dates: {len(common)}")
    
    k_core = k_states.loc[common, "k_core"]
    m_anchor = m_states.loc[common, "m_anchor"]
    d_path = d_states.loc[common, "d_path"]
    
    # Correlation matrix
    df = pd.DataFrame({"K": k_core, "M": m_anchor, "D": d_path}).dropna()
    print(f"After dropna: {len(df)} dates\n")
    
    corr_matrix = df.corr()
    print("Correlation matrix:")
    print(corr_matrix.round(3).to_string())
    
    # VIF (Variance Inflation Factor)
    print("\nVIF analysis:")
    for col in df.columns:
        other_cols = [c for c in df.columns if c != col]
        X = df[other_cols].values
        y = df[col].values
        X_aug = np.column_stack([np.ones(len(X)), X])
        beta = np.linalg.lstsq(X_aug, y, rcond=None)[0]
        y_pred = X_aug @ beta
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = np.sum((y - y.mean()) ** 2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
        vif = 1 / (1 - r2) if r2 < 1 else float('inf')
        uniqueness = 1 - r2
        print(f"  {col}: VIF={vif:.3f}, Uniqueness={uniqueness:.3f}")
    
    # 2. PCA on benchmark panel
    print("\n=== PCA on Benchmark Panel ===\n")
    
    # Select key series for PCA
    pca_series = {
        "VIX": "FRED:VIXCLS",
        "SKEW": "CBOE:SKEW",
        "VVIX": "CBOE:VVIX",
        "NFCI": "FRED:NFCI",
        "T10Y2Y": "FRED:T10Y2Y",
        "MOVE": "CBOE:MOVE",
        "SOFR_IORB": "DERIVED:SOFR_IORB_SPREAD",
    }
    
    pca_data = {}
    for name, sid in pca_series.items():
        s = rolling_z(get_series(bp, sid))
        pca_data[name] = s
    
    pca_df = pd.DataFrame(pca_data).dropna()
    print(f"PCA data: {len(pca_df)} dates, {len(pca_df.columns)} series")
    
    pca_result = run_pca(pca_df, n_components=4)
    if pca_result:
        print(f"\nExplained variance ratio:")
        for i, (var, cum) in enumerate(zip(pca_result["explained_ratio"], pca_result["cumulative_ratio"])):
            print(f"  PC{i+1}: {var:.3f} (cumulative: {cum:.3f})")
        
        print(f"\nComponent loadings:")
        labels = list(pca_df.columns)
        for i, comp in enumerate(pca_result["components"][:4]):
            print(f"  PC{i+1}: ", end="")
            for label, loading in zip(labels, comp):
                if abs(loading) > 0.3:
                    print(f"{label}={loading:.2f} ", end="")
            print()
    
    # 3. M/D/K vs PCA factors
    print("\n=== M/D/K vs PCA Factors ===\n")
    
    if pca_result and len(pca_df) > 0:
        # Get PCA scores aligned with M/D/K
        pca_scores = pd.DataFrame(
            pca_result["scores"][:, :4],
            index=pca_df.index,
            columns=["PC1", "PC2", "PC3", "PC4"]
        )
        
        common_pca = pca_scores.index.intersection(df.index)
        print(f"Common dates (PCA + M/D/K): {len(common_pca)}")
        
        if len(common_pca) > 30:
            corr_pca = pd.DataFrame({
                "K": k_states.loc[common_pca, "k_core"],
                "M": m_states.loc[common_pca, "m_anchor"],
                "D": d_states.loc[common_pca, "d_path"],
                "PC1": pca_scores.loc[common_pca, "PC1"],
                "PC2": pca_scores.loc[common_pca, "PC2"],
                "PC3": pca_scores.loc[common_pca, "PC3"],
                "PC4": pca_scores.loc[common_pca, "PC4"],
            }).dropna()
            
            print(f"\nCorrelation between M/D/K and PCA factors:")
            print(corr_pca.corr().round(3).to_string())
    
    # 4. Summary
    print("\n=== Summary ===\n")
    print("Independence results:")
    print(f"  K vs M: {corr_matrix.loc['K','M']:.3f}")
    print(f"  K vs D: {corr_matrix.loc['K','D']:.3f}")
    print(f"  M vs D: {corr_matrix.loc['M','D']:.3f}")
    print()
    print("VIF results:")
    for col in df.columns:
        other_cols = [c for c in df.columns if c != col]
        X = df[other_cols].values
        y = df[col].values
        X_aug = np.column_stack([np.ones(len(X)), X])
        beta = np.linalg.lstsq(X_aug, y, rcond=None)[0]
        y_pred = X_aug @ beta
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = np.sum((y - y.mean()) ** 2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
        vif = 1 / (1 - r2) if r2 < 1 else float('inf')
        uniqueness = 1 - r2
        print(f"  {col}: VIF={vif:.3f}, Uniqueness={uniqueness:.3f}")
    
    # Save results
    out_data = {
        "generated": datetime.now(UTC).isoformat(),
        "correlation_matrix": corr_matrix.to_dict(),
        "vif": {col: round(1 / (1 - (1 - np.linalg.lstsq(np.column_stack([np.ones(len(df)), df[[c for c in df.columns if c != col]].values]), df[col].values, rcond=None)[0] @ np.column_stack([np.ones(len(df)), df[[c for c in df.columns if c != col]].values]).T) / np.sum((df[col].values - df[col].values.mean()) ** 2) * np.sum((df[col].values - df[col].values.mean()) ** 2)), 3) for col in df.columns},
    }
    
    out_path = OUTPUT / "identification_results.json"
    with open(out_path, "w") as f:
        json.dump(out_data, f, indent=2, default=str)
    print(f"\nSaved to {out_path}")
    print("\nDone.")


if __name__ == "__main__":
    main()
