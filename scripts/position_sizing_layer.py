#!/usr/bin/env python3
"""Position Sizing Layer — translate trade decisions into position weights.

This script translates trade decisions into position weights based on
governance rules. It does NOT create signals — it only translates
approved decisions into position intents.

Usage:
    python3 scripts/position_sizing_layer.py
    python3 scripts/position_sizing_layer.py --json

Output:
    Output/position/latest.json
    Output/position/latest.md
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from _runtime_io import load_json, load_yaml

ROOT = Path(__file__).resolve().parents[1]
TRADE_DECISION_PATH = ROOT / "Output" / "trade_decision" / "latest.json"
RISK_GATE_PATH = ROOT / "Output" / "trade_decision" / "risk_gate.json"
FRESHNESS_PATH = ROOT / "Output" / "quality" / "freshness_report.json"
POLICY_PATH = ROOT / "governance" / "position_sizing_policy.yaml"
OUTPUT_DIR = ROOT / "Output" / "position"

DEFAULT_ASSETS = ["SPY", "HYG", "TLT"]


def check_hard_blocks(
    trade_decision: dict[str, Any],
    risk_gate: dict[str, Any],
    freshness: dict[str, Any],
) -> list[str]:
    """Check for hard blocks that force zero position."""
    blockers = []

    # Freshness check
    if freshness and freshness.get("verdict") == "FAIL":
        blockers.append("freshness_fail")

    # Evidence grade check
    evidence_grade = trade_decision.get("evidence_grade", "D")
    if evidence_grade == "D":
        blockers.append("evidence_grade_d")

    # Promotion gate check
    risk_notes = trade_decision.get("risk_notes", [])
    for note in risk_notes:
        if "Promotion gate blocked" in note:
            blockers.append("promotion_gate_blocked")
            break

    # Risk gate check
    if risk_gate:
        risk_status = risk_gate.get("risk_check", {}).get("status", "UNKNOWN")
        if risk_status != "APPROVED_FOR_RESEARCH":
            blockers.append("risk_gate_not_approved")

    # Confidence check
    confidence = trade_decision.get("confidence", "low")
    if confidence == "low":
        blockers.append("confidence_low")

    # Paper support check
    paper = trade_decision.get("paper_sources", {})
    if isinstance(paper, dict):
        approved = paper.get("approved_support", [])
        if not approved:
            blockers.append("paper_support_missing")

    return blockers


def translate_decision(
    trade_decision: dict[str, Any],
    blockers: list[str],
    policy: dict[str, Any],
) -> dict[str, Any]:
    """Translate trade decision into position intent."""
    decision = trade_decision.get("decision", "NO_TRADE")
    decision_mapping = policy.get("decision_mapping", {})

    # Get mapping for this decision
    mapping = decision_mapping.get(decision, {})

    # If any blockers, force zero position
    if blockers:
        return {
            "portfolio_action": "hold_flat",
            "positions": [
                {
                    "asset": asset,
                    "direction": "flat",
                    "target_weight": 0.0,
                    "max_weight": 0.0,
                    "risk_unit": 0.0,
                }
                for asset in DEFAULT_ASSETS
            ],
        }

    # Check if decision is enabled
    if not mapping.get("enabled", True):
        return {
            "portfolio_action": "hold_flat",
            "positions": [
                {
                    "asset": asset,
                    "direction": "flat",
                    "target_weight": 0.0,
                    "max_weight": 0.0,
                    "risk_unit": 0.0,
                }
                for asset in DEFAULT_ASSETS
            ],
        }

    # Get action and weights
    action = mapping.get("action", "hold_flat")
    target_weight = mapping.get("target_weight", 0.0)
    max_weight = mapping.get("max_weight", 0.0)
    risk_unit = mapping.get("risk_unit", 0.0)

    return {
        "portfolio_action": action,
        "positions": [
            {
                "asset": asset,
                "direction": "long" if target_weight > 0 else ("short" if target_weight < 0 else "flat"),
                "target_weight": target_weight,
                "max_weight": max_weight,
                "risk_unit": risk_unit,
            }
            for asset in DEFAULT_ASSETS
        ],
    }


def build_position_intent(
    trade_decision: dict[str, Any],
    risk_gate: dict[str, Any],
    freshness: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    """Build complete position intent."""
    now = datetime.now(UTC)
    date_str = now.strftime("%Y-%m-%d")

    # Check hard blocks
    blockers = check_hard_blocks(trade_decision, risk_gate, freshness)

    # Translate decision
    translation = translate_decision(trade_decision, blockers, policy)

    # Determine allowed mode
    if blockers:
        allowed_mode = "research_only"
    else:
        risk_status = (risk_gate or {}).get("risk_check", {}).get("status", "UNKNOWN")
        if risk_status == "APPROVED_FOR_PAPER_TRADING":
            allowed_mode = "paper_trading"
        else:
            allowed_mode = "research_only"

    return {
        "schema_version": "position_intent.v1",
        "generated_at": now.isoformat(),
        "date": date_str,
        "decision": trade_decision.get("decision", "NO_TRADE"),
        "allowed_mode": allowed_mode,
        "portfolio_action": translation["portfolio_action"],
        "positions": translation["positions"],
        "blockers": blockers,
        "risk_notes": trade_decision.get("risk_notes", []),
    }


def format_markdown(intent: dict[str, Any]) -> str:
    lines = [
        f"# Position Intent — {intent['date']}",
        "",
        f"**Generated:** {intent['generated_at']}",
        "",
        "---",
        "",
        "## Decision",
        "",
        f"- **Decision:** {intent['decision']}",
        f"- **Allowed Mode:** {intent['allowed_mode']}",
        f"- **Portfolio Action:** {intent['portfolio_action']}",
        "",
        "## Positions",
        "",
        "| Asset | Direction | Target Weight | Max Weight | Risk Unit |",
        "|---|---|---:|---:|---:|",
    ]

    for pos in intent["positions"]:
        lines.append(
            f"| {pos['asset']} | {pos['direction']} | {pos['target_weight']:.2%} | {pos['max_weight']:.2%} | {pos['risk_unit']:.2f} |"
        )

    if intent["blockers"]:
        lines += [
            "",
            "## Blockers",
            "",
        ]
        for blocker in intent["blockers"]:
            lines.append(f"- {blocker}")

    lines += [
        "",
        "---",
        "",
        "*This is a position intent, not an execution order. Use for paper trading and calibration only.*",
    ]

    return "\n".join(lines) + "\n"


def write_outputs(intent: dict[str, Any]) -> dict[str, Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = OUTPUT_DIR / "latest.json"
    md_path = OUTPUT_DIR / "latest.md"

    json_path.write_text(json.dumps(intent, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(format_markdown(intent), encoding="utf-8")

    return {"json": json_path, "markdown": md_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="Position sizing layer.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    args = parser.parse_args()

    # Load inputs
    trade_decision = load_json(TRADE_DECISION_PATH)
    risk_gate = load_json(RISK_GATE_PATH)
    freshness = load_json(FRESHNESS_PATH)
    policy = load_yaml(POLICY_PATH)

    if not trade_decision:
        print("No trade decision found.")
        return

    if not policy:
        print("Position sizing policy not found.")
        return

    # Build position intent
    intent = build_position_intent(trade_decision, risk_gate, freshness, policy)

    # Write outputs
    paths = write_outputs(intent)

    if args.json:
        print(json.dumps(intent, indent=2, ensure_ascii=False))
    else:
        print(f"Position intent: {paths['markdown']}")
        print(f"Decision: {intent['decision']}")
        print(f"Allowed mode: {intent['allowed_mode']}")
        print(f"Portfolio action: {intent['portfolio_action']}")
        print(f"Blockers: {intent['blockers']}")


if __name__ == "__main__":
    main()