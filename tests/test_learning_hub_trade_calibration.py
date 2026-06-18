from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from learning_hub_trade_calibration import build_calibration_event, dedupe_entries


def _entry(recorded_at: str, decision: str = "WATCH") -> dict:
    return {
        "recorded_at": recorded_at,
        "date": "2026-06-18",
        "decision": decision,
        "confidence": "medium",
        "evidence_grade": "D",
        "time_horizon": "1w",
        "asset_scope": ["SPY", "TLT"],
        "trade_thesis": {"claim_ladder": {"claim_statement": "claim"}},
    }


def test_dedupe_entries_keeps_latest_state() -> None:
    deduped = dedupe_entries([_entry("first"), _entry("second")])
    assert len(deduped) == 1
    assert deduped[0]["recorded_at"] == "second"


def test_calibration_event_matches_decision_fields() -> None:
    entry = _entry("now", decision="WATCH")
    calibration = {
        "evaluations": [
            {"date": "2026-06-18", "decision": "NO_TRADE", "confidence": "medium", "evidence_grade": "D", "evaluated_horizons": ["1d"]},
            {"date": "2026-06-18", "decision": "WATCH", "confidence": "medium", "evidence_grade": "D", "evaluated_horizons": ["1w"]},
        ]
    }
    event = build_calibration_event(entry, calibration, None)
    assert event["evaluated_horizons"] == ["1w"]
