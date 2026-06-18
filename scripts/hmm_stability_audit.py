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
import logging
from pathlib import Path
from typing import Any

import numpy as np

from _runtime_io import ensure_dir, load_json, utc_now, write_json

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
HMM_DIR = ROOT / "Output" / "ml_signals"
HMM_LATEST = HMM_DIR / "latest" / "regime_hmm.json"
OUTPUT_DIR = ROOT / "Output" / "hmm_stability"


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


def _get_model_signature(hmm: dict[str, Any]) -> str:
    """Extract a model signature from HMM output to group compatible history.

    Uses method + train_window + feature_count to identify model versions.
    """
    method = hmm.get("method", "unknown")
    stability = hmm.get("stability", {})
    train_window = stability.get("train_window", "unknown")
    feature_count = stability.get("feature_count", 0)
    return f"{method}:{train_window}:{feature_count}"


def _filter_history_by_signature(
    history: list[dict[str, Any]], signature: str,
) -> list[dict[str, Any]]:
    """Filter history to entries with matching model signature."""
    return [h for h in history if _get_model_signature(h) == signature]


def audit_hmm(hmm: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    """Run complete HMM stability audit.

    Splits assessment into two independent dimensions:
    - model_health: Is the model structurally sound? (PASS/WATCH/FAIL)
    - calibration_status: Do we have enough calibration data?
      (INSUFFICIENT_HISTORY / CALIBRATING / PASSED)

    This avoids conflating "model is bad" with "not enough history yet".
    """
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

    # Filter history by model signature to avoid mixing old/new model outputs
    model_signature = _get_model_signature(hmm)
    compatible_history = _filter_history_by_signature(history, model_signature)

    # Rolling analysis (only on compatible history)
    rolling_refit = compute_rolling_refit_agreement(compatible_history)
    label_stability = compute_label_stability(compatible_history)

    # State distribution
    dist_check = check_state_distribution(hmm)

    # Calibration data (from confidence_calibration wrapper, if present)
    cal = hmm.get("calibration", {})
    calibrated_confidence = regime.get("calibrated_confidence")
    calibration_passed = regime.get("calibration_passed")
    cal_history_len = cal.get("diagnostics", {}).get("calibration_history_length", 0)

    # ── Dimension 1: Model Health ────────────────────────────────────
    # Is the model structurally sound? Does it have enough data to fit?
    model_health_issues = []
    model_health = "PASS"

    if sample_days < 252:
        model_health_issues.append(f"Sample days={sample_days} < 252 — limited training data")
        model_health = "FAIL"

    if feature_count < 3:
        model_health_issues.append(f"Feature count={feature_count} < 3 — may be underfitting")
        model_health = "FAIL"

    if not dist_check["balanced"]:
        model_health_issues.append(f"State distribution imbalanced: max={dist_check.get('max_proportion', '?')}")
        model_health = "WATCH"

    if posterior_entropy < 0.01:
        # Extremely low entropy is a model health issue (degenerate posterior)
        model_health_issues.append(f"Posterior entropy={posterior_entropy:.4f} near zero — degenerate posterior")
        model_health = "FAIL"

    if not model_health_issues:
        model_health_issues.append("Model structure is healthy")

    # ── Dimension 2: Calibration Status ──────────────────────────────
    # Do we have enough history to trust the model's outputs?
    calibration_issues = []

    if len(compatible_history) < 2:
        calibration_status = "INSUFFICIENT_HISTORY"
        calibration_issues.append(
            f"Only {len(compatible_history)} compatible runs — "
            f"need >= 2 for rolling refit, >= 10 for calibration"
        )
    elif len(compatible_history) < 10:
        calibration_status = "CALIBRATING"
        if rolling_refit < 0.7:
            calibration_issues.append(
                f"Rolling refit agreement={rolling_refit:.3f} < 0.7 — "
                f"needs more consistent runs"
            )
        if label_stability < 0.6:
            calibration_issues.append(
                f"Label stability={label_stability:.3f} < 0.6 — "
                f"regime labels still stabilizing"
            )
        if not calibration_issues:
            calibration_issues.append(
                f"Rolling metrics OK but only {len(compatible_history)} runs — "
                f"need >= 10 for full calibration"
            )
    else:
        # 10+ compatible runs — check if calibration passes
        if rolling_refit >= 0.7 and label_stability >= 0.6 and posterior_entropy >= 0.1:
            calibration_status = "PASSED"
            calibration_issues.append("Calibration checks passed")
        else:
            calibration_status = "CALIBRATING"
            if rolling_refit < 0.7:
                calibration_issues.append(f"Rolling refit={rolling_refit:.3f} < 0.7")
            if label_stability < 0.6:
                calibration_issues.append(f"Label stability={label_stability:.3f} < 0.6")
            if posterior_entropy < 0.1:
                calibration_issues.append(f"Entropy={posterior_entropy:.3f} < 0.1")

    # ── Combined Grade (backward compat) ─────────────────────────────
    if model_health == "FAIL" or calibration_status == "INSUFFICIENT_HISTORY":
        grade = "WEAK"
    elif model_health == "WATCH" or calibration_status == "CALIBRATING":
        grade = "ADEQUATE"
    else:
        grade = "HIGH"

    # ── Usage Recommendations ────────────────────────────────────────
    # Split by claim type, not one-size-fits-all
    if model_health == "FAIL":
        allowed_use = "none"
        forbidden_use = ["regime_label", "mechanism_hypothesis", "any_claim"]
    elif calibration_status == "INSUFFICIENT_HISTORY":
        allowed_use = "conflict_monitor_only"
        forbidden_use = ["regime_label", "primary_signal", "standalone_claim"]
    elif calibration_status == "CALIBRATING":
        allowed_use = "regime_hint"
        forbidden_use = ["regime_label", "certainty", "standalone_signal"]
    else:
        allowed_use = "regime_hint"
        forbidden_use = ["truth", "certainty", "standalone_signal"]

    # What HMM can support regardless of calibration
    hmm_supportable = [
        "m_d_structural_readout",
        "mechanism_hypothesis",
        "watch_condition",
        "invalidation_condition",
        "conflict_monitoring",
    ]

    # What HMM blocks when not calibrated
    hmm_blocked_claims = []
    if calibration_status != "PASSED":
        hmm_blocked_claims = [
            "regime_call",
            "crisis_conclusion",
            "compression_conclusion",
            "directional_forecast",
            "trading_signal",
        ]

    # All issues combined for backward compat
    all_issues = model_health_issues + calibration_issues

    result = {
        "schema_version": "system.hmm_stability_audit.v2",
        "generated_at": utc_now().isoformat(),
        "sample_days": sample_days,
        "feature_count": feature_count,
        "train_window": train_window,
        "model_signature": model_signature,
        "compatible_history_length": len(compatible_history),
        "current_regime": regime.get("current", "unknown"),
        "current_probability": current_prob,
        "raw_probability": _as_float(regime.get("raw_probability", current_prob)),
        "posterior_entropy": round(posterior_entropy, 4),
        "rolling_refit_agreement": round(rolling_refit, 4),
        "label_stability": round(label_stability, 4),
        "state_distribution": dist_check,

        # New: split dimensions
        "model_health": {
            "grade": model_health,
            "issues": model_health_issues,
        },
        "calibration_status": {
            "status": calibration_status,
            "issues": calibration_issues,
            "compatible_history": len(compatible_history),
            "required_for_passed": 10,
        },

        # Claim-type-aware blocking
        "hmm_supportable_claims": hmm_supportable,
        "hmm_blocked_claims": hmm_blocked_claims,

        # Backward compat
        "stability_grade": grade,
        "issues": all_issues,
        "allowed_use": allowed_use,
        "forbidden_use": forbidden_use,
        "history_length": len(history),
    }

    # Add calibration fields if available
    if cal:
        result["calibration"] = {
            "calibrated_confidence": calibrated_confidence,
            "calibration_passed": calibration_passed,
            "cap_applied": cal.get("cap_applied"),
            "degradation_reasons": cal.get("degradation_reasons", []),
        }
    elif calibrated_confidence is not None:
        result["calibration"] = {
            "calibrated_confidence": calibrated_confidence,
            "calibration_passed": calibration_passed,
        }

    return result


def format_markdown(report: dict[str, Any]) -> str:
    mh = report.get("model_health", {})
    cs = report.get("calibration_status", {})
    lines = [
        "# HMM Stability Audit",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Stability grade: **{report['stability_grade']}**",
        f"- Model health: **{mh.get('grade', 'N/A')}**",
        f"- Calibration status: **{cs.get('status', 'N/A')}**",
        "",
        "## Basic Metrics",
        "",
        f"- Sample days: {report['sample_days']}",
        f"- Feature count: {report['feature_count']}",
        f"- Train window: {report['train_window']}",
        f"- Model signature: {report.get('model_signature', 'N/A')}",
        f"- History length: {report['history_length']} (compatible: {report.get('compatible_history_length', 'N/A')})",
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
        "## Model Health",
        "",
    ]
    for issue in mh.get("issues", []):
        lines.append(f"- {issue}")

    lines += [
        "",
        "## Calibration Status",
        "",
    ]
    for issue in cs.get("issues", []):
        lines.append(f"- {issue}")

    lines += [
        "",
        "## Claim-Type Blocking",
        "",
        "HMM supports:",
    ]
    for claim in report.get("hmm_supportable_claims", []):
        lines.append(f"- ✅ {claim}")
    if report.get("hmm_blocked_claims"):
        lines.append("")
        lines.append("HMM blocks:")
        for claim in report["hmm_blocked_claims"]:
            lines.append(f"- ❌ {claim}")

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
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Audit HMM stability.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    args = parser.parse_args()

    hmm = load_json(HMM_LATEST)
    if not hmm:
        logger.warning("No HMM output found at %s", HMM_LATEST)
        return

    history = load_hmm_history()
    report = audit_hmm(hmm, history)

    ensure_dir(OUTPUT_DIR)
    json_path = OUTPUT_DIR / "hmm_stability_audit.json"
    md_path = OUTPUT_DIR / "hmm_stability_audit.md"

    write_json(json_path, report)
    md_path.write_text(format_markdown(report), encoding="utf-8")

    if args.json:
        # CLI output — keep as print for piping
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        logger.info("HMM stability audit: %s", report['stability_grade'])
        logger.info("Sample days: %d, Features: %d", report['sample_days'], report['feature_count'])
        logger.info("Posterior entropy: %.3f", report['posterior_entropy'])
        logger.info("Rolling refit: %.3f", report['rolling_refit_agreement'])
        logger.info("Label stability: %.3f", report['label_stability'])


if __name__ == "__main__":
    main()
