#!/usr/bin/env python3
"""Build feedback sample pool from event replay windows and daily judgments.

Creates stratified feedback_sample.v1 records under Data/feedback_samples/.

Usage:
    python3 scripts/build_feedback_sample_pool.py
    python3 scripts/build_feedback_sample_pool.py --append
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from _runtime_io import ROOT, ensure_dir, load_json

MANIFEST = ROOT / "Data" / "feedback_samples" / "sample_manifest.jsonl"
REPLAY_DIR = ROOT / "Output" / "sandbox" / "event_replay"
FRAMEWORK = ROOT / "Output" / "current" / "framework_output.json"
JUDGMENT = ROOT / "Output" / "judgment" / "judgment_card.json"
TRADE = ROOT / "Output" / "judgment" / "trade_decision.json"
GATE = ROOT / "Output" / "judgment" / "promotion_gate.json"
OPERATORS = ROOT / "Output" / "current" / "operator_activations.json"


def _sample_id(as_of: str, sample_type: str, suffix: str) -> str:
    h = hashlib.sha256(f"{as_of}:{sample_type}:{suffix}".encode()).hexdigest()[:8]
    return f"{as_of}_{sample_type}_{h}"


def _read_manifest_ids() -> set[str]:
    if not MANIFEST.exists():
        return set()
    ids: set[str] = set()
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        ids.add(json.loads(line).get("sample_id", ""))
    return ids


def _build_sample(
    as_of: str,
    sample_type: str,
    why: str,
    event: dict[str, Any] | None = None,
    operator_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fw = load_json(FRAMEWORK) or {}
    basic = fw.get("basic", {})
    judgment = load_json(JUDGMENT) or {}
    trade = load_json(TRADE) or {}
    gate = load_json(GATE) or {}

    return {
        "schema_version": "feedback_sample.v1",
        "sample_id": _sample_id(as_of, sample_type, why[:40]),
        "as_of_date": as_of,
        "sample_type": sample_type,
        "why_selected": why,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "system_state": {
            "m_value": basic.get("M"),
            "d_value": basic.get("D"),
            "k_value": basic.get("K"),
            "x_value": basic.get("X"),
            "channel_coverage": list(basic.get("channel_coverage", [])),
        },
        "system_judgment": {
            "decision": trade.get("decision"),
            "confidence": judgment.get("confidence"),
            "claim_tier": judgment.get("claim_tier"),
            "claim_label": judgment.get("claim_label"),
            "mechanism_hypothesis": judgment.get("mechanism_hypothesis"),
            "evidence_grade": judgment.get("evidence_grade"),
            "promotion_gate": gate.get("verdict"),
        },
        "operator_activations": operator_snapshot,
        "closure_loop": {
            "failure_reason": None,
            "suggested_fix": {
                "operator": None,
                "proxy": None,
                "gate": None,
            },
            "human_review_required": True,
        },
        "event_context": event,
        "forward_outcome": {},
        "review_label": "needs_review",
    }


def build_pool(append: bool = False) -> int:
    ensure_dir(MANIFEST.parent)
    existing = _read_manifest_ids() if append else set()
    if not append and MANIFEST.exists():
        MANIFEST.write_text("", encoding="utf-8")

    ops_payload = load_json(OPERATORS) or {}
    op_by_date: dict[str, list] = {}
    for act in ops_payload.get("activations", []):
        op_by_date.setdefault(act.get("as_of", ""), []).append(act)

    written = 0
    with MANIFEST.open("a", encoding="utf-8") as fh:
        if REPLAY_DIR.exists():
            for path in sorted(REPLAY_DIR.glob("*.json")):
                if path.name == "summary.json":
                    continue
                window = json.loads(path.read_text(encoding="utf-8"))
                wid = window.get("window_id", path.stem)
                for op_name, block in window.get("operators", {}).items():
                    for rec in block.get("records", []):
                        as_of = rec.get("as_of")
                        if not as_of:
                            continue
                        stype = "event_window"
                        sid = _sample_id(as_of, stype, wid)
                        if sid in existing:
                            continue
                        sample = _build_sample(
                            as_of,
                            stype,
                            f"Event replay window {wid} / {op_name}",
                            event={
                                "event_type": wid,
                                "event_description": window.get("label"),
                                "event_source": "event_replay_factory",
                            },
                            operator_snapshot={op_name: rec},
                        )
                        fh.write(json.dumps(sample, ensure_ascii=False) + "\n")
                        existing.add(sid)
                        written += 1

    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Build feedback sample pool.")
    parser.add_argument("--append", action="store_true")
    args = parser.parse_args()
    n = build_pool(append=args.append)
    print(f"Wrote {n} sample(s) → {MANIFEST}")


if __name__ == "__main__":
    main()
