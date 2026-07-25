from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.commands.weekly.claim_evaluator import dedupe_entries


def _entry(recorded_at: str, claim: str = "claim") -> dict:
    return {
        "recorded_at": recorded_at,
        "date": "2026-06-18",
        "decision": "WATCH",
        "confidence": "medium",
        "evidence_grade": "D",
        "time_horizon": "1w",
        "asset_scope": ["SPY", "TLT"],
        "trade_thesis": {"claim_ladder": {"claim_statement": claim}},
    }


def test_dedupe_entries_keeps_latest_same_decision_state() -> None:
    entries = [_entry("first"), _entry("second")]
    deduped = dedupe_entries(entries)
    assert len(deduped) == 1
    assert deduped[0]["recorded_at"] == "second"


def test_dedupe_entries_keeps_distinct_claims() -> None:
    entries = [_entry("first", claim="claim-a"), _entry("second", claim="claim-b")]
    assert len(dedupe_entries(entries)) == 2
