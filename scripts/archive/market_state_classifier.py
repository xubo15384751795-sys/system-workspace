#!/usr/bin/env python3
"""Market State Classifier — ML layer on top of M/D/K/X rule system.

Uses the same data as the rule-based system but adds:
1. HMM: discovers latent states from data (no manual thresholds)
2. XGBoost: predicts forward stress events

Output: Output/market_state_classifier/
"""
from __future__ import annotations

import json
import warnings
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "Output" / "market_state_classifier"
OUTPUT.mkdir(parents=True, exist_ok=True)

BP_PATH = ROOT / "Data" / "harvester" / "exports" / "latest" / "data" / "benchmark_panel.parquet"
ETF_PATH = ROOT / "Data" / "panels" / "cross_asset_daily_panel.parquet"


# ── Helpers ──────────────────────────────────────────────────────────────
def rolling_z(s: pd.Series, w: int = 60) -> pd.Series:
    mu = s.rolling(w, min_periods=20).mean()
    sig = s.rolling(w, min_periods=20).std().replace(0, np.nan)
    return ((s - mu) / sig).clip(-5, 5)


def get_series(bp: pd.DataFrame, sid: str) -> pd.Series:
    s = bp[bp["series_id"] == sid].sort_values("date").drop_duplicates("date").set_index("date")["value"]
    return s


def get_etf(etf: pd.DataFrame, sym: str) -> pd.Series:
    s = etf[etf["symbol"] == sym].sort_values("date").set_index("date")["close"]
    s.index = pd.to_datetime(s.index)
    return s


# ── Feature Engineering ──────────────────────────────────────────────────
def build_features(bp: pd.DataFrame, etf: pd.DataFrame) -> pd.DataFrame:
    """Build feature matrix from the same data sources as K/M/D state machines."""

    # --- M components (policy-market anchor gap) ---
    t10y2y = get_series(bp, "FRED:T10Y2Y")
    t10yie = get_series(bp, "FRED:T10YIE")
    dgs3mo = get_series(bp, "FRED:DGS3MO")
    dprime = get_series(bp, "FRED:DPRIME")
    real_rate = dgs3mo - t10yie

    # --- D components (funding/credit path) ---
    nfci = get_series(bp, "FRED:NFCI").resample("D").ffill()
    sofr_iorb = get_series(bp, "DERIVED:SOFR_IORB_SPREAD")
    hy_spread = get_series(bp, "FRED:BAMLH0A0HYM2")
    ig_spread = get_series(bp, "FRED:BAMLC0A4CBBB")
    nfci_lev = get_series(bp, "FRED:NFCILEVERAGE").resample("D").ffill()
    totbkcr = get_series(bp, "FRED:TOTBKCR").resample("D").ffill()

    # --- K components (curvature) ---
    skew = get_series(bp, "CBOE:SKEW")
    vvix = get_series(bp, "CBOE:VVIX")
    vix9d = get_series(bp, "CBOE:VIX9D")
    vix3m = get_series(bp, "CBOE:VIX3M")
    butterfly = vix9d - vix3m

    # --- Cross-asset features ---
    spy = get_etf(etf, "SPY")
    tlt = get_etf(etf, "TLT")
    hyg = get_etf(etf, "HYG")
    kre = get_etf(etf, "KRE")

    spy_ret = spy.pct_change()
    tlt_ret = tlt.pct_change()
    corr_spy_tlt = spy_ret.rolling(40).corr(tlt_ret)

    sectors = {sym: get_etf(etf, sym) for sym in ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]}
    sector_rets = pd.DataFrame({sym: s.pct_change() for sym, s in sectors.items()})
    sector_disp = sector_rets.rolling(20).std().mean(axis=1) * np.sqrt(252)

    spy_dd = (spy - spy.cummax()) / spy.cummax()

    # VIX / MOVE
    vix = get_series(bp, "FRED:VIXCLS")
    move = get_series(bp, "CBOE:MOVE")

    # --- Assemble raw series, then align to common date range ---
    # Use concat with inner join to find common dates
    raw = pd.concat({
        "m_curve": t10y2y, "m_inflation": t10yie, "m_short_rate": dgs3mo,
        "m_real_rate": real_rate, "m_prime": dprime,
        "d_funding": sofr_iorb, "d_credit": nfci, "d_leverage": nfci_lev,
        "d_spread_hy": hy_spread, "d_spread_ig": ig_spread, "d_bank_credit": totbkcr,
        "k_skew": skew, "k_vvix": vvix, "k_butterfly": butterfly,
        "corr_spy_tlt": corr_spy_tlt, "sector_dispersion": sector_disp,
        "spy_drawdown": spy_dd, "hyg_tlt_ratio": hyg / tlt, "kre_spy_ratio": kre / spy,
        "vix_level": vix, "move_level": move, "nfci_total": nfci,
    }, axis=1)

    # Forward fill then drop rows with too many NaN
    raw = raw.ffill().bfill()
    features = raw.dropna(thresh=15)

    # Apply rolling z-score to each column
    for col in features.columns:
        features[col] = rolling_z(features[col])

    # Drop initial NaN from rolling z
    features = features.dropna(thresh=15)

    return features


# ── HMM State Discovery ─────────────────────────────────────────────────
def run_hmm(features: pd.DataFrame, n_states: int = 5) -> dict:
    """Discover latent market states using Gaussian HMM."""
    from hmmlearn.hmm import GaussianHMM

    # Use core features for HMM (avoid multicollinearity)
    hmm_features = [
        "m_curve", "m_inflation", "m_real_rate",
        "d_credit", "d_spread_hy", "d_leverage",
        "k_skew", "k_vvix", "k_butterfly",
        "corr_spy_tlt", "sector_dispersion", "spy_drawdown",
        "vix_level",
    ]
    X = features[hmm_features].dropna()
    dates = X.index

    # Standardize
    from sklearn.preprocessing import StandardScaler
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # Fit HMM
    model = GaussianHMM(
        n_components=n_states,
        covariance_type="full",
        n_iter=200,
        random_state=42,
        tol=1e-4,
    )
    model.fit(X_scaled)
    states = model.predict(X_scaled)

    # Analyze states
    state_profiles = []
    for s in range(n_states):
        mask = states == s
        profile = {
            "state": s,
            "count": int(mask.sum()),
            "pct": float(mask.sum() / len(states) * 100),
            "mean_features": {},
        }
        for feat in hmm_features:
            profile["mean_features"][feat] = float(X.loc[mask, feat].mean())
        state_profiles.append(profile)

    # Transition matrix
    trans = model.transmat_.tolist()

    # Label states by their characteristics
    state_labels = label_hmm_states(state_profiles, hmm_features)

    return {
        "states": states.tolist(),
        "dates": [str(d) for d in dates],
        "profiles": state_profiles,
        "transitions": trans,
        "labels": state_labels,
        "feature_names": hmm_features,
        "score": float(model.score(X_scaled)),
    }


def label_hmm_states(profiles: list, features: list) -> dict:
    """Label HMM states based on feature profiles."""
    labels = {}
    for p in profiles:
        means = p["mean_features"]
        vix = means.get("vix_level", 0)
        dd = means.get("spy_drawdown", 0)
        credit = means.get("d_credit", 0)
        corr = means.get("corr_spy_tlt", 0)
        disp = means.get("sector_dispersion", 0)

        if vix > 1.5 and dd < -0.05:
            labels[p["state"]] = "CRISIS"
        elif vix > 0.8 and credit > 0.5:
            labels[p["state"]] = "STRESS"
        elif vix < -0.5 and credit < -0.3:
            labels[p["state"]] = "CALM"
        elif disp > 0.8:
            labels[p["state"]] = "DIVERGENCE"
        else:
            labels[p["state"]] = "NEUTRAL"

    # Make sure we don't have duplicate labels
    seen = {}
    for k, v in labels.items():
        if v in seen:
            labels[k] = f"{v}_{k}"
        seen[v] = k

    return labels


# ── XGBoost Stress Prediction ───────────────────────────────────────────
def run_xgboost(features: pd.DataFrame) -> dict:
    """Predict forward 20-day max drawdown using XGBoost."""
    from sklearn.metrics import classification_report, roc_auc_score
    from sklearn.model_selection import TimeSeriesSplit
    from xgboost import XGBClassifier

    # Build target: forward 20-day max drawdown > 5%
    spy = features["spy_drawdown"].copy()
    # Forward 20-day drawdown
    fwd_dd = spy.rolling(20).min().shift(-20)
    # Binary: stress = 1 if forward drawdown > 5%
    target = (fwd_dd < -0.05).astype(int)

    # Features (exclude spy_drawdown to avoid leakage)
    feat_cols = [c for c in features.columns if c != "spy_drawdown"]
    X = features[feat_cols].copy()
    y = target.copy()

    # Align and drop NaN
    mask = X.notna().all(axis=1) & y.notna()
    X = X[mask]
    y = y[mask]

    # Time series split
    tscv = TimeSeriesSplit(n_splits=5)
    results = {"folds": [], "feature_importance": {}}

    for fold, (train_idx, test_idx) in enumerate(tscv.split(X)):
        X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
        y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

        model = XGBClassifier(
            n_estimators=100,
            max_depth=4,
            learning_rate=0.1,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            use_label_encoder=False,
            eval_metric="logloss",
        )
        model.fit(X_train, y_train)

        y_pred = model.predict(X_test)
        y_proba = model.predict_proba(X_test)[:, 1]

        try:
            auc = roc_auc_score(y_test, y_proba)
        except ValueError:
            auc = 0.0

        report = classification_report(y_test, y_pred, output_dict=True, zero_division=0)

        results["folds"].append({
            "fold": fold,
            "train_size": len(train_idx),
            "test_size": len(test_idx),
            "auc": float(auc),
            "precision_stress": float(report.get("1", {}).get("precision", 0)),
            "recall_stress": float(report.get("1", {}).get("recall", 0)),
        })

    # Final model on full data for feature importance
    final_model = XGBClassifier(
        n_estimators=100, max_depth=4, learning_rate=0.1,
        subsample=0.8, colsample_bytree=0.8, random_state=42,
        use_label_encoder=False, eval_metric="logloss",
    )
    final_model.fit(X, y)

    importance = dict(zip(feat_cols, final_model.feature_importances_.tolist()))
    results["feature_importance"] = dict(sorted(importance.items(), key=lambda x: -x[1])[:15])
    results["target_distribution"] = {
        "stress_days": int(y.sum()),
        "normal_days": int((1 - y).sum()),
        "stress_pct": float(y.mean() * 100),
    }
    results["date_range"] = f"{X.index[0]} to {X.index[-1]}"
    results["total_days"] = len(X)

    return results


# ── Compare with Rule System ─────────────────────────────────────────────
def compare_with_rules(features: pd.DataFrame, hmm_result: dict) -> dict:
    """Compare HMM states with rule-based K states."""
    # Reconstruct K states from features (same logic as k_state_machine.py)
    k_core = features[["k_skew", "k_vvix", "k_butterfly"]].mean(axis=1)
    k_cross = pd.DataFrame({
        "corr_breakdown": -features["corr_spy_tlt"],
        "sector_divergence": features["sector_dispersion"],
        "credit_stress": -features["hyg_tlt_ratio"],
    }).mean(axis=1)

    def classify_k(core, cross):
        if core < -0.5:
            return "K1_COMPRESSION"
        elif cross >= 1.0 and core >= 1.0:
            return "K4_CURVATURE_BREAK"
        elif cross >= 0.5 and core >= 0.5:
            return "K3_CROSS_CONFIRMATION"
        elif core >= 1.0:
            return "K2_CORE_PRESSURE"
        else:
            return "K0_NORMAL"

    rule_states = []
    for i in range(len(k_core)):
        if pd.notna(k_core.iloc[i]) and pd.notna(k_cross.iloc[i]):
            rule_states.append(classify_k(k_core.iloc[i], k_cross.iloc[i]))
        else:
            rule_states.append("UNKNOWN")

    # Build comparison
    hmm_dates = hmm_result["dates"]
    hmm_states = hmm_result["states"]
    hmm_labels = hmm_result["labels"]

    # Align dates
    common_dates = features.index.intersection(pd.to_datetime(hmm_dates))
    if len(common_dates) == 0:
        return {"error": "no common dates"}

    # Cross-tabulation
    cross_tab = {}
    for d in common_dates:
        hmm_s = hmm_states[hmm_dates.index(str(d.date()))] if str(d.date()) in hmm_dates else None
        rule_s = rule_states[features.index.get_loc(d)] if d in features.index else None
        if hmm_s is not None and rule_s is not None:
            label = hmm_labels.get(str(hmm_s), f"state_{hmm_s}")
            key = f"HMM:{label} vs K:{rule_s}"
            cross_tab[key] = cross_tab.get(key, 0) + 1

    return {
        "cross_tabulation": cross_tab,
        "common_dates": len(common_dates),
        "rule_state_distribution": {s: rule_states.count(s) for s in set(rule_states)},
        "hmm_state_distribution": {hmm_labels.get(str(s), f"state_{s}"): hmm_states.count(s) for s in set(hmm_states)},
    }


# ── Main ─────────────────────────────────────────────────────────────────
def main():
    print("Loading data...")
    bp = pd.read_parquet(BP_PATH)
    etf = pd.read_parquet(ETF_PATH)

    print("Building features...")
    features = build_features(bp, etf)
    print(f"  Features: {features.shape[0]} days × {features.shape[1]} features")
    print(f"  Date range: {features.index[0]} to {features.index[-1]}")

    print("\nRunning HMM (5 states)...")
    hmm_result = run_hmm(features, n_states=5)
    print(f"  States discovered: {len(hmm_result['profiles'])}")
    for p in hmm_result["profiles"]:
        label = hmm_result["labels"].get(str(p["state"]), f"state_{p['state']}")
        print(f"    {label}: {p['count']} days ({p['pct']:.1f}%)")

    print("\nRunning XGBoost stress predictor...")
    xgb_result = run_xgboost(features)
    print(f"  Target: {xgb_result['target_distribution']['stress_pct']:.1f}% stress days")
    print(f"  Avg AUC: {np.mean([f['auc'] for f in xgb_result['folds']]):.3f}")
    print("  Top features:")
    for feat, imp in list(xgb_result["feature_importance"].items())[:8]:
        print(f"    {feat}: {imp:.4f}")

    print("\nComparing with rule-based K states...")
    comparison = compare_with_rules(features, hmm_result)
    if "error" not in comparison:
        print(f"  Common dates: {comparison['common_dates']}")
        print("  Rule state distribution:")
        for k, v in comparison["rule_state_distribution"].items():
            print(f"    {k}: {v}")

    # Save results
    output = {
        "timestamp": datetime.now(UTC).isoformat(),
        "feature_stats": {
            "days": features.shape[0],
            "features": features.shape[1],
            "date_range": f"{features.index[0]} to {features.index[-1]}",
        },
        "hmm": {
            "profiles": hmm_result["profiles"],
            "labels": hmm_result["labels"],
            "transitions": hmm_result["transitions"],
            "score": hmm_result["score"],
        },
        "xgboost": xgb_result,
        "comparison": comparison,
    }

    out_path = OUTPUT / "classifier_results.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
