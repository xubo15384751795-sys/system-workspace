#!/usr/bin/env python3
"""Record Trade Decision — add decision to paper trading ledger.

This script records each trade decision to a JSONL ledger for
later calibration and replay.

Usage:
    python3 scripts/record_trade_decision.py
    python3 scripts/record_trade_decision.py --json

Output:
    Output/trade_ledger/decisions.jsonl
    Output/trade_ledger/latest.md
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TRADE_DECISION_PATH = ROOT / "Output" / "trade_decision" / "latest.json"
RISK_GATE_PATH = ROOT / "Output" / "trade_decision" / "risk_gate.json"
OUTPUT_DIR = ROOT / "Output" / "trade_ledger"


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_paper_sources(raw: Any) -> list[dict[str, str]]:
    """Normalize paper_sources from both old (list) and new (dict) formats.

    Old format: list of source dicts
    New format (trade_decision.v2): {"approved_support": [...], "background_context": [...]}
    """
    if isinstance(raw, list):
        # Old format: list of source dicts
        return [
            {
                "source_file": s.get("source_file", ""),
                "content_type": s.get("content_type", ""),
                "content_id": s.get("content_id", ""),
                "review_status": s.get("review_status", "needs_review"),
            }
            for s in raw
        ]
    if isinstance(raw, dict):
        # New format: dict with approved_support and background_context
        sources = []
        for category in ("approved_support", "background_context"):
            for s in raw.get(category, []):
                if isinstance(s, dict):
                    sources.append({
                        "source_file": s.get("source_file", s.get("source", "")),
                        "content_type": s.get("content_type", s.get("type", category)),
                        "content_id": s.get("content_id", s.get("source", "")),
                        "review_status": s.get("review_status", "needs_review"),
                        "category": category,
                    })
        return sources
    return []


def _normalize_system_sources(raw: Any) -> list[dict[str, str]]:
    """Normalize system_sources from both old and new formats.

    Old format: {"source_type": ..., "status": ...}
    New format: {"source": ..., "type": ..., "status": ...}
    """
    if not isinstance(raw, list):
        return []
    return [
        {
            "source_type": s.get("source_type", s.get("type", s.get("source", ""))),
            "status": s.get("status", ""),
        }
        for s in raw
        if isinstance(s, dict)
    ]


def build_ledger_entry(
    decision: dict[str, Any],
    risk_gate: dict[str, Any],
) -> dict[str, Any]:
    """Build a ledger entry from trade decision and risk gate."""
    return {
        "schema_version": "trade_ledger_entry.v1",
        "recorded_at": datetime.now(UTC).isoformat(),
        "date": decision.get("date", datetime.now(UTC).strftime("%Y-%m-%d")),
        "decision": decision.get("decision", "NO_TRADE"),
        "confidence": decision.get("confidence", "low"),
        "evidence_grade": decision.get("evidence_grade", "D"),
        "allowed_size": decision.get("allowed_size", "zero"),
        "time_horizon": decision.get("time_horizon", "1d"),
        "asset_scope": decision.get("asset_scope", []),
        "invalidation": decision.get("invalidation", []),
        "risk_notes": decision.get("risk_notes", []),
        "paper_sources": _normalize_paper_sources(decision.get("paper_sources", [])),
        "system_sources": _normalize_system_sources(decision.get("system_sources", [])),
        "risk_gate_status": risk_gate.get("risk_check", {}).get("status", "UNKNOWN"),
        "risk_level": risk_gate.get("risk_check", {}).get("risk_level", "UNKNOWN"),
        "trade_thesis": decision.get("trade_thesis", {}),
        "forward_outcome": None,  # To be filled by replay
    }


def append_to_ledger(entry: dict[str, Any]) -> Path:
    """Append entry to ledger JSONL file."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ledger_path = OUTPUT_DIR / "decisions.jsonl"

    with ledger_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return ledger_path


def write_latest(entry: dict[str, Any]) -> Path:
    """Write latest entry as markdown."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    latest_path = OUTPUT_DIR / "latest.md"

    lines = [
        f"# Trade Ledger — {entry['date']}",
        "",
        f"**Recorded:** {entry['recorded_at']}",
        "",
        "---",
        "",
        "## Decision",
        "",
        f"- **Decision:** {entry['decision']}",
        f"- **Confidence:** {entry['confidence']}",
        f"- **Evidence Grade:** {entry['evidence_grade']}",
        f"- **Allowed Size:** {entry['allowed_size']}",
        f"- **Time Horizon:** {entry['time_horizon']}",
        f"- **Asset Scope:** {', '.join(entry['asset_scope'])}",
        "",
        "## Risk Gate",
        "",
        f"- **Status:** {entry['risk_gate_status']}",
        f"- **Risk Level:** {entry['risk_level']}",
        "",
        "## Trade Thesis",
        "",
        f"**Hypothesis:** {entry['trade_thesis'].get('hypothesis', 'N/A')}",
        "",
        "## Paper Sources",
        "",
    ]

    if entry['paper_sources']:
        for source in entry['paper_sources']:
            lines.append(f"- [{source['content_type']}] {source['content_id']} ({source['review_status']})")
    else:
        lines.append("- None")

    lines += [
        "",
        "## System Sources",
        "",
    ]

    for source in entry['system_sources']:
        lines.append(f"- [{source['source_type']}] {source['status']}")

    lines += [
        "",
        "## Forward Outcome",
        "",
        "*To be filled by trade decision replay*",
        "",
        "---",
        "",
        "*This is a paper trading record. Not for live execution.*",
    ]

    latest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return latest_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Record trade decision to ledger.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    args = parser.parse_args()

    # Load trade decision
    decision = load_json(TRADE_DECISION_PATH)
    if not decision:
        print("No trade decision found. Run trade_decision_layer.py first.")
        return

    # Load risk gate
    risk_gate = load_json(RISK_GATE_PATH)
    if not risk_gate:
        print("No risk gate found. Run trade_risk_gate.py first.")
        return

    # Build ledger entry
    entry = build_ledger_entry(decision, risk_gate)

    # Append to ledger
    ledger_path = append_to_ledger(entry)

    # Write latest
    latest_path = write_latest(entry)

    if args.json:
        print(json.dumps(entry, indent=2, ensure_ascii=False))
    else:
        print(f"Recorded to ledger: {ledger_path}")
        print(f"Latest: {latest_path}")
        print(f"Decision: {entry['decision']}")
        print(f"Confidence: {entry['confidence']}")
        print(f"Risk Gate: {entry['risk_gate_status']}")


if __name__ == "__main__":
    main()
