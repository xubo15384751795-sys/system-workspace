#!/usr/bin/env python3
"""Baseline comparison — evaluate system judgment against naive baselines.

Computes four baseline strategies over the same sample set used for
feedback calibration, then compares system judgment performance against
each.  This is a review-only diagnostic; it does not affect any pipeline
outputs or thresholds.

Baselines:
    1. no_signal     — never warns (always predicts calm)
    2. always_warn   — always warns (every day is a stress alert)
    3. random_freq    — warns at the system's actual warning frequency
    4. simple_rule    — warns when SPY 5d return < -2%

Output:
    Output/validation/baseline_comparison.json

Usage:
    python3 scripts/commands/weekly/baseline_comparison.py
    python3 scripts/commands/weekly/baseline_comparison.py --json
"""
from __future__ import annotations

import argparse
import json
from typing import Any

import numpy as np
import pandas as pd
from scripts._data_paths import resolve_cross_asset_panel_path
from scripts._runtime_io import ROOT, ensure_dir, load_json, utc_now, write_json

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
FEEDBACK_DIR = ROOT / "Output" / "feedback_samples" / "replay_runs"
VALIDATION_DIR = ROOT / "Output" / "validation"
REPORT_PATH = VALIDATION_DIR / "baseline_comparison.json"
PANEL_PATH = resolve_cross_asset_panel_path()

# ---------------------------------------------------------------------------
# Baseline strategies
# ---------------------------------------------------------------------------

def baseline_no_signal(n: int) -> np.ndarray:
    """Never warn — all predictions are 'no stress'."""
    return np.zeros(n, dtype=bool)


def baseline_always_warn(n: int) -> np.ndarray:
    """Always warn — every day is predicted as stress."""
    return np.ones(n, dtype=bool)


def baseline_random_freq(n: int, warn_fraction: float, seed: int = 42) -> np.ndarray:
    """Warn at the given frequency with fixed seed for reproducibility."""
    rng = np.random.default_rng(seed)
    return rng.random(n) < warn_fraction


def baseline_simple_rule(spy_returns: pd.Series, threshold: float = -0.02) -> np.ndarray:
    """Warn when SPY 5-day return is below threshold."""
    return (spy_returns < threshold).to_numpy(dtype=bool)


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------

def compute_metrics(
    predictions: np.ndarray,
    actual_stress: np.ndarray,
    label: str,
) -> dict[str, Any]:
    """Compute classification metrics for a baseline strategy."""
    pred = predictions.astype(bool)
    truth = actual_stress.astype(bool)

    tp = int((pred & truth).sum())
    fp = int((pred & ~truth).sum())
    fn = int((~pred & truth).sum())
    tn = int((~pred & truth).sum())  # BUG: should be (~pred & ~truth)
    # Fix: recalculate properly
    tn = int((~pred & ~truth).sum())

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    accuracy = (tp + tn) / len(truth) if len(truth) > 0 else 0.0
    false_alarm_rate = fp / (fp + tn) if (fp + tn) > 0 else 0.0
    missed_rate = fn / (fn + tp) if (fn + tp) > 0 else 0.0

    return {
        "strategy": label,
        "n": len(truth),
        "warn_count": int(pred.sum()),
        "warn_fraction": round(float(pred.mean()), 4),
        "actual_stress_count": int(truth.sum()),
        "actual_stress_fraction": round(float(truth.mean()), 4),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "accuracy": round(accuracy, 4),
        "false_alarm_rate": round(false_alarm_rate, 4),
        "missed_stress_rate": round(missed_rate, 4),
    }


# ---------------------------------------------------------------------------
# System judgment metrics from feedback samples
# ---------------------------------------------------------------------------

def load_system_judgments() -> list[dict[str, Any]]:
    """Load evaluated feedback samples with system judgment and outcomes."""
    samples = []
    if not FEEDBACK_DIR.exists():
        return samples
    for fpath in sorted(FEEDBACK_DIR.glob("*.json")):
        sample = load_json(fpath)
        if sample and sample.get("forward_outcome", {}).get("computed_at"):
            samples.append(sample)
    return samples


def extract_system_metrics(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute system judgment metrics from feedback samples."""
    if not samples:
        return {"n": 0, "error": "no evaluated samples found"}

    # System "warned" if decision was WATCH or RESEARCH_REVIEW (not NO_TRADE)
    warned = []
    actual_stress = []

    for s in samples:
        decision = s.get("system_judgment", {}).get("decision", "NO_TRADE")
        stress = s.get("forward_outcome", {}).get("stress_event_happened", False)
        warned.append(decision in ("WATCH", "RESEARCH_REVIEW", "ACTIVE_WATCH"))
        actual_stress.append(stress)

    pred = np.array(warned, dtype=bool)
    truth = np.array(actual_stress, dtype=bool)

    return compute_metrics(pred, truth, "system_judgment")


# ---------------------------------------------------------------------------
# Full comparison
# ---------------------------------------------------------------------------

def build_comparison() -> dict[str, Any]:
    """Build the full baseline comparison report."""
    samples = load_system_judgments()

    if not samples:
        return {
            "schema_version": "validation.baseline_comparison.v1",
            "generated_at": utc_now().isoformat(),
            "status": "no_data",
            "error": "No evaluated feedback samples found. Run evaluate_feedback_samples.py first.",
        }

    # Extract stress labels
    actual_stress = np.array([
        s.get("forward_outcome", {}).get("stress_event_happened", False)
        for s in samples
    ], dtype=bool)

    n = len(samples)
    system_stress_rate = float(actual_stress.mean())
    system_warn_count = sum(
        1 for s in samples
        if s.get("system_judgment", {}).get("decision") in ("WATCH", "RESEARCH_REVIEW", "ACTIVE_WATCH")
    )
    system_warn_fraction = system_warn_count / n if n > 0 else 0.0

    # Build baseline metrics
    baselines = [
        compute_metrics(baseline_no_signal(n), actual_stress, "no_signal"),
        compute_metrics(baseline_always_warn(n), actual_stress, "always_warn"),
        compute_metrics(
            baseline_random_freq(n, system_warn_fraction),
            actual_stress,
            "random_freq",
        ),
    ]

    # Simple rule baseline — needs SPY returns
    spy_returns = pd.Series([
        s.get("forward_outcome", {}).get("spy", {}).get("pct_1w")
        for s in samples
    ], dtype=float)
    # Use SPY 1w return as proxy for 5d return
    valid_spy = spy_returns.notna()
    if valid_spy.sum() > 0:
        simple_pred = np.zeros(n, dtype=bool)
        simple_pred[valid_spy] = baseline_simple_rule(
            spy_returns[valid_spy].fillna(0), threshold=-0.02
        )
        baselines.append(compute_metrics(simple_pred, actual_stress, "simple_rule"))
    else:
        baselines.append({
            "strategy": "simple_rule",
            "n": n,
            "error": "no SPY 1w returns available",
        })

    # System judgment metrics
    system_metrics = extract_system_metrics(samples)

    # Comparison table: does system beat each baseline?
    comparisons = []
    for bl in baselines:
        if "error" in bl:
            continue
        comparisons.append({
            "baseline": bl["strategy"],
            "system_f1": system_metrics.get("f1", 0),
            "baseline_f1": bl.get("f1", 0),
            "system_recall": system_metrics.get("recall", 0),
            "baseline_recall": bl.get("recall", 0),
            "system_missed_rate": system_metrics.get("missed_stress_rate", 0),
            "baseline_missed_rate": bl.get("missed_stress_rate", 0),
            "system_false_alarm_rate": system_metrics.get("false_alarm_rate", 0),
            "baseline_false_alarm_rate": bl.get("false_alarm_rate", 0),
            "system_beats_f1": system_metrics.get("f1", 0) > bl.get("f1", 0),
            "system_beats_recall": system_metrics.get("recall", 0) > bl.get("recall", 0),
        })

    return {
        "schema_version": "validation.baseline_comparison.v1",
        "generated_at": utc_now().isoformat(),
        "status": "complete",
        "sample_count": n,
        "actual_stress_rate": round(system_stress_rate, 4),
        "system_metrics": system_metrics,
        "baselines": baselines,
        "comparisons": comparisons,
        "notes": [
            "Review-only diagnostic. Does not affect pipeline outputs or thresholds.",
            "Baselines are computed over the same feedback sample set as system judgment.",
            "random_freq uses the system's actual warning frequency with seed=42.",
            "simple_rule warns when SPY 1w return < -2%.",
            "System 'warns' when decision is WATCH, RESEARCH_REVIEW, or ACTIVE_WATCH.",
        ],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Baseline comparison for ML validation hardening.")
    parser.add_argument("--json", action="store_true", help="Print report JSON to stdout.")
    args = parser.parse_args()

    ensure_dir(VALIDATION_DIR)
    report = build_comparison()
    write_json(REPORT_PATH, report)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Baseline comparison: {REPORT_PATH}")
        print(f"Status: {report['status']}")
        if report.get("comparisons"):
            for c in report["comparisons"]:
                beat = "✅" if c["system_beats_f1"] else "❌"
                print(f"  vs {c['baseline']}: F1 {beat} "
                      f"(system={c['system_f1']:.3f}, baseline={c['baseline_f1']:.3f})")


if __name__ == "__main__":
    main()
