#!/usr/bin/env python3
"""Build Learning Hub feedback summary from claim ladder and CaseLab reviews.

Aggregates:
- Claim ladder state transitions (promotions, demotions, invalidations)
- CaseLab context review statistics
- Mechanism calibration gate status
- Proxy lifecycle suggestions

Output:
    Output/system_learning/latest/claim_ladder_feedback.json
    Output/system_learning/latest/caselab_review_feedback.json
"""
from __future__ import annotations

import argparse
import json
from typing import Any

from scripts._runtime_io import ROOT, ensure_dir, load_json, load_jsonl, utc_now, write_json

CLAIM_LADDER_STATE = ROOT / "Output" / "claim_ladder" / "state.json"
FEEDBACK_LOG = ROOT / "caselab_context" / "feedback_log.jsonl"
CALIBRATION_GATE = ROOT / "Output" / "caselab" / "causal" / "mechanism_calibration_gate.json"
ALERT_PATH = ROOT / "Output" / "alerts" / "latest_alert.json"
ACCURACY_REPORT_PATH = ROOT / "Output" / "system_learning" / "latest" / "judgment_accuracy_report.json"
OUTPUT_DIR = ROOT / "Output" / "system_learning" / "latest"


def build_claim_ladder_feedback() -> dict[str, Any]:
    """Summarize claim ladder state for Learning Hub."""
    state = load_json(CLAIM_LADDER_STATE)
    if not state:
        return {
            "schema_version": "claim_ladder_feedback.v1",
            "generated_at": utc_now().isoformat(),
            "status": "no_state_file",
            "claims": [],
        }

    claims = state.get("claims", [])
    summary = state.get("summary", {})

    # Extract recent transitions
    recent_transitions = []
    for claim in claims:
        history = claim.get("history", [])
        if history:
            latest = history[-1]
            recent_transitions.append({
                "claim_id": claim.get("claim_id"),
                "mechanism_hypothesis": claim.get("mechanism_hypothesis", "")[:80],
                "action": latest.get("action"),
                "from_tier": latest.get("from_tier"),
                "to_tier": latest.get("to_tier"),
                "reasons": latest.get("reasons", []),
            })

    # Extract improvement suggestions
    improvement_items = []
    for claim in claims:
        blockers = claim.get("promotion_blockers", [])
        triggers = claim.get("demotion_triggers_active", [])
        if blockers:
            improvement_items.append({
                "claim_id": claim.get("claim_id"),
                "issue": "promotion_blocked",
                "details": [b.get("description", "") for b in blockers],
            })
        if triggers:
            improvement_items.append({
                "claim_id": claim.get("claim_id"),
                "issue": "demotion_risk",
                "details": [t.get("description", "") for t in triggers],
            })

    return {
        "schema_version": "claim_ladder_feedback.v1",
        "generated_at": utc_now().isoformat(),
        "status": "ok",
        "summary": summary,
        "recent_transitions": recent_transitions,
        "improvement_items": improvement_items,
    }


def build_caselab_review_feedback() -> dict[str, Any]:
    """Summarize CaseLab review status for Learning Hub."""
    entries = load_jsonl(FEEDBACK_LOG)
    if not entries:
        return {
            "schema_version": "caselab_review_feedback.v1",
            "generated_at": utc_now().isoformat(),
            "status": "no_entries",
        }

    by_status: dict[str, int] = {}
    for entry in entries:
        status = entry.get("review_status", "needs_review")
        by_status[status] = by_status.get(status, 0) + 1

    # Read calibration gate
    calib = load_json(CALIBRATION_GATE)
    calib_summary = None
    if calib:
        calib_summary = {
            "achieved_level": calib.get("achieved_level", "none"),
            "holdout_accuracy": None,
            "holdout_mae": None,
        }
        hm = calib.get("holdout_metrics", {})
        if isinstance(hm, dict):
            calib_summary["holdout_accuracy"] = hm.get("direction_accuracy")
            calib_summary["holdout_mae"] = hm.get("mean_absolute_error") or hm.get("mae")
        elif isinstance(hm, list):
            for metric in hm:
                if isinstance(metric, dict):
                    if metric.get("metric") == "direction_accuracy":
                        calib_summary["holdout_accuracy"] = metric.get("value")
                    elif metric.get("metric") in ("mae", "mean_absolute_error"):
                        calib_summary["holdout_mae"] = metric.get("value")

    return {
        "schema_version": "caselab_review_feedback.v1",
        "generated_at": utc_now().isoformat(),
        "status": "ok",
        "total_entries": len(entries),
        "by_status": by_status,
        "calibration_gate": calib_summary,
    }


def build_pipeline_alert_feedback() -> dict[str, Any]:
    """Read daily pipeline alerts and format for Learning Hub consumption."""
    alert = load_json(ALERT_PATH)
    if not alert:
        return {
            "schema_version": "pipeline_alert_feedback.v1",
            "generated_at": utc_now().isoformat(),
            "status": "no_alerts",
            "failed_steps": [],
            "warnings": [],
        }

    failed = []
    for entry in alert.get("failed_steps", []):
        if isinstance(entry, str):
            failed.append({"step": entry, "error": "", "duration_s": 0})
        else:
            failed.append({
                "step": entry.get("step", ""),
                "error": entry.get("error", "")[-300:],
                "duration_s": entry.get("duration_s", 0),
            })

    return {
        "schema_version": "pipeline_alert_feedback.v1",
        "generated_at": utc_now().isoformat(),
        "status": "ok",
        "severity": alert.get("severity", "UNKNOWN"),
        "run_date": alert.get("date", ""),
        "failed_steps": failed,
        "warnings": alert.get("warnings", []),
        "total_failed": len(failed),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    args = parser.parse_args()

    ensure_dir(OUTPUT_DIR)

    claim_feedback = build_claim_ladder_feedback()
    caselab_feedback = build_caselab_review_feedback()
    alert_feedback = build_pipeline_alert_feedback()

    # Read accuracy report summary (produced by judgment_accuracy_report.py)
    accuracy_report = load_json(ACCURACY_REPORT_PATH)
    accuracy_summary = {}
    if accuracy_report and accuracy_report.get("status") == "ok":
        accuracy_summary = {
            "total_evaluated": accuracy_report.get("summary", {}).get("total_evaluated", 0),
            "accuracy": accuracy_report.get("summary", {}).get("accuracy"),
            "avg_spy_return_pct": accuracy_report.get("summary", {}).get("avg_spy_return_pct"),
            "by_confidence": accuracy_report.get("by_confidence", {}),
        }

    claim_path = OUTPUT_DIR / "claim_ladder_feedback.json"
    caselab_path = OUTPUT_DIR / "caselab_review_feedback.json"
    alert_path = OUTPUT_DIR / "pipeline_alert_feedback.json"

    write_json(claim_path, claim_feedback)
    write_json(caselab_path, caselab_feedback)
    write_json(alert_path, alert_feedback)

    if args.json:
        print(json.dumps({
            "claim_ladder": claim_feedback,
            "caselab_review": caselab_feedback,
            "pipeline_alerts": alert_feedback,
            "judgment_accuracy": accuracy_summary,
        }, indent=2))
    else:
        print(f"Claim ladder feedback: {claim_path}")
        cl_summary = claim_feedback.get("summary", {})
        print(f"  Active claims: {cl_summary.get('active_claims', 0)}")
        print(f"  Highest tier: {cl_summary.get('highest_tier', 0)}")
        print(f"  Improvement items: {len(claim_feedback.get('improvement_items', []))}")

        print(f"CaseLab review feedback: {caselab_path}")
        for status, count in caselab_feedback.get("by_status", {}).items():
            print(f"  {status}: {count}")

        calib = caselab_feedback.get("calibration_gate", {})
        if calib:
            print(f"  Calibration: {calib.get('achieved_level', 'none')} (accuracy: {calib.get('holdout_accuracy', 'N/A')})")

        print(f"Pipeline alert feedback: {alert_path}")
        if alert_feedback.get("status") == "ok":
            print(f"  Severity: {alert_feedback.get('severity', 'N/A')}")
            print(f"  Failed steps: {alert_feedback.get('total_failed', 0)}")
            for fs in alert_feedback.get("failed_steps", []):
                print(f"    - {fs['step']}: {fs['error'][:80]}")
        else:
            print("  No alerts")

        if accuracy_summary:
            print(f"Judgment accuracy: {accuracy_summary.get('total_evaluated', 0)} evaluated")
            print(f"  Accuracy: {accuracy_summary.get('accuracy', 'N/A')}")
            print(f"  Avg SPY return: {accuracy_summary.get('avg_spy_return_pct', 'N/A')}%")


if __name__ == "__main__":
    main()
