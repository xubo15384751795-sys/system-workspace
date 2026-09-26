#!/usr/bin/env python3
"""Learning Hub Judgment Calibration Event Writer.

Reads judgment cards and calibration report, generates JSONL events
for Learning Hub to track judgment quality over time.

Usage:
    python3 scripts/learning_hub_judgment_calibration.py
    python3 scripts/learning_hub_judgment_calibration.py --json

Output:
    Output/system_learning/events/judgment_calibration_YYYY-MM-DD.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from verity.runtime.runtime_io import ROOT, ensure_dir, load_json, utc_now, write_json

JUDGMENT_DIR = ROOT / "Output" / "judgment"
CALIBRATION_PATH = JUDGMENT_DIR / "calibration_report.json"
PROMOTION_GATE_PATH = JUDGMENT_DIR / "promotion_gate.json"
EVENTS_DIR = ROOT / "Output" / "system_learning" / "events"


def load_judgment_cards() -> list[dict[str, Any]]:
    """Load all dated judgment cards."""
    cards = []
    for card_path in sorted(JUDGMENT_DIR.glob("*.json")):
        if card_path.name == "latest.json" or not re.match(r"\d{4}-\d{2}-\d{2}\.json$", card_path.name):
            continue
        payload = load_json(card_path)
        if payload:
            cards.append(payload)
    return cards


def build_calibration_event(
    card: dict[str, Any],
    calibration: dict[str, Any] | None,
    promotion_gate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a single judgment calibration event."""
    as_of = str(card.get("as_of", ""))[:10]
    decision = card.get("decision", "UNKNOWN")
    confidence = (card.get("confidence") or {}).get("level", "unknown")
    claim_ceiling = card.get("claim_ceiling", "unknown")
    gate_status = card.get("gate_status", {})

    # Promotion gate verdict
    promotion_verdict = "NOT_AVAILABLE"
    if promotion_gate:
        promotion_verdict = promotion_gate.get("overall_status", "UNKNOWN")

    # Find matching calibration evaluation
    outcomes = {}
    evaluated_horizons = []
    skipped_reason = None

    if calibration:
        evaluations = calibration.get("evaluations", [])
        for eval_item in evaluations:
            if eval_item.get("as_of") == as_of:
                outcomes = eval_item.get("outcomes", {})
                evaluated_horizons = eval_item.get("evaluated_horizons", [])
                if eval_item.get("status") != "evaluated":
                    skipped_reason = eval_item.get("status", "unknown")
                break

    # Risk flags from judgment card
    risk_flags = card.get("risk", [])

    # Invalidation conditions
    invalidation = card.get("invalidation", [])

    # Determine invalidation status
    invalidation_status = "not_triggered"
    if any("downgrade" in str(inv).lower() for inv in invalidation):
        invalidation_status = "condition_present"

    # Determine calibration status
    calibration_status = "insufficient_sample"
    if calibration:
        summary = calibration.get("summary", {})
        if summary.get("evaluated_cards", 0) >= 10:
            calibration_status = "adequate_sample"
        elif summary.get("evaluated_cards", 0) >= 5:
            calibration_status = "limited_sample"

    return {
        "event_type": "judgment_calibration",
        "schema_version": "system.judgment_calibration_event.v2",
        "generated_at": utc_now().isoformat(),
        "judgment_date": as_of,
        "decision": decision,
        "confidence": confidence,
        "claim_ceiling": claim_ceiling,
        "promotion_gate_verdict": promotion_verdict,
        "gate_status": gate_status,
        "evaluated_horizons": evaluated_horizons,
        "outcomes": outcomes,
        "skipped_reason": skipped_reason,
        "risk_flags": risk_flags,
        "invalidation_conditions": invalidation,
        "invalidation_status": invalidation_status,
        "calibration_status": calibration_status,
    }


def write_events(events: list[dict[str, Any]], date_str: str) -> Path:
    """Write events to JSONL file."""
    ensure_dir(EVENTS_DIR)
    output_path = EVENTS_DIR / f"judgment_calibration_{date_str}.jsonl"

    with output_path.open("w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    return output_path


def build_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Build summary statistics from events."""
    evaluated = [e for e in events if not e.get("skipped_reason")]
    skipped = [e for e in events if e.get("skipped_reason")]

    by_decision: dict[str, int] = {}
    by_confidence: dict[str, int] = {}
    recurring_risks: dict[str, int] = {}
    blocked_promotions = 0
    by_promotion_verdict: dict[str, int] = {}

    for event in evaluated:
        decision = event.get("decision", "UNKNOWN")
        by_decision[decision] = by_decision.get(decision, 0) + 1

        confidence = event.get("confidence", "unknown")
        by_confidence[confidence] = by_confidence.get(confidence, 0) + 1

        for risk in event.get("risk_flags", []):
            recurring_risks[risk] = recurring_risks.get(risk, 0) + 1

        # Track promotion gate verdicts
        promo_verdict = event.get("promotion_gate_verdict", "NOT_AVAILABLE")
        by_promotion_verdict[promo_verdict] = by_promotion_verdict.get(promo_verdict, 0) + 1
        if promo_verdict == "BLOCKED":
            blocked_promotions += 1

    return {
        "total_events": len(events),
        "evaluated_cards": len(evaluated),
        "skipped_cards": len(skipped),
        "by_decision": by_decision,
        "by_confidence": by_confidence,
        "recurring_risk_flags": recurring_risks,
        "blocked_promotions": blocked_promotions,
        "by_promotion_verdict": by_promotion_verdict,
    }


def build_learning_hub_summary(
    events: list[dict[str, Any]],
    calibration: dict[str, Any] | None,
    promotion_gate: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build a summary for Learning Hub ingestion."""
    summary = build_summary(events)

    # Add calibration data
    if calibration:
        cal_summary = calibration.get("summary", {})
        summary["calibration_sample_size"] = cal_summary.get("evaluated_cards", 0)
        summary["confidence_calibration"] = cal_summary.get("confidence_calibration", {})
        summary["decision_outcomes"] = cal_summary.get("decision_outcomes", {})

    # Add promotion gate data
    if promotion_gate:
        summary["current_promotion_gate"] = {
            "status": promotion_gate.get("overall_status"),
            "blocked_gates": promotion_gate.get("blocked_gates", []),
            "blocking_reasons": promotion_gate.get("blocking_reasons", []),
            "claim_ceiling": promotion_gate.get("claim_ceiling"),
        }

    # Determine next required evidence
    next_evidence = []
    if promotion_gate and promotion_gate.get("overall_status") == "BLOCKED":
        for reason in promotion_gate.get("blocking_reasons", []):
            if "confidence" in reason.lower():
                next_evidence.append("improve_measurement_quality")
            if "caselab" in reason.lower():
                next_evidence.append("wait_for_better_analogy")
            if "hmm" in reason.lower():
                next_evidence.append("resolve_hmm_conflict")
            if "k gate" in reason.lower():
                next_evidence.append("pass_k_measurement_gate")
            if "x" in reason.lower():
                next_evidence.append("pass_x_measurement_gate")
    summary["next_required_evidence"] = list(set(next_evidence))

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Learning Hub judgment calibration events.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    parser.add_argument("--date", default=None, help="Override date for output file.")
    args = parser.parse_args()

    # Load data
    cards = load_judgment_cards()
    calibration = load_json(CALIBRATION_PATH)
    promotion_gate = load_json(PROMOTION_GATE_PATH)

    if not cards:
        print("No judgment cards found.")
        return

    # Build events
    events = [build_calibration_event(card, calibration, promotion_gate) for card in cards]

    # Write events
    date_str = args.date or utc_now().strftime("%Y-%m-%d")
    output_path = write_events(events, date_str)

    # Build summary
    summary = build_summary(events)

    # Build Learning Hub summary
    hub_summary = build_learning_hub_summary(events, calibration, promotion_gate)

    # Write Learning Hub summary
    hub_summary_path = EVENTS_DIR / f"judgment_calibration_summary_{date_str}.json"
    write_json(hub_summary_path, hub_summary)

    # Also write to Learning Hub latest
    hub_latest_dir = ROOT / "Output" / "system_learning" / "latest"
    ensure_dir(hub_latest_dir)
    write_json(hub_latest_dir / "judgment_calibration_summary.json", hub_summary)

    if args.json:
        print(json.dumps({"events": events, "summary": summary, "hub_summary": hub_summary}, indent=2, ensure_ascii=False))
    else:
        print(f"Judgment calibration events: {output_path}")
        print(f"Total events: {summary['total_events']}")
        print(f"Evaluated: {summary['evaluated_cards']}, Skipped: {summary['skipped_cards']}")
        print(f"By decision: {summary['by_decision']}")
        print(f"By confidence: {summary['by_confidence']}")
        print(f"Blocked promotions: {summary['blocked_promotions']}")
        print(f"Next required evidence: {hub_summary.get('next_required_evidence', [])}")


if __name__ == "__main__":
    main()
