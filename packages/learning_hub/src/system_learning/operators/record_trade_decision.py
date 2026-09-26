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
import hashlib
import json
import logging
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from verity.runtime.runtime_io import ROOT, ensure_dir, load_json, surface_dir
from system_runtime.events import EventEnvelope, JsonlEventStore

TRADE_DECISION_PATH = surface_dir("trade_decision") / "latest.json"
RISK_GATE_PATH = surface_dir("trade_decision") / "risk_gate.json"
OUTPUT_DIR = surface_dir("trade_ledger")


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
            "source_type": s.get("source_type", s.get("source", s.get("type", ""))),
            "status": s.get("status", ""),
        }
        for s in raw
        if isinstance(s, dict)
    ]


def _resolve_velocity_gate_state() -> dict[str, Any]:
    """Record-only velocity gate snapshot for the ledger (FULL / EXIT / UNKNOWN)."""
    try:
        from strategy_lab.risk_gate import latest_velocity_gate_state

        return latest_velocity_gate_state()
    except ModuleNotFoundError:
        try:
            from strategy_lab.risk_gate import latest_velocity_gate_state

            return latest_velocity_gate_state()
        except Exception as exc:  # noqa: BLE001 — ledger must still write
            return {
                "state": "UNKNOWN",
                "position": None,
                "trigger": None,
                "trigger_reason": f"unavailable: {exc}",
                "source": "error",
                "as_of_date": None,
            }
    except Exception as exc:  # noqa: BLE001 — ledger must still write
        return {
            "state": "UNKNOWN",
            "position": None,
            "trigger": None,
            "trigger_reason": f"unavailable: {exc}",
            "source": "error",
            "as_of_date": None,
        }


def build_ledger_entry(
    decision: dict[str, Any],
    risk_gate: dict[str, Any],
    velocity_gate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a ledger entry from trade decision and risk gate."""
    vg = velocity_gate if velocity_gate is not None else None
    if vg is None and isinstance(decision.get("velocity_gate"), dict):
        vg = decision["velocity_gate"]
    if vg is None:
        vg = _resolve_velocity_gate_state()
    stance = decision.get("stance") or decision.get("decision", "WATCH")
    size = decision.get("size")
    if size is None:
        # Legacy allowed_size mapping
        label = decision.get("allowed_size", "zero")
        size = {"zero": 0.0, "small": 0.25, "medium": 0.5, "large": 1.0}.get(label, 0.0)
    return {
        "schema_version": "trade_ledger_entry.v2",
        "recorded_at": datetime.now(UTC).isoformat(),
        "date": decision.get("date", datetime.now(UTC).strftime("%Y-%m-%d")),
        "decision": decision.get("decision", stance),
        "stance": stance,
        "size": float(size),
        "effective_size": decision.get("effective_size"),
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
        "velocity_gate_state": (
            decision.get("velocity_gate_state")
            or vg.get("state")
            or "UNKNOWN"
        ),
        "velocity_gate": vg,
        "trade_thesis": decision.get("trade_thesis", {}),
        "learning_trace": decision.get("learning_trace"),
        "decision_fingerprint": decision_fingerprint(decision),
        "forward_outcome": None,  # claim continuity (claim_evaluator)
        "market_forward_outcome": None,  # filled by trade_decision_replay / evaluate backfill
    }


def decision_fingerprint(decision: dict[str, Any]) -> str:
    """Stable fingerprint for one observable decision state."""
    thesis = decision.get("trade_thesis", {})
    payload = {
        "date": decision.get("date", ""),
        "decision": decision.get("decision", "WATCH"),
        "stance": decision.get("stance", decision.get("decision", "WATCH")),
        "size": decision.get("size"),
        "confidence": decision.get("confidence", "low"),
        "evidence_grade": decision.get("evidence_grade", "D"),
        "time_horizon": decision.get("time_horizon", "1d"),
        "asset_scope": sorted(decision.get("asset_scope", [])),
        "claim": thesis.get("claim_ladder", {}).get("claim_statement", thesis.get("hypothesis", "")),
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _load_ledger(path: Path) -> list[dict[str, Any]]:
    return JsonlEventStore(path).read_payloads()


def _write_ledger(path: Path, entries: list[dict[str, Any]]) -> None:
    JsonlEventStore(path).replace_payloads(
        entries,
        event_type="trade_decision_recorded",
        payload_schema="trade_ledger_entry.v2",
        producer="record_trade_decision",
        run_id=os.environ.get("ZCODE_BUNDLE_RUN_ID"),
    )


def upsert_to_ledger(entry: dict[str, Any]) -> tuple[Path, str]:
    """Insert the entry, replacing the same dated decision fingerprint."""
    ensure_dir(OUTPUT_DIR)
    ledger_path = OUTPUT_DIR / "decisions.jsonl"

    entries = _load_ledger(ledger_path)
    fingerprint = entry.get("decision_fingerprint")
    date = entry.get("date")
    for idx, existing in enumerate(entries):
        if existing.get("date") == date and existing.get("decision_fingerprint") == fingerprint:
            prior_outcome = existing.get("forward_outcome")
            if prior_outcome is not None:
                entry["forward_outcome"] = prior_outcome
            prior_market = existing.get("market_forward_outcome")
            if prior_market is not None:
                entry["market_forward_outcome"] = prior_market
            entries[idx] = entry
            _write_ledger(ledger_path, entries)
            return ledger_path, "updated"

    event = EventEnvelope.create(
        event_type="trade_decision_recorded",
        payload_schema=str(entry.get("schema_version", "trade_ledger_entry.v2")),
        payload=entry,
        producer="record_trade_decision",
        run_id=os.environ.get("ZCODE_BUNDLE_RUN_ID"),
        event_id=str(entry.get("decision_fingerprint") or "") or None,
        occurred_at=str(entry.get("recorded_at") or "") or None,
    )
    mode = JsonlEventStore(ledger_path).upsert(
        event,
        identity_fields=("date", "decision_fingerprint"),
    )
    return ledger_path, mode


def write_latest(entry: dict[str, Any]) -> Path:
    """Write latest entry as markdown."""
    ensure_dir(OUTPUT_DIR)
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
        f"- **Stance:** {entry.get('stance', entry['decision'])}",
        f"- **Size:** {entry.get('size', 'N/A')}",
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
        f"- **Velocity Gate:** {entry.get('velocity_gate_state', 'UNKNOWN')}",
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

    # Upsert into ledger
    ledger_path, write_mode = upsert_to_ledger(entry)

    # Write latest
    latest_path = write_latest(entry)

    if args.json:
        print(json.dumps(entry, indent=2, ensure_ascii=False))
    else:
        print(f"Recorded to ledger: {ledger_path}")
        print(f"Mode: {write_mode}")
        print(f"Latest: {latest_path}")
        print(f"Decision: {entry['decision']}")
        print(f"Confidence: {entry['confidence']}")
        print(f"Risk Gate: {entry['risk_gate_status']}")

    # Evaluate past claims and update forward_outcomes
    claim_eval_script = ROOT / "scripts" / "commands" / "weekly" / "claim_evaluator.py"
    if claim_eval_script.exists():
        try:
            subprocess.run(
                [sys.executable, str(claim_eval_script)],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            logging.getLogger(__name__).warning("claim_evaluator subprocess failed: %s", exc)


if __name__ == "__main__":
    main()
