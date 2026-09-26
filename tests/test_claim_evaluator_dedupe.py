from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from system_learning.operators.claim_evaluator import (
    dedupe_entries,
    update_forward_outcomes,
)


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


def test_dedupe_entries_keeps_latest_claim_state() -> None:
    deduped = dedupe_entries([_entry("first"), _entry("second")])
    assert len(deduped) == 1
    assert deduped[0]["recorded_at"] == "second"


def test_dedupe_entries_keeps_distinct_claims() -> None:
    assert len(dedupe_entries([_entry("first", "a"), _entry("second", "b")])) == 2


def test_update_forward_outcomes_matches_entry_key_not_date() -> None:
    first = _entry("first", "a")
    second = _entry("second", "b")
    evaluations = [
        {
            "entry_date": "2026-06-18",
            "entry_key": (
                "2026-06-18",
                "WATCH",
                "medium",
                "D",
                "1w",
                ("SPY", "TLT"),
                "a",
            ),
            "days_since": 0,
            "status": "confirmed",
            "md_continuity": {},
            "invalidation_status": {},
            "outcome": {},
        }
    ]

    updated = update_forward_outcomes([first, second], evaluations)
    assert updated[0]["forward_outcome"]["status"] == "confirmed"
    assert "forward_outcome" not in updated[1]
