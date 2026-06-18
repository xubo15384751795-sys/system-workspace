#!/usr/bin/env python3
"""Learning Hub Comprehensive Summary — all calibration data.

This script generates a comprehensive Learning Hub summary that includes:
- Judgment calibration
- Trade decision calibration
- Paper mechanism performance
- Horizon event usefulness
- GluonTS forecast reliability
- Qlib incremental feedback
- Recurring failed assumptions

Usage:
    python3 scripts/learning_hub_comprehensive_summary.py
    python3 scripts/learning_hub_comprehensive_summary.py --json

Output:
    Output/system_learning/latest/comprehensive_summary.json
    Output/system_learning/latest/comprehensive_summary.md
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
from _runtime_io import ensure_dir, load_json, load_jsonl, utc_now, write_json

JUDGMENT_CALIBRATION_PATH = ROOT / "Output" / "system_learning" / "latest" / "judgment_calibration_summary.json"
TRADE_CALIBRATION_PATH = ROOT / "Output" / "system_learning" / "latest" / "trade_decision_calibration_summary.json"
TRADE_LEDGER_PATH = ROOT / "Output" / "trade_ledger" / "decisions.jsonl"
CALIBRATION_REPORT_PATH = ROOT / "Output" / "trade_ledger" / "calibration_report.json"
MARKET_FEEDBACK_PATH = ROOT / "Output" / "market_feedback" / "feedback_decision.json"
CLAIM_EVALUATION_PATH = ROOT / "Output" / "system_learning" / "latest" / "claim_evaluation.json"
CLAIM_PROGRESSION_PATH = ROOT / "Output" / "claim_ladder" / "progression.json"
HORIZON_EVENTS_PATH = ROOT / "Data" / "horizon_events" / "daily_digest.json"
PROBABILISTIC_CONTEXT_PATH = ROOT / "Output" / "probabilistic_context" / "latest.json"
OUTPUT_DIR = ROOT / "Output" / "system_learning" / "latest"


def build_comprehensive_summary() -> dict[str, Any]:
    """Build comprehensive Learning Hub summary."""
    now = utc_now()

    # Load all data sources
    judgment_calibration = load_json(JUDGMENT_CALIBRATION_PATH)
    trade_calibration = load_json(TRADE_CALIBRATION_PATH)
    trade_ledger = load_jsonl(TRADE_LEDGER_PATH)
    calibration_report = load_json(CALIBRATION_REPORT_PATH)
    market_feedback = load_json(MARKET_FEEDBACK_PATH)
    horizon_digest = load_json(HORIZON_EVENTS_PATH)
    probabilistic_context = load_json(PROBABILISTIC_CONTEXT_PATH)

    # Judgment Calibration
    judgment_summary = {
        "total_cards": judgment_calibration.get("total_events", 0) if judgment_calibration else 0,
        "evaluated_cards": judgment_calibration.get("evaluated_events", 0) if judgment_calibration else 0,
        "by_confidence": judgment_calibration.get("by_confidence", {}) if judgment_calibration else {},
        "blocked_promotions": judgment_calibration.get("blocked_promotions", 0) if judgment_calibration else 0,
    }

    # Trade Decision Calibration
    trade_summary = {
        "total_decisions": trade_calibration.get("total_events", 0) if trade_calibration else 0,
        "evaluated_decisions": trade_calibration.get("evaluated_events", 0) if trade_calibration else 0,
        "by_decision": trade_calibration.get("by_decision", {}) if trade_calibration else {},
        "by_evidence_grade": trade_calibration.get("by_evidence_grade", {}) if trade_calibration else {},
    }

    # Paper Mechanism Performance
    paper_mechanism_summary = {
        "total_mechanisms_used": 0,
        "mechanism_hit_rate": None,
        "best_mechanisms": [],
        "weak_mechanisms": [],
    }

    # Analyze trade ledger for mechanism performance
    if trade_ledger:
        mechanism_counts: dict[str, int] = {}
        for entry in trade_ledger:
            for source in entry.get("paper_sources", []):
                mechanism_id = source.get("content_id", "unknown")
                mechanism_counts[mechanism_id] = mechanism_counts.get(mechanism_id, 0) + 1

        paper_mechanism_summary["total_mechanisms_used"] = len(mechanism_counts)
        if mechanism_counts:
            sorted_mechanisms = sorted(mechanism_counts.items(), key=lambda x: x[1], reverse=True)
            paper_mechanism_summary["best_mechanisms"] = [m[0] for m in sorted_mechanisms[:3]]

    # Horizon Event Usefulness
    horizon_summary = {
        "total_events": horizon_digest.get("total_events", 0) if horizon_digest else 0,
        "mechanism_matches": horizon_digest.get("total_matches", 0) if horizon_digest else 0,
        "top_mechanisms": list((horizon_digest.get("mechanism_matches", {}) if horizon_digest else {}).keys())[:3],
    }

    # GluonTS Forecast Reliability
    gluonts_summary = {
        "overall_risk_level": probabilistic_context.get("summary", {}).get("overall_risk_level") if probabilistic_context else None,
        "tail_risk_detected": probabilistic_context.get("summary", {}).get("tail_risk_detected") if probabilistic_context else False,
        "model_confidence": probabilistic_context.get("summary", {}).get("model_confidence") if probabilistic_context else None,
        "forecasts_count": len(probabilistic_context.get("forecasts", [])) if probabilistic_context else 0,
    }

    # Qlib Incremental Feedback
    qlib_summary = {
        "incremental_explanation_power": market_feedback.get("summary", {}).get("incremental_explanation_power") if market_feedback else None,
        "mechanism_usefulness_score": market_feedback.get("summary", {}).get("mechanism_usefulness_score") if market_feedback else None,
        "feature_promotion_candidates": market_feedback.get("summary", {}).get("feature_promotion_candidates", []) if market_feedback else [],
    }

    # Claim Evaluation — forward-looking claim verification
    claim_evaluation = load_json(CLAIM_EVALUATION_PATH)
    claim_summary = {
        "total_evaluations": claim_evaluation.get("summary", {}).get("total_evaluations", 0) if claim_evaluation else 0,
        "confirmed": claim_evaluation.get("summary", {}).get("confirmed", 0) if claim_evaluation else 0,
        "contradicted": claim_evaluation.get("summary", {}).get("contradicted", 0) if claim_evaluation else 0,
        "invalidated": claim_evaluation.get("summary", {}).get("invalidated", 0) if claim_evaluation else 0,
        "tracking": claim_evaluation.get("summary", {}).get("tracking", 0) if claim_evaluation else 0,
        "mechanism_scores": claim_evaluation.get("mechanism_scores", {}) if claim_evaluation else {},
        "module_contributions": claim_evaluation.get("module_contributions", {}) if claim_evaluation else {},
    }

    # Claim Ladder Progression — cross-run tier tracking
    progression = load_json(CLAIM_PROGRESSION_PATH)
    progression_summary = {
        "status": progression.get("status", "not_available") if progression else "not_available",
        "previous_run": progression.get("previous_run") if progression else None,
        "total_claims": len(progression.get("claims", [])) if progression else 0,
        "claims": progression.get("claims", []) if progression else [],
    }

    # Recurring Failed Assumptions
    failed_assumptions = []
    if calibration_report:
        evaluations = calibration_report.get("evaluations", [])
        for eval_item in evaluations:
            if eval_item.get("status") == "evaluated":
                # Check if decision was wrong
                spy_1w = ((eval_item.get("outcomes", {}).get("1w", {}).get("metrics", {}).get("SPY", {}) or {}).get("return_pct"))
                if spy_1w is not None and eval_item.get("decision") in ("TACTICAL_LONG", "HEDGE"):
                    if spy_1w < -1.0:
                        failed_assumptions.append({
                            "date": eval_item.get("date"),
                            "decision": eval_item.get("decision"),
                            "outcome": f"SPY 1w: {spy_1w:.2f}%",
                            "lesson": "Active decision failed - review mechanism",
                        })

    # Next Evidence Needed
    next_evidence = []
    if judgment_calibration:
        next_evidence.extend(judgment_calibration.get("next_required_evidence", []))

    return {
        "schema_version": "learning_hub_comprehensive_summary.v1",
        "generated_at": now.isoformat(),
        "judgment_calibration": judgment_summary,
        "trade_decision_calibration": trade_summary,
        "paper_mechanism_performance": paper_mechanism_summary,
        "horizon_event_usefulness": horizon_summary,
        "gluonts_forecast_reliability": gluonts_summary,
        "qlib_incremental_feedback": qlib_summary,
        "claim_evaluation": claim_summary,
        "claim_ladder_progression": progression_summary,
        "recurring_failed_assumptions": failed_assumptions[:5],
        "next_evidence_needed": list(set(next_evidence)),
    }


def format_markdown(summary: dict[str, Any]) -> str:
    """Format comprehensive summary as markdown."""
    lines = [
        "# Learning Hub Comprehensive Summary",
        "",
        f"**Generated:** {summary['generated_at']}",
        "",
        "---",
        "",
        "## Judgment Calibration",
        "",
    ]

    jc = summary["judgment_calibration"]
    lines.extend([
        f"- Total cards: {jc['total_cards']}",
        f"- Evaluated: {jc['evaluated_cards']}",
        f"- Blocked promotions: {jc['blocked_promotions']}",
        f"- By confidence: {jc['by_confidence']}",
        "",
    ])

    lines.append("## Trade Decision Calibration")
    lines.append("")

    tc = summary["trade_decision_calibration"]
    lines.extend([
        f"- Total decisions: {tc['total_decisions']}",
        f"- Evaluated: {tc['evaluated_decisions']}",
        f"- By decision: {tc['by_decision']}",
        f"- By evidence grade: {tc['by_evidence_grade']}",
        "",
    ])

    lines.append("## Paper Mechanism Performance")
    lines.append("")

    pm = summary["paper_mechanism_performance"]
    lines.extend([
        f"- Total mechanisms used: {pm['total_mechanisms_used']}",
        f"- Mechanism hit rate: {pm['mechanism_hit_rate']}",
        f"- Best mechanisms: {', '.join(pm['best_mechanisms']) if pm['best_mechanisms'] else 'N/A'}",
        "",
    ])

    lines.append("## Horizon Event Usefulness")
    lines.append("")

    he = summary["horizon_event_usefulness"]
    lines.extend([
        f"- Total events: {he['total_events']}",
        f"- Mechanism matches: {he['mechanism_matches']}",
        f"- Top mechanisms: {', '.join(he['top_mechanisms']) if he['top_mechanisms'] else 'N/A'}",
        "",
    ])

    lines.append("## GluonTS Forecast Reliability")
    lines.append("")

    gt = summary["gluonts_forecast_reliability"]
    lines.extend([
        f"- Overall risk level: {gt['overall_risk_level']}",
        f"- Tail risk detected: {gt['tail_risk_detected']}",
        f"- Model confidence: {gt['model_confidence']}",
        f"- Forecasts: {gt['forecasts_count']}",
        "",
    ])

    lines.append("## Qlib Incremental Feedback")
    lines.append("")

    ql = summary["qlib_incremental_feedback"]
    lines.extend([
        f"- Incremental explanation power: {ql['incremental_explanation_power']}",
        f"- Mechanism usefulness score: {ql['mechanism_usefulness_score']}",
        f"- Feature promotion candidates: {', '.join(ql['feature_promotion_candidates']) if ql['feature_promotion_candidates'] else 'N/A'}",
        "",
    ])

    lines.append("## Claim Evaluation")
    lines.append("")

    ce = summary.get("claim_evaluation", {})
    lines.extend([
        f"- Total evaluations: {ce.get('total_evaluations', 0)}",
        f"- Confirmed: {ce.get('confirmed', 0)}",
        f"- Contradicted: {ce.get('contradicted', 0)}",
        f"- Invalidated: {ce.get('invalidated', 0)}",
        f"- Tracking: {ce.get('tracking', 0)}",
        "",
    ])

    mc = ce.get("module_contributions", {})
    if mc:
        lines.append("### Module Contributions")
        lines.append("")
        for mod, stats in mc.items():
            lines.append(f"- **{mod}**: {stats.get('usefulness', 'unknown')}")
        lines.append("")

    lines.append("## Claim Ladder Progression")
    lines.append("")

    prog = summary.get("claim_ladder_progression", {})
    lines.extend([
        f"- Status: {prog.get('status', 'not_available')}",
        f"- Total tracked claims: {prog.get('total_claims', 0)}",
        "",
    ])
    for claim in prog.get("claims", []):
        tier = claim.get("tier", "?")
        label = claim.get("label", "?")
        status = claim.get("progression_status", "?")
        lines.append(f"- **Tier {tier}** ({label}): {status}")
    if not prog.get("claims"):
        lines.append("- No claims being tracked yet")
    lines.append("")

    lines.append("## Recurring Failed Assumptions")
    lines.append("")

    if summary["recurring_failed_assumptions"]:
        for fa in summary["recurring_failed_assumptions"]:
            lines.append(f"- [{fa['date']}] {fa['decision']}: {fa['outcome']} — {fa['lesson']}")
    else:
        lines.append("- None recorded yet")

    lines.extend([
        "",
        "## Next Evidence Needed",
        "",
    ])

    if summary["next_evidence_needed"]:
        for evidence in summary["next_evidence_needed"]:
            lines.append(f"- {evidence}")
    else:
        lines.append("- None specified")

    lines.extend([
        "",
        "---",
        "",
        "*This summary aggregates all calibration data for Learning Hub.*",
    ])

    return "\n".join(lines) + "\n"


def write_outputs(summary: dict[str, Any]) -> dict[str, Path]:
    """Write comprehensive summary outputs."""
    ensure_dir(OUTPUT_DIR)

    json_path = OUTPUT_DIR / "comprehensive_summary.json"
    md_path = OUTPUT_DIR / "comprehensive_summary.md"

    write_json(json_path, summary)
    md_path.write_text(format_markdown(summary), encoding="utf-8")

    return {"json": json_path, "markdown": md_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate comprehensive Learning Hub summary.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    args = parser.parse_args()

    summary = build_comprehensive_summary()
    paths = write_outputs(summary)

    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print(f"Comprehensive summary: {paths['markdown']}")
        print(f"Judgment calibration: {summary['judgment_calibration']['total_cards']} cards")
        print(f"Trade decisions: {summary['trade_decision_calibration']['total_decisions']} decisions")
        print(f"Paper mechanisms: {summary['paper_mechanism_performance']['total_mechanisms_used']} used")
        print(f"Horizon events: {summary['horizon_event_usefulness']['total_events']} events")


if __name__ == "__main__":
    main()
