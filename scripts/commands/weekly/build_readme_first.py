#!/usr/bin/env python3
"""Build 00_READ_ME_FIRST.md — from System Index.

This script reads from Data/system_index/latest.json to generate
a consistent README that reflects the true system state.

Usage:
    python3 scripts/commands/weekly/build_readme_first.py
    python3 scripts/commands/weekly/build_readme_first.py --json

Output:
    Output/current/00_READ_ME_FIRST.md
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from typing import Any

from scripts._runtime_io import ROOT, current_dir, ensure_dir, load_json

INDEX_PATH = ROOT / "Data" / "system_index" / "latest.json"
FRAMEWORK_OUTPUT_PATH = current_dir() / "framework_output.json"
EVIDENCE_REPORT_PATH = ROOT / "Output" / "current" / "evidence_grade_report.json"
OUTPUT_PATH = ROOT / "Output" / "current" / "00_READ_ME_FIRST.md"


def build_readme_from_index(
    index: dict[str, Any],
    framework_output: dict[str, Any] | None = None,
    evidence_report: dict[str, Any] | None = None,
) -> str:
    """Build README from System Index."""
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    date = index.get("generated_at", now)[:10]

    # Output source and quality from framework_output.json
    fw = framework_output or {}
    run_id = fw.get("run_id", "unknown")
    source = fw.get("source")
    quality_status = (fw.get("basic") or {}).get("quality_status", "N/A")
    if source == "structural_replay_v2" or run_id.startswith("replay_bridge"):
        output_source = f"structural_replay_v2 bridge ({run_id})"
    elif run_id.startswith("deformation"):
        output_source = f"deformation run ({run_id})"
    else:
        output_source = run_id

    # Extract key sections
    measurement = index.get("measurement_state", {})
    judgment = measurement.get("judgment", {}).get("summary", {})
    promotion_gate = measurement.get("promotion_gate", {}).get("summary", {})
    signals = measurement.get("signals", {})
    hmm = signals.get("hmm", {}).get("summary", {})
    k_gate = signals.get("k_gate", {}).get("summary", {})
    x_gate = signals.get("x_gate", {}).get("summary", {})

    trade_decision = index.get("trade_decision", {}).get("summary", {})
    risk_gate = index.get("risk_gate", {}).get("summary", {})

    paper = index.get("paper_world_model", {})
    horizon = index.get("horizon_events", {})
    prob_context = measurement.get("probabilistic_context", {})
    market_feedback = index.get("market_feedback", {}).get("latest", {})

    # Determine availability
    paper_available = paper.get("cases", {}).get("exists", False)
    horizon_available = horizon.get("events", {}).get("exists", False)
    prob_available = prob_context.get("exists", False) if isinstance(prob_context, dict) else False
    feedback_available = market_feedback.get("exists", False)

    # Freshness - FAIL must name the failing items, never a bare FAIL (WB-A3).
    freshness = index.get("freshness", {})
    freshness_verdict = freshness.get("verdict", "UNKNOWN")
    stale_artifacts = freshness.get("stale_artifacts", [])
    if freshness_verdict == "FAIL" and stale_artifacts:
        freshness_display = f"FAIL ({', '.join(stale_artifacts)})"
    else:
        freshness_display = freshness_verdict

    report = evidence_report or {}
    structural_grade = report.get("grade", trade_decision.get("evidence_grade", "N/A") if trade_decision else "N/A")
    trade_grade = report.get("trade_decision_grade", trade_decision.get("evidence_grade", "N/A") if trade_decision else "N/A")
    grade_match = report.get("grade_match")
    grade_note = ""
    if grade_match is False:
        grade_note = " (structural vs trade differ — see evidence_grade_report.json)"

    # Check if HMM regime is forbidden
    forbidden = promotion_gate.get("forbidden_language", [])
    hmm_regime = hmm.get("current_regime", "N/A")
    if hmm_regime.lower() in [f.lower() for f in forbidden]:
        hmm_display = "withheld (diagnostic-only)"
    else:
        hmm_display = f"{hmm_regime} (stability: {hmm.get('stability_grade', 'N/A')})"

    # Position intent - now derived from trade_decision.v3 in build_system_index
    # (stance x effective_size x velocity_gate_state). Single decision dialect.
    position = index.get("position", {}).get("summary", {})
    position_decision = position.get("decision", "N/A")
    position_action = position.get("portfolio_action", "N/A")
    position_mode = position.get("allowed_mode", "N/A")
    position_blockers = position.get("blockers", [])
    # Target weight comes from the derived effective_size (was hardcoded 0%).
    target_weight = position.get("target_weight")
    if target_weight is None:
        target_weight_str = "N/A"
    else:
        target_weight_str = f"{float(target_weight) * 100:.0f}%"

    # ── Plain Summary (WB-B1) ──────────────────────────────────────────────
    # Constitution (PRODUCT_FRAMEWORK_BOUNDARY.md): "Product tools must not
    # require framework concepts for basic use." The first screen must answer
    # three questions in plain language: what state / changed vs yesterday /
    # what would change the decision. Internal jargon stays in the advanced
    # sections below (System Status, Signal Gates, etc.).
    stance_value = trade_decision.get("decision", "WATCH")
    stress_direction = {
        "RISK_ON": "market structure pressure is low and the direction is relief",
        "RISK_OFF": "market structure pressure is elevated and the direction is stress",
        "WATCH": "market structure pressure is neutral; the system is watching",
    }.get(stance_value, "market structure pressure is in an unspecified state")

    hmm_regime_raw = hmm.get("current_regime", "unknown")
    regime_plain = {
        "compression": "compressed (low dispersion)",
        "expansion": "expanding (rising dispersion)",
        "transition": "in transition",
    }.get(hmm_regime_raw.lower(), hmm_regime_raw)

    # What would change the decision (invalidation conditions in plain words)
    invalidation_plain = []
    # Read invalidation from the trade_decision v3 file directly for plain mapping
    td_path = ROOT / "Output" / "trade_decision" / "latest.json"
    td_data = load_json(td_path) if td_path.exists() else {}
    for inv in td_data.get("invalidation", []):
        plain = {
            "Data freshness > 48h": "data falls more than 2 days behind",
            "Velocity gate EXIT": "market velocity triggers the automatic safety brake",
            "Promotion gate hard-blocks": "the system is hard-blocked from live use",
            "K/X gate verdict changes to FAIL": "a structural integrity check fails",
        }.get(inv)
        if plain:
            invalidation_plain.append(plain)
    if not invalidation_plain:
        invalidation_plain = ["the structural state changes materially"]

    lines = [
        f"# System Output - {date}",
        "",
        f"**Generated:** {now}",
        "",
        "---",
        "",
        "## Plain Summary",
        "",
        f"- **Today:** {stress_direction} (internal: {stance_value}, regime {regime_plain}).",
        f"- **Compared to yesterday:** see change analysis; judgment as-of {judgment.get('as_of', date)}.",
        f"- **What would change the decision:** {'; '.join(invalidation_plain)}.",
        "",
        "---",
        "",
        "## System Status",
        "",
        f"- **Output source:** {output_source}",
        f"- **Quality:** {quality_status}",
        f"- **Judgment:** {judgment.get('decision', 'N/A')}",
        f"- **Trade Decision:** {trade_decision.get('decision', 'N/A')}",
        f"- **Risk Gate:** {risk_gate.get('status', 'N/A')}",
        f"- **Promotion Gate:** {promotion_gate.get('overall_status', 'N/A')}",
        f"- **Freshness:** {freshness_display}",
        f"- **Structural evidence grade:** {structural_grade}",
        f"- **Trade evidence grade:** {trade_grade}{grade_note}",
        "",
        "## Position Translation",
        "",
        f"- **Decision:** {position_decision}",
        f"- **Portfolio Action:** {position_action}",
        f"- **Allowed Mode:** {position_mode}",
        f"- **Target Weight:** {target_weight_str}",
        f"- **Blockers:** {', '.join(position_blockers) if position_blockers else 'none'}",
        "",
        "## Data Sources",
        "",
        f"- **Paper World Model:** {'✅ available' if paper_available else '❌ missing'}",
        f"- **Horizon Events:** {'✅ available' if horizon_available else '❌ missing'}",
        f"- **Probabilistic Context:** {'✅ available' if prob_available else '❌ missing'}",
        f"- **Market Feedback:** {'✅ available' if feedback_available else '❌ missing'}",
        "",
        "## Signal Gates",
        "",
        f"- **HMM:** {hmm_display}",
        f"- **K Gate:** {k_gate.get('verdict', 'N/A')}",
        f"- **X Gate:** {x_gate.get('verdict', 'N/A')}",
        "",
        "## Execution Status",
        "",
        "- **Live execution:** ❌ not allowed",
        f"- **Paper trading:** {'✅ allowed' if risk_gate.get('status') == 'APPROVED_FOR_RESEARCH' else '❌ blocked'}",
        "- **Current status:** research-only",
        "",
        "---",
        "",
        "## What This System Can Say Today",
        "",
    ]

    # What system can say
    can_say = []
    cannot_say = []

    if judgment:
        can_say.append(f"Judgment decision: {judgment.get('decision', 'N/A')}")
        can_say.append(f"Confidence: {judgment.get('confidence', 'N/A')}")
        can_say.append(f"Claim ceiling: {judgment.get('claim_ceiling', 'N/A')}")

    if trade_decision:
        can_say.append(f"Trade decision: {trade_decision.get('decision', 'N/A')}")
        can_say.append(f"Trade evidence grade: {trade_grade}")
        if structural_grade != trade_grade:
            can_say.append(f"Structural evidence grade: {structural_grade}")

    if k_gate:
        cannot_say.append(f"K is {k_gate.get('current_role', 'diagnostic_rebuild')} — not a primary readout")

    if x_gate:
        cannot_say.append("X_agg is background-only — not a daily trigger")

    if promotion_gate.get("overall_status") == "BLOCKED":
        cannot_say.append("Strong claims blocked by promotion gate")

    for item in can_say:
        lines.append(f"- {item}")

    lines += [
        "",
        "## What This System Cannot Say Today",
        "",
    ]
    for item in cannot_say:
        lines.append(f"- {item}")

    # Forbidden language
    forbidden = promotion_gate.get("forbidden_language", [])
    if forbidden:
        lines += [
            "",
            "## Forbidden Language",
            "",
        ]
        for term in forbidden:
            lines.append(f"- ❌ {term}")

    lines += [
        "",
        "## Not a Trading Signal",
        "",
        "This system is a structural research tool. It does not:",
        "- Generate trading signals",
        "- Predict market direction",
        "- Recommend positions",
        "- Provide timing indicators",
        "",
        "All outputs are diagnostic observations for research purposes only.",
        "",
        "---",
        "",
        "*This document is auto-generated from System Index. It exists to prevent misreading of system outputs.*",
    ]

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build 00_READ_ME_FIRST.md from System Index.")
    parser.add_argument("--json", action="store_true", help="Print index context as JSON.")
    args = parser.parse_args()

    index = load_json(INDEX_PATH)
    if not index:
        print("No System Index found. Run: python3 scripts/build_system_index.py")
        return

    framework_output = load_json(FRAMEWORK_OUTPUT_PATH)
    evidence_report = load_json(EVIDENCE_REPORT_PATH)

    if args.json:
        print(json.dumps(index, indent=2, ensure_ascii=False))
    else:
        md = build_readme_from_index(index, framework_output, evidence_report)
        ensure_dir(OUTPUT_PATH.parent)
        OUTPUT_PATH.write_text(md, encoding="utf-8")
        print(f"Wrote: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
