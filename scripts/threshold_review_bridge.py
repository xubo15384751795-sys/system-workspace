#!/usr/bin/env python3
"""Threshold review bridge — convert failures into review candidates.

Reads feedback samples labeled missed_stress AND claim failures from
claim_evaluator.py, then generates threshold review candidates for human
review.  This script NEVER automatically changes thresholds — it only
surfaces cases so that a human can decide whether adjustments are warranted.

Input sources:
    1. Output/feedback_samples/replay_runs/*.json (missed_stress + false_positive)
    2. Output/system_learning/latest/claim_failures_pending.json (from claim_evaluator)

Output:
    Output/system_learning/latest/threshold_review_candidates.json

Usage:
    python3 scripts/threshold_review_bridge.py
    python3 scripts/threshold_review_bridge.py --json
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from _runtime_io import ROOT, ensure_dir, load_json, utc_now, write_json

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
FEEDBACK_DIR = ROOT / "Output" / "feedback_samples" / "replay_runs"
SUMMARY_PATH = ROOT / "Output" / "feedback_samples" / "calibration_summary.json"
SYSTEM_LEARNING_DIR = ROOT / "Output" / "system_learning" / "latest"
REPORT_PATH = SYSTEM_LEARNING_DIR / "threshold_review_candidates.json"
CLAIM_FAILURES_PATH = SYSTEM_LEARNING_DIR / "claim_failures_pending.json"

# ---------------------------------------------------------------------------
# Threshold constants (imported from _constants for reference)
# ---------------------------------------------------------------------------
# These are the current thresholds.  The review candidates include them
# so that a reviewer can see what the system was using at generation time.
FEEDBACK_SPY_1W_DROP = -0.03
FEEDBACK_SPY_1M_DROP = -0.05
FEEDBACK_MDD_WARNING = -0.05


# ---------------------------------------------------------------------------
# Candidate generation
# ---------------------------------------------------------------------------

def load_missed_stress_cases() -> list[dict[str, Any]]:
    """Load all feedback samples labeled missed_stress or false_positive."""
    cases = []
    if not FEEDBACK_DIR.exists():
        return cases
    for fpath in sorted(FEEDBACK_DIR.glob("*.json")):
        sample = load_json(fpath)
        if sample and sample.get("review_label") in ("missed_stress", "false_positive"):
            cases.append(sample)
    return cases


def load_claim_failures() -> list[dict[str, Any]]:
    """Load claim failures from claim_evaluator.py output.

    These are contradicted/invalidated claims with gate/threshold attribution.
    """
    if not CLAIM_FAILURES_PATH.exists():
        return []
    data = load_json(CLAIM_FAILURES_PATH)
    return data if isinstance(data, list) else []


def _claim_failure_to_candidate(failure: dict[str, Any]) -> dict[str, Any]:
    """Convert a claim failure item to a review candidate format."""
    meta = failure.get("metadata", {})
    md = meta.get("md_continuity", {})
    return {
        "sample_id": f"claim_{meta.get('entry_date', 'unknown')}_{meta.get('failure_status', '?')}",
        "as_of_date": meta.get("entry_date"),
        "sample_type": "claim_failure",
        "auto_label_reason": failure.get("item", ""),
        "decision": meta.get("failure_status", "unknown"),
        "confidence": "n/a",
        "claim_tier": meta.get("claim_tier"),
        "signal_state": {
            "m_value": md.get("entry_M"),
            "d_value": md.get("entry_D"),
            "k_value": None,
            "x_value": None,
        },
        "outcome": meta.get("outcome", {}),
        "current_thresholds": {},
        "gate_attribution": {
            "blocking_gates": meta.get("blocking_gates", []),
            "module_contributions": meta.get("module_contributions", {}),
        },
        "review_status": "pending",
        "reviewer_notes": "",
    }


def _extract_signal_state(sample: dict[str, Any]) -> dict[str, Any]:
    """Extract M/D/K/X signal state at the time of the missed case."""
    state = sample.get("system_state", {})
    return {
        "m_value": state.get("m_value"),
        "d_value": state.get("d_value"),
        "k_value": state.get("k_value"),
        "x_value": state.get("x_value"),
    }


def _extract_outcome_summary(sample: dict[str, Any]) -> dict[str, Any]:
    """Extract forward outcome summary."""
    fo = sample.get("forward_outcome", {})
    spy = fo.get("spy", {})
    vix = fo.get("vix", {})
    return {
        "spy_1w": spy.get("pct_1w"),
        "spy_1m": spy.get("pct_1m"),
        "max_drawdown_1m": fo.get("max_drawdown_1m"),
        "vix_change_1w": vix.get("change_1w"),
        "stress_event": fo.get("stress_event_happened"),
    }


def _cluster_by_pattern(cases: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Cluster missed_stress cases by signal pattern for pattern-level review."""
    clusters: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for case in cases:
        state = case.get("system_state", {})
        m = state.get("m_value")
        k = state.get("k_value")

        # Build a simple pattern key
        m_label = "m_high" if m is not None and m > 0.3 else "m_low" if m is not None and m < -0.3 else "m_mid"
        k_label = "k_high" if k is not None and k > 0.3 else "k_low" if k is not None and k < -0.3 else "k_mid"
        pattern = f"{m_label}_{k_label}"
        clusters[pattern].append(case)

    return dict(clusters)


def build_review_candidates(
    cases: list[dict[str, Any]],
    claim_failures: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build threshold review candidates from missed_stress and claim failure cases."""
    claim_failures = claim_failures or []

    # Merge claim failures into candidates
    claim_candidates = [_claim_failure_to_candidate(f) for f in claim_failures]

    if not cases and not claim_candidates:
        return {
            "schema_version": "system_learning.threshold_review.v1",
            "generated_at": utc_now().isoformat(),
            "candidate_count": 0,
            "candidates": [],
            "pattern_clusters": {},
            "status": "no_candidates",
            "notes": [
                "No missed_stress cases found. System thresholds may be adequate.",
                "Review-only output. Does not automatically change any thresholds.",
            ],
        }

    # Build individual candidates from feedback samples
    candidates = []
    for case in cases:
        judgment = case.get("system_judgment", {})
        label = case.get("review_label", "")
        candidate = {
            "sample_id": case.get("sample_id"),
            "as_of_date": case.get("as_of_date"),
            "sample_type": case.get("sample_type"),
            "auto_label_reason": case.get("auto_label_reason", ""),
            "decision": judgment.get("decision"),
            "confidence": judgment.get("confidence"),
            "claim_tier": judgment.get("claim_tier"),
            "signal_state": _extract_signal_state(case),
            "outcome": _extract_outcome_summary(case),
            "current_thresholds": {
                "spy_1w_drop": FEEDBACK_SPY_1W_DROP,
                "spy_1m_drop": FEEDBACK_SPY_1M_DROP,
                "mdd_warning": FEEDBACK_MDD_WARNING,
            },
            "failure_type": label,
            "review_status": "pending",
            "reviewer_notes": "",
        }
        candidates.append(candidate)

    # Merge claim failure candidates (with gate attribution)
    candidates.extend(claim_candidates)

    # Cluster by pattern
    clusters = _cluster_by_pattern(cases)
    pattern_summary = {}
    for pattern, pattern_cases in clusters.items():
        outcomes = [_extract_outcome_summary(c) for c in pattern_cases]
        mdd_vals = [o["max_drawdown_1m"] for o in outcomes if o["max_drawdown_1m"] is not None]
        spy_1w_vals = [o["spy_1w"] for o in outcomes if o["spy_1w"] is not None]

        pattern_summary[pattern] = {
            "count": len(pattern_cases),
            "avg_max_drawdown_1m": round(float(sum(mdd_vals) / len(mdd_vals)), 4) if mdd_vals else None,
            "avg_spy_1w": round(float(sum(spy_1w_vals) / len(spy_1w_vals)), 4) if spy_1w_vals else None,
            "sample_ids": [c.get("sample_id") for c in pattern_cases[:5]],  # first 5 for reference
        }

    # Generate threshold adjustment suggestions (informational only)
    suggestions = _generate_threshold_suggestions(cases)

    return {
        "schema_version": "system_learning.threshold_review.v1",
        "generated_at": utc_now().isoformat(),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "pattern_clusters": pattern_summary,
        "threshold_suggestions": suggestions,
        "status": "pending_review",
        "notes": [
            "Review-only output. Does NOT automatically change any thresholds.",
            "Each candidate represents a missed_stress case where the system said NO_TRADE but stress materialized.",
            "Pattern clusters group cases by M/K signal state to identify systematic gaps.",
            "Threshold suggestions are informational — a human must approve any changes.",
            "To approve a suggestion, update _constants.py and document the rationale.",
        ],
    }


def _generate_threshold_suggestions(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Generate threshold adjustment suggestions based on missed_stress patterns.

    These are purely informational.  The bridge NEVER auto-applies changes.
    """
    suggestions = []

    # Analyze MDD distribution of missed cases
    mdd_vals = [
        c.get("forward_outcome", {}).get("max_drawdown_1m")
        for c in cases
        if c.get("forward_outcome", {}).get("max_drawdown_1m") is not None
    ]
    if mdd_vals:
        avg_mdd = sum(mdd_vals) / len(mdd_vals)
        # If average missed MDD is much worse than current threshold, suggest review
        if avg_mdd < FEEDBACK_MDD_WARNING * 1.5:
            suggestions.append({
                "type": "threshold_review",
                "parameter": "FEEDBACK_MDD_WARNING",
                "current_value": FEEDBACK_MDD_WARNING,
                "observed_avg_missed": round(avg_mdd, 4),
                "observation": (
                    f"Average MDD of missed cases ({avg_mdd:.4f}) is significantly worse "
                    f"than current threshold ({FEEDBACK_MDD_WARNING}).  Consider whether "
                    f"the warning threshold is too lenient."
                ),
                "action_required": "Human review and approval in _constants.py",
            })

    # Analyze SPY 1w distribution
    spy_vals = [
        c.get("forward_outcome", {}).get("spy", {}).get("pct_1w")
        for c in cases
        if c.get("forward_outcome", {}).get("spy", {}).get("pct_1w") is not None
    ]
    if spy_vals:
        avg_spy = sum(spy_vals) / len(spy_vals)
        if avg_spy < FEEDBACK_SPY_1W_DROP:
            suggestions.append({
                "type": "threshold_review",
                "parameter": "FEEDBACK_SPY_1W_DROP",
                "current_value": FEEDBACK_SPY_1W_DROP,
                "observed_avg_missed": round(avg_spy, 4),
                "observation": (
                    f"Average SPY 1w return of missed cases ({avg_spy:.4f}) is worse "
                    f"than current threshold ({FEEDBACK_SPY_1W_DROP}).  Consider whether "
                    f"the system should have warned on these cases."
                ),
                "action_required": "Human review and approval in _constants.py",
            })

    # Stress window cluster analysis
    stress_cases = [c for c in cases if c.get("sample_type") == "stress_window"]
    if stress_cases:
        stress_rate = len(stress_cases) / len(cases) if cases else 0
        if stress_rate > 0.4:
            suggestions.append({
                "type": "pattern_review",
                "parameter": "stress_window_miss_rate",
                "current_value": round(stress_rate, 4),
                "observation": (
                    f"{len(stress_cases)}/{len(cases)} ({stress_rate:.0%}) of missed_stress "
                    f"cases come from stress_window samples.  This suggests the system's "
                    f"stress detection has systematic gaps during actual stress periods."
                ),
                "action_required": "Human review of stress_window sample generation and signal sensitivity",
            })

    return suggestions


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Threshold review bridge for missed_stress cases.")
    parser.add_argument("--json", action="store_true", help="Print report JSON to stdout.")
    args = parser.parse_args()

    ensure_dir(SYSTEM_LEARNING_DIR)
    cases = load_missed_stress_cases()
    claim_failures = load_claim_failures()
    report = build_review_candidates(cases, claim_failures)
    write_json(REPORT_PATH, report)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Threshold review candidates: {REPORT_PATH}")
        print(f"Candidates: {report['candidate_count']}")
        print(f"  from missed_stress/false_positive: {len(cases)}")
        print(f"  from claim_evaluator failures: {len(claim_failures)}")
        print(f"Status: {report['status']}")
        for pattern, summary in report.get("pattern_clusters", {}).items():
            print(f"  {pattern}: {summary['count']} cases, "
                  f"avg MDD={summary.get('avg_max_drawdown_1m', 'N/A')}")


if __name__ == "__main__":
    main()
