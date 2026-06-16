#!/usr/bin/env python3
"""HMM Stability Audit — assess Hidden Markov Model reliability.

Reads HMM regime detection output and evaluates:
- Sample days and feature count
- Train window adequacy
- State distribution balance
- Rolling refit agreement
- Label stability across refits
- Posterior entropy (overconfidence check)

Usage:
    python3 scripts/hmm_stability_audit.py
    python3 scripts/hmm_stability_audit.py --json

Output:
    Output/hmm_stability/hmm_stability_audit.json
    Output/hmm_stability/hmm_stability_audit.md
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
HMM_DIR = ROOT / "Output" / "ml_signals"
HMM_LATEST = HMM_DIR / "latest" / "regime_hmm.json"
OUTPUT_DIR = ROOT / "Output" / "hmm_stability"


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def load_hmm_history() -> list[dict[str, Any]]:
    """Load all HMM outputs for rolling analysis."""
    history = []
    for path in sorted(HMM_DIR.glob("*/regime_hmm.json")):
        payload = load_json(path)
        if payload:
            payload["_path"] = str(path)
            history.append(payload)
    return history


def compute_posterior_entropy(probs: list[float]) -> float:
    """Compute Shannon entropy of posterior distribution."""
    arr = np.array(probs)
    arr = arr[arr > 0]
    if len(arr) == 0:
        return 0.0
    return float(-np.sum(arr * np.log2(arr)))


def compute_rolling_refit_agreement(history: list[dict[str, Any]], window: int = 20) -> float:
    """Compute agreement between consecutive HMM fits."""
    if len(history) < 2:
        return 0.0  # Not enough history

    agreements = []
    for i in range(1, len(history)):
        prev_regime = history[i - 1].get("regime", {}).get("current", "unknown")
        curr_regime = history[i].get("regime", {}).get("current", "unknown")
        agreements.append(1.0 if prev_regime == curr_regime else 0.0)

    return float(np.mean(agreements)) if agreements else 0.0


def compute_label_stability(history: list[dict[str, Any]], window: int = 10) -> float:
    """Compute stability of regime labels over recent window."""
    if len(history) < 2:
        return 0.0  # Not enough history

    recent = history[-min(window, len(history)):]
    regimes = [h.get("regime", {}).get("current", "unknown") for h in recent]
    unique = len(set(regimes))

    # Stability: 1.0 if all same, lower if more variety
    return 1.0 / unique if unique > 0 else 0.0


def check_state_distribution(hmm: dict[str, Any]) -> dict[str, Any]:
    """Check if state distribution is balanced."""
    regime = hmm.get("regime", {})
    
    # Try state_distribution first, then state_probs
    states = regime.get("state_distribution", {})
    if not states:
        states = regime.get("state_probs", {})

    if not states:
        return {"balanced": False, "reason": "No state distribution found"}

    total = sum(states.values())
    if total == 0:
        return {"balanced": False, "reason": "Zero total observations"}

    proportions = {k: v / total for k, v in states.items()}
    max_prop = max(proportions.values())
    min_prop = min(proportions.values())

    # Balanced if:
    # 1. No state dominates too much (< 0.95), OR
    # 2. At least 2 states have meaningful probability (> 0.01)
    states_with_prob = sum(1 for v in proportions.values() if v > 0.01)
    balanced = max_prop < 0.95 or states_with_prob >= 2

    return {
        "balanced": balanced,
        "proportions": {k: round(v, 3) for k, v in proportions.items()},
        "max_proportion": round(max_prop, 3),
        "min_proportion": round(min_prop, 3),
        "states_with_meaningful_prob": states_with_prob,
    }


def audit_hmm(hmm: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    """Run complete HMM stability audit."""
    regime = hmm.get("regime", {})
    stability = hmm.get("stability", {})
    provenance = hmm.get("provenance", {})

    # Basic metrics
    sample_days = int(stability.get("sample_days", provenance.get("input_row_count", 0)))
    feature_count = int(stability.get("feature_count", len(provenance.get("features") or provenance.get("feature_columns") or [])))
    train_window = stability.get("train_window", "unknown")

    # Posterior analysis
    current_prob = _as_float(regime.get("probability", regime.get("current_probability", 0)))
    state_probs_raw = regime.get("state_probs", regime.get("state_probabilities", []))
    if isinstance(state_probs_raw, dict):
        state_probs = list(state_probs_raw.values())
    else:
        state_probs = state_probs_raw
    posterior_entropy = compute_posterior_entropy(state_probs) if state_probs else 0.0

    # Rolling analysis
    rolling_refit = compute_rolling_refit_agreement(history)
    label_stability = compute_label_stability(history)

    # State distribution
    dist_check = check_state_distribution(hmm)

    # Stability grade
    issues = []
    grade = "ADEQUATE"

    if sample_days < 252:
        issues.append(f"Sample days={sample_days} < 252 — limited training data")
        grade = "WEAK"

    if feature_count < 3:
        issues.append(f"Feature count={feature_count} < 3 — may be underfitting")
        grade = "WEAK"

    if posterior_entropy < 0.1:
        issues.append(f"Posterior entropy={posterior_entropy:.3f} < 0.1 — possibly overconfident")
        grade = "WEAK"

    # Only check rolling refit if we have enough history
    if len(history) >= 2:
        if rolling_refit < 0.7:
            issues.append(f"Rolling refit agreement={rolling_refit:.3f} < 0.7 — unstable")
            grade = "WEAK"

        if label_stability < 0.6:
            issues.append(f"Label stability={label_stability:.3f} < 0.6 — regime labels unstable")
            grade = "WEAK"
    else:
        issues.append("Insufficient history for rolling refit/label stability checks")

    if not dist_check["balanced"]:
        issues.append(f"State distribution imbalanced: max={dist_check.get('max_proportion', '?')}")
        grade = "WEAK"

    if not issues:
        issues.append("All stability checks passed")

    # Usage recommendations
    if grade == "WEAK":
        allowed_use = "conflict_monitor_only"
        forbidden_use = ["regime_label", "primary_signal", "standalone_claim"]
    else:
        allowed_use = "regime_hint"
        forbidden_use = ["truth", "certainty", "standalone_signal"]

    return {
        "schema_version": "system.hmm_stability_audit.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "sample_days": sample_days,
        "feature_count": feature_count,
        "train_window": train_window,
        "current_regime": regime.get("current", "unknown"),
        "current_probability": current_prob,
        "posterior_entropy": round(posterior_entropy, 4),
        "rolling_refit_agreement": round(rolling_refit, 4),
        "label_stability": round(label_stability, 4),
        "state_distribution": dist_check,
        "stability_grade": grade,
        "issues": issues,
        "allowed_use": allowed_use,
        "forbidden_use": forbidden_use,
        "history_length": len(history),
    }


def format_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# HMM Stability Audit",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Stability grade: **{report['stability_grade']}**",
        "",
        "## Basic Metrics",
        "",
        f"- Sample days: {report['sample_days']}",
        f"- Feature count: {report['feature_count']}",
        f"- Train window: {report['train_window']}",
        f"- History length: {report['history_length']}",
        "",
        "## Current State",
        "",
        f"- Regime: {report['current_regime']}",
        f"- Probability: {report['current_probability']:.3f}",
        f"- Posterior entropy: {report['posterior_entropy']:.3f}",
        "",
        "## Stability Metrics",
        "",
        f"- Rolling refit agreement: {report['rolling_refit_agreement']:.3f}",
        f"- Label stability: {report['label_stability']:.3f}",
        "",
        "## State Distribution",
        "",
    ]

    dist = report["state_distribution"]
    if "proportions" in dist:
        for state, prop in dist["proportions"].items():
            lines.append(f"- {state}: {prop:.1%}")
    else:
        lines.append(f"- {dist.get('reason', 'Unknown')}")

    lines += [
        "",
        "## Issues",
        "",
    ]
    for issue in report["issues"]:
        lines.append(f"- {issue}")

    lines += [
        "",
        "## Usage",
        "",
        f"- Allowed: {report['allowed_use']}",
        "- Forbidden:",
    ]
    for item in report["forbidden_use"]:
        lines.append(f"  - {item}")

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit HMM stability.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    args = parser.parse_args()

    hmm = load_json(HMM_LATEST)
    if not hmm:
        print("No HMM output found at", HMM_LATEST)
        return

    history = load_hmm_history()
    report = audit_hmm(hmm, history)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUTPUT_DIR / "hmm_stability_audit.json"
    md_path = OUTPUT_DIR / "hmm_stability_audit.md"

    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(format_markdown(report), encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"HMM stability audit: {report['stability_grade']}")
        print(f"Sample days: {report['sample_days']}, Features: {report['feature_count']}")
        print(f"Posterior entropy: {report['posterior_entropy']:.3f}")
        print(f"Rolling refit: {report['rolling_refit_agreement']:.3f}")
        print(f"Label stability: {report['label_stability']:.3f}")


if __name__ == "__main__":
    main()
