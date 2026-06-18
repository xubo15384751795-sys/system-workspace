#!/usr/bin/env python3
"""Learning Hub Trade Decision Calibration — absorb trade decision quality.

This script reads trade decision calibration data and generates
events for Learning Hub to track decision quality over time.

Usage:
    python3 scripts/learning_hub_trade_calibration.py
    python3 scripts/learning_hub_trade_calibration.py --json

Output:
    Output/system_learning/events/trade_decision_calibration_YYYY-MM-DD.jsonl
    Output/system_learning/latest/trade_decision_calibration_summary.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
from _runtime_io import ensure_dir, load_json, load_jsonl, utc_now, write_json

TRADE_LEDGER_PATH = ROOT / "Output" / "trade_ledger" / "decisions.jsonl"
CALIBRATION_REPORT_PATH = ROOT / "Output" / "trade_ledger" / "calibration_report.json"
RISK_GATE_PATH = ROOT / "Output" / "trade_decision" / "risk_gate.json"
EVENTS_DIR = ROOT / "Output" / "system_learning" / "events"


def build_calibration_event(
    entry: dict[str, Any],
    calibration: dict[str, Any] | None,
    risk_gate: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build a single trade decision calibration event."""
    date = entry.get("date", utc_now().strftime("%Y-%m-%d"))

    # Find matching calibration evaluation
    outcomes = {}
    evaluated_horizons = []
    if calibration:
        evaluations = calibration.get("evaluations", [])
        for eval_item in evaluations:
            if eval_item.get("date") == date:
                outcomes = eval_item.get("outcomes", {})
                evaluated_horizons = eval_item.get("evaluated_horizons", [])
                break

    # Get risk gate status
    risk_gate_status = "UNKNOWN"
    if risk_gate:
        risk_gate_status = risk_gate.get("risk_check", {}).get("status", "UNKNOWN")

    return {
        "event_type": "trade_decision_calibration",
        "schema_version": "trade_decision_calibration_event.v1",
        "generated_at": utc_now().isoformat(),
        "decision_date": date,
        "decision": entry.get("decision", "NO_TRADE"),
        "confidence": entry.get("confidence", "low"),
        "evidence_grade": entry.get("evidence_grade", "D"),
        "risk_gate_status": risk_gate_status,
        "evaluated_horizons": evaluated_horizons,
        "outcomes": outcomes,
        "paper_sources": entry.get("paper_sources", []),
        "system_sources": entry.get("system_sources", []),
        "trade_thesis": entry.get("trade_thesis", {}),
    }


def build_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Build summary statistics from events."""
    evaluated = [e for e in events if e.get("evaluated_horizons")]
    skipped = [e for e in events if not e.get("evaluated_horizons")]

    by_decision: dict[str, int] = {}
    by_confidence: dict[str, int] = {}
    by_evidence_grade: dict[str, int] = {}

    for event in events:
        decision = event.get("decision", "UNKNOWN")
        by_decision[decision] = by_decision.get(decision, 0) + 1

        confidence = event.get("confidence", "unknown")
        by_confidence[confidence] = by_confidence.get(confidence, 0) + 1

        grade = event.get("evidence_grade", "D")
        by_evidence_grade[grade] = by_evidence_grade.get(grade, 0) + 1

    return {
        "total_events": len(events),
        "evaluated_events": len(evaluated),
        "skipped_events": len(skipped),
        "by_decision": by_decision,
        "by_confidence": by_confidence,
        "by_evidence_grade": by_evidence_grade,
    }


def build_learning_hub_summary(
    events: list[dict[str, Any]],
    calibration: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build summary for Learning Hub ingestion."""
    summary = build_summary(events)

    # Add calibration data
    if calibration:
        cal_summary = calibration.get("summary", {})
        summary["calibration_sample_size"] = cal_summary.get("evaluated_decisions", 0)
        summary["avg_spy_1w_return"] = cal_summary.get("avg_spy_1w_return_pct")

    # Analyze paper sources
    paper_source_counts: dict[str, int] = {}
    for event in events:
        for source in event.get("paper_sources", []):
            content_type = source.get("content_type", "unknown")
            paper_source_counts[content_type] = paper_source_counts.get(content_type, 0) + 1
    summary["paper_source_counts"] = paper_source_counts

    # Analyze system sources
    system_source_counts: dict[str, int] = {}
    for event in events:
        for source in event.get("system_sources", []):
            source_type = source.get("source_type", "unknown")
            system_source_counts[source_type] = system_source_counts.get(source_type, 0) + 1
    summary["system_source_counts"] = system_source_counts

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate trade decision calibration events.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    parser.add_argument("--date", default=None, help="Override date for output file.")
    args = parser.parse_args()

    # Load data
    entries = load_jsonl(TRADE_LEDGER_PATH)
    calibration = load_json(CALIBRATION_REPORT_PATH)
    risk_gate = load_json(RISK_GATE_PATH)

    if not entries:
        print("No trade decisions in ledger.")
        return

    # Build events
    events = [build_calibration_event(entry, calibration, risk_gate) for entry in entries]

    # Write events
    date_str = args.date or utc_now().strftime("%Y-%m-%d")
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = EVENTS_DIR / f"trade_decision_calibration_{date_str}.jsonl"

    with output_path.open("w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    # Build summary
    summary = build_summary(events)

    # Build Learning Hub summary
    hub_summary = build_learning_hub_summary(events, calibration)

    # Write Learning Hub summary
    hub_latest_dir = ROOT / "Output" / "system_learning" / "latest"
    ensure_dir(hub_latest_dir)
    write_json(hub_latest_dir / "trade_decision_calibration_summary.json", hub_summary)

    if args.json:
        print(json.dumps({"events": events, "summary": summary, "hub_summary": hub_summary}, indent=2, ensure_ascii=False))
    else:
        print(f"Trade decision calibration events: {output_path}")
        print(f"Total events: {summary['total_events']}")
        print(f"Evaluated: {summary['evaluated_events']}, Skipped: {summary['skipped_events']}")
        print(f"By decision: {summary['by_decision']}")
        print(f"By confidence: {summary['by_confidence']}")
        print(f"By evidence grade: {summary['by_evidence_grade']}")


if __name__ == "__main__":
    main()
