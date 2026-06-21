"""Standalone LightGBM experiment — do M/D/K/X velocity features improve prediction?

Compares:
  Baseline: standard market features (returns, volatility, momentum)
  Treatment: market features + M/D/K/X velocity features

This is simpler than modifying the full Qlib pipeline and directly
answers the question: do structural deformation features add
incremental predictive power?

Usage:
    python scripts/strategy_lab/qlib_experiment.py
    python scripts/strategy_lab/qlib_experiment.py --start 2010-01-01
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import _runtime_io as rio
from strategy_lab.data_loader import load_aligned, load_signals
from strategy_lab.risk_gate import compute_velocity_gate

OUTPUT_DIR = rio.ROOT / "Output" / "strategy_lab" / "qlib_experiment"


def build_market_features(close: pd.Series) -> pd.DataFrame:
    """Build standard market features from close prices."""
    f = pd.DataFrame(index=close.index)

    # Returns at various horizons
    for h in [1, 5, 10, 20, 60]:
        f[f"ret_{h}d"] = close.pct_change(h)

    # Volatility
    for w in [5, 10, 20, 60]:
        f[f"vol_{w}d"] = close.pct_change().rolling(w).std()

    # Momentum
    for w in [20, 60, 126]:
        f[f"mom_{w}d"] = close.pct_change(w)

    # Drawdown from rolling peak
    for w in [20, 60]:
        peak = close.rolling(w).max()
        f[f"dd_{w}d"] = (close - peak) / peak

    # RSI-like: proportion of up days
    for w in [10, 20]:
        up = (close.pct_change() > 0).rolling(w).mean()
        f[f"up_ratio_{w}d"] = up

    return f


def build_deformation_features(signals: pd.DataFrame) -> pd.DataFrame:
    """Build M/D/K/X deformation features."""
    f = pd.DataFrame(index=signals.index)

    # Raw channels
    for ch in ["M", "D", "K", "X"]:
        f[f"deform_{ch}"] = signals[ch]

    # Velocity at multiple windows
    for window in [5, 10, 20]:
        velocity = signals.diff(window)
        for ch in ["M", "D", "K", "X"]:
            f[f"deform_{ch}_vel{window}"] = velocity[ch]

    # Cofire count
    for window in [5, 10, 20]:
        velocity = signals.diff(window)
        cofire = pd.Series(0, index=signals.index)
        for ch in ["M", "D", "K", "X"]:
            cofire += (velocity[ch] > 0.2).astype(int)
        f[f"deform_cofire_{window}d"] = cofire

    # Velocity gate
    gate = compute_velocity_gate(signals)
    f["deform_velocity_gate"] = gate

    # Stress level (continuous)
    velocity_20d = signals.diff(20)
    max_vel = pd.Series(0.0, index=signals.index)
    for ch in ["M", "D", "K", "X"]:
        max_vel = np.maximum(max_vel, velocity_20d[ch].fillna(0))
    f["deform_stress_level"] = np.clip((max_vel - 1.5) / 2.0, 0, 1)

    return f


def run_experiment(
    start: str = "2010-01-01",
    end: str | None = None,
    train_end: str = "2020-12-31",
    forward_days: int = 5,
) -> dict:
    """Run baseline vs treatment LightGBM experiment.

    Predicts: N-day forward return (classification: positive or negative).
    """
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.metrics import accuracy_score, roc_auc_score

    # Load data
    data = load_aligned(start=start, end=end)
    signals = data[["M", "D", "K", "X"]]

    # Build features
    market_f = build_market_features(data["close"])
    deform_f = build_deformation_features(signals)

    # Target: forward N-day return sign
    target = (data["close"].shift(-forward_days) / data["close"] - 1 > 0).astype(int)
    target.name = "target"

    # Align and drop NaN
    baseline_df = pd.concat([market_f, target], axis=1).dropna()
    treatment_df = pd.concat([market_f, deform_f, target], axis=1).dropna()

    # Use common index
    common_idx = baseline_df.index.intersection(treatment_df.index)
    baseline_df = baseline_df.loc[common_idx]
    treatment_df = treatment_df.loc[common_idx]

    # Split train/test
    train_mask = baseline_df.index <= train_end
    test_mask = baseline_df.index > train_end

    # ── Baseline model ───────────────────────────────────────────────
    feature_cols_base = [c for c in baseline_df.columns if c != "target"]
    X_train_b = baseline_df.loc[train_mask, feature_cols_base]
    y_train_b = baseline_df.loc[train_mask, "target"]
    X_test_b = baseline_df.loc[test_mask, feature_cols_base]
    y_test_b = baseline_df.loc[test_mask, "target"]

    model_b = GradientBoostingClassifier(
        n_estimators=100, max_depth=4, learning_rate=0.05,
        subsample=0.8, random_state=42,
    )
    model_b.fit(X_train_b, y_train_b)

    pred_b = model_b.predict_proba(X_test_b)[:, 1]
    acc_b = accuracy_score(y_test_b, (pred_b > 0.5).astype(int))
    try:
        auc_b = roc_auc_score(y_test_b, pred_b)
    except ValueError:
        auc_b = 0.0

    # ── Treatment model ──────────────────────────────────────────────
    feature_cols_treat = [c for c in treatment_df.columns if c != "target"]
    X_train_t = treatment_df.loc[train_mask, feature_cols_treat]
    y_train_t = treatment_df.loc[train_mask, "target"]
    X_test_t = treatment_df.loc[test_mask, feature_cols_treat]
    y_test_t = treatment_df.loc[test_mask, "target"]

    model_t = GradientBoostingClassifier(
        n_estimators=100, max_depth=4, learning_rate=0.05,
        subsample=0.8, random_state=42,
    )
    model_t.fit(X_train_t, y_train_t)

    pred_t = model_t.predict_proba(X_test_t)[:, 1]
    acc_t = accuracy_score(y_test_t, (pred_t > 0.5).astype(int))
    try:
        auc_t = roc_auc_score(y_test_t, pred_t)
    except ValueError:
        auc_t = 0.0

    # ── Feature importance ───────────────────────────────────────────
    importances = pd.Series(
        model_t.feature_importances_, index=feature_cols_treat
    ).sort_values(ascending=False)

    deform_importance = importances[[c for c in importances.index if c.startswith("deform_")]]
    market_importance = importances[[c for c in importances.index if not c.startswith("deform_")]]

    # ── Directional accuracy when gate says EXIT vs FULL ─────────────
    if "deform_velocity_gate" in treatment_df.columns:
        gate_test = treatment_df.loc[test_mask, "deform_velocity_gate"]
        gate_exit = gate_test == 0
        gate_full = gate_test == 1

        if gate_exit.sum() > 10 and gate_full.sum() > 10:
            # When gate says EXIT: what % of time does market actually drop?
            actual_when_exit = y_test_t[gate_exit]
            exit_correct = (actual_when_exit == 0).mean()  # market dropped = correct

            actual_when_full = y_test_t[gate_full]
            full_correct = (actual_when_full == 1).mean()  # market rose = correct
        else:
            exit_correct = None
            full_correct = None
    else:
        exit_correct = None
        full_correct = None

    results = {
        "forward_days": forward_days,
        "train_period": f"{start} → {train_end}",
        "test_period": f"{train_end} → {end or 'latest'}",
        "n_train": int(train_mask.sum()),
        "n_test": int(test_mask.sum()),
        "baseline": {
            "n_features": len(feature_cols_base),
            "accuracy": round(float(acc_b), 4),
            "auc": round(float(auc_b), 4),
        },
        "treatment": {
            "n_features": len(feature_cols_treat),
            "n_deform_features": len([c for c in feature_cols_treat if c.startswith("deform_")]),
            "accuracy": round(float(acc_t), 4),
            "auc": round(float(auc_t), 4),
        },
        "delta": {
            "accuracy": round(float(acc_t - acc_b), 4),
            "auc": round(float(auc_t - auc_b), 4),
        },
        "velocity_gate_accuracy": {
            "exit_correct_rate": round(float(exit_correct), 4) if exit_correct is not None else None,
            "full_correct_rate": round(float(full_correct), 4) if full_correct is not None else None,
            "n_exit_days": int(gate_exit.sum()) if exit_correct is not None else None,
            "n_full_days": int(gate_full.sum()) if full_correct is not None else None,
        },
        "top_deform_features": {
            k: float(v) for k, v in deform_importance.head(10).items()
        },
        "top_market_features": {
            k: float(v) for k, v in market_importance.head(5).items()
        },
    }

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="LightGBM deformation feature experiment")
    parser.add_argument("--start", type=str, default="2010-01-01")
    parser.add_argument("--end", type=str, default=None)
    parser.add_argument("--train-end", type=str, default="2020-12-31")
    parser.add_argument("--forward", type=int, default=5, help="Forward return days (5 or 20)")
    args = parser.parse_args()

    print("Running LightGBM experiment...")
    print(f"  Market features vs Market + M/D/K/X velocity features")
    print(f"  Forward prediction: {args.forward} days")
    print()

    results = run_experiment(
        start=args.start, end=args.end,
        train_end=args.train_end, forward_days=args.forward,
    )

    # Print results
    print("=" * 70)
    print("RESULTS")
    print("=" * 70)
    print(f"  Train: {results['train_period']} ({results['n_train']} samples)")
    print(f"  Test:  {results['test_period']} ({results['n_test']} samples)")
    print()
    print(f"  Baseline (market only):  accuracy={results['baseline']['accuracy']:.4f}  AUC={results['baseline']['auc']:.4f}")
    print(f"  Treatment (+ deform):   accuracy={results['treatment']['accuracy']:.4f}  AUC={results['treatment']['auc']:.4f}")
    print(f"  Delta:                  accuracy={results['delta']['accuracy']:+.4f}  AUC={results['delta']['auc']:+.4f}")
    print()

    vga = results["velocity_gate_accuracy"]
    if vga["exit_correct_rate"] is not None:
        print(f"  Velocity gate accuracy:")
        print(f"    When EXIT: market dropped {vga['exit_correct_rate']:.1%} of the time ({vga['n_exit_days']} days)")
        print(f"    When FULL: market rose   {vga['full_correct_rate']:.1%} of the time ({vga['n_full_days']} days)")
        print()

    print("  Top deformation features (by importance):")
    for k, v in results["top_deform_features"].items():
        print(f"    {k}: {v:.4f}")
    print()

    # Save
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "lightgbm_experiment.json"
    out_path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(f"Saved to {out_path}")


if __name__ == "__main__":
    main()
