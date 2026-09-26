#!/usr/bin/env python3
"""List latest system state — reads from unified index.

This script reads from Data/system_index/latest.json instead of
scanning directories independently.

Usage:
    python3 scripts/list_latest.py
    python3 scripts/list_latest.py --json
    python3 scripts/list_latest.py --section judgment

Output:
    Prints current system state to stdout.
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

from verity.runtime.runtime_io import ROOT

INDEX_PATH = ROOT / "Data" / "system_index" / "latest.json"


def load_index() -> dict | None:
    """Load system index."""
    if not INDEX_PATH.exists():
        return None
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="List latest system state.")
    parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    parser.add_argument("--section", default=None, help="Print specific section.")
    args = parser.parse_args()

    index = load_index()
    if not index:
        print("No system index found. Run: python3 scripts/build_system_index.py")
        return

    if args.json:
        if args.section:
            section = index.get(args.section, {})
            print(json.dumps(section, indent=2, ensure_ascii=False))
        else:
            print(json.dumps(index, indent=2, ensure_ascii=False))
        return

    # Pretty print
    print(f"System Index — {index.get('generated_at', 'unknown')}")
    print("=" * 60)

    # Harvester
    harvester = index.get("harvester", {})
    if harvester.get("exists"):
        print("\n📦 HARVESTER")
        print(f"  Status: ✅ ({harvester.get('modified', 'N/A')[:10]})")

    # Paper World Model
    paper = index.get("paper_world_model", {})
    paper_cases = paper.get("cases", {})
    if paper_cases.get("exists"):
        print("\n📚 PAPER WORLD MODEL")
        manifest = paper.get("manifest") or {}
        if manifest.get("synced_at"):
            print(f"  Synced: {manifest['synced_at'][:19]}")
        counts = manifest.get("record_counts") or {}
        if counts:
            print(
                f"  Records: cases={counts.get('cases', '?')} "
                f"mechanisms={counts.get('mechanisms', '?')}"
            )
        print("  Cases: ✅")
        print(f"  Mechanisms: {'✅' if paper.get('mechanisms', {}).get('exists') else '❌'}")
        print(f"  Variables: {'✅' if paper.get('variables', {}).get('exists') else '❌'}")
        print(f"  Indicators: {'✅' if paper.get('indicators', {}).get('exists') else '❌'}")
        print(f"  Trade Ideas: {'✅' if paper.get('trade_ideas', {}).get('exists') else '❌'}")

    # Horizon Events
    horizon = index.get("horizon_events", {})
    if horizon.get("events", {}).get("exists"):
        print("\n🌐 HORIZON EVENTS")
        print("  Events: ✅")
        print(f"  Mechanism Matches: {'✅' if horizon.get('mechanism_matches', {}).get('exists') else '❌'}")

    # Measurement State
    measurement = index.get("measurement_state", {})

    # Judgment
    judgment = measurement.get("judgment", {}).get("summary")
    if judgment:
        print("\n📊 JUDGMENT")
        print(f"  Decision: {judgment.get('decision', 'N/A')}")
        print(f"  Confidence: {judgment.get('confidence', 'N/A')}")
        print(f"  Claim ceiling: {judgment.get('claim_ceiling', 'N/A')}")

    # Promotion gate
    gate = measurement.get("promotion_gate", {}).get("summary")
    if gate:
        print("\n🚧 PROMOTION GATE")
        print(f"  Status: {gate.get('overall_status', 'N/A')}")
        blocked = gate.get("blocked_gates", [])
        if blocked:
            print(f"  Blocked by: {', '.join(blocked)}")

    # Signals
    signals = measurement.get("signals", {})
    hmm = signals.get("hmm", {}).get("summary")
    if hmm:
        print("\n📈 HMM")
        print(f"  Regime: {hmm.get('current_regime', 'N/A')}")
        print(f"  Stability: {hmm.get('stability_grade', 'N/A')}")

    k = signals.get("k_gate", {}).get("summary")
    if k:
        print("\n📐 K GATE")
        print(f"  Verdict: {k.get('verdict', 'N/A')}")
        print(f"  Role: {k.get('current_role', 'N/A')}")

    x = signals.get("x_gate", {}).get("summary")
    if x:
        print("\n📏 X GATE")
        print(f"  Verdict: {x.get('verdict', 'N/A')}")
        print(f"  Background: {x.get('background_allowed', 'N/A')}")

    # Trade Decision
    trade = index.get("trade_decision", {}).get("summary")
    if trade:
        print("\n💼 TRADE DECISION")
        print(f"  Decision: {trade.get('decision', 'N/A')}")
        print(f"  Confidence: {trade.get('confidence', 'N/A')}")
        print(f"  Evidence Grade: {trade.get('evidence_grade', 'N/A')}")

    # Risk Gate
    risk = index.get("risk_gate", {}).get("summary")
    if risk:
        print("\n🛡️ RISK GATE")
        print(f"  Status: {risk.get('status', 'N/A')}")
        print(f"  Risk Level: {risk.get('risk_level', 'N/A')}")

    # Probabilistic Context
    prob = measurement.get("probabilistic_context", {})
    if prob.get("exists"):
        print("\n🎲 PROBABILISTIC CONTEXT")
        print("  GluonTS: ✅")

    # Market Feedback
    feedback = index.get("market_feedback", {}).get("latest", {})
    if feedback.get("exists"):
        # Read feedback to get source
        feedback_data = None
        try:
            feedback_path = feedback.get("path")
            if feedback_path:
                feedback_data = json.loads(Path(feedback_path).read_text())
        except Exception:
            logger.debug("Failed to read feedback at %s", feedback_path, exc_info=True)

        source = feedback_data.get("source", "unknown") if feedback_data else "unknown"
        print("\n📉 MARKET FEEDBACK")
        print(f"  Source: {source}")
        if source == "sample":
            print("  ⚠️ SAMPLE / NOT VALIDATION")

    # Position Intent
    position = index.get("position", {})
    position_summary = position.get("summary")
    if position_summary:
        print("\n💰 POSITION INTENT")
        print(f"  Decision: {position_summary.get('decision', 'N/A')}")
        print(f"  Allowed Mode: {position_summary.get('allowed_mode', 'N/A')}")
        print(f"  Portfolio Action: {position_summary.get('portfolio_action', 'N/A')}")
        blockers = position_summary.get("blockers", [])
        if blockers:
            print(f"  Blockers: {', '.join(blockers)}")

    # Operator Registry
    operator = index.get("operator_registry", {})
    operator_summary = operator.get("summary")
    if operator_summary:
        print("\n📋 OPERATOR REGISTRY")
        print(f"  Status: {operator_summary.get('status', 'N/A')}")
        print(f"  Total Operators: {operator_summary.get('total_operators', 'N/A')}")
        print(f"  Issues: {operator_summary.get('issues', 'N/A')}")

    # Learning Hub
    learning = index.get("learning_hub", {})
    learning_exists = learning.get("summary", {}).get("exists") or learning.get("comprehensive_summary", {}).get("exists")
    if learning_exists:
        print("\n🧠 LEARNING HUB")
        print(f"  Summary: {'✅' if learning.get('summary', {}).get('exists') else '❌'}")
        print(f"  Comprehensive: {'✅' if learning.get('comprehensive_summary', {}).get('exists') else '❌'}")
        print(f"  Calibration Events: {learning.get('calibration_events_count', 0)}")

    print()


if __name__ == "__main__":
    main()
