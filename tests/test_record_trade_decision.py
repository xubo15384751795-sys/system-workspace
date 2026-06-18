from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from record_trade_decision import build_ledger_entry, decision_fingerprint, upsert_to_ledger


def _decision(claim: str = "mechanism hypothesis") -> dict:
    return {
        "date": "2026-06-18",
        "decision": "WATCH",
        "confidence": "medium",
        "evidence_grade": "D",
        "time_horizon": "1w",
        "asset_scope": ["TLT", "SPY"],
        "trade_thesis": {
            "hypothesis": "Primary readout",
            "claim_ladder": {"claim_statement": claim},
        },
    }


def test_decision_fingerprint_is_stable_for_same_decision() -> None:
    first = _decision()
    second = _decision()
    second["asset_scope"] = ["SPY", "TLT"]
    assert decision_fingerprint(first) == decision_fingerprint(second)


def test_upsert_replaces_same_dated_fingerprint(tmp_path, monkeypatch) -> None:
    output_dir = tmp_path / "trade_ledger"
    monkeypatch.setattr("record_trade_decision.OUTPUT_DIR", output_dir)

    first = build_ledger_entry(_decision(), {"risk_check": {"status": "APPROVED"}})
    path, mode = upsert_to_ledger(first)
    assert mode == "inserted"

    second = build_ledger_entry(_decision(), {"risk_check": {"status": "APPROVED"}})
    second["recorded_at"] = "later"
    path, mode = upsert_to_ledger(second)
    assert mode == "updated"

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["recorded_at"] == "later"


def test_upsert_preserves_forward_outcome(tmp_path, monkeypatch) -> None:
    output_dir = tmp_path / "trade_ledger"
    monkeypatch.setattr("record_trade_decision.OUTPUT_DIR", output_dir)

    first = build_ledger_entry(_decision(), {"risk_check": {"status": "APPROVED"}})
    first["forward_outcome"] = {"status": "evaluated"}
    path, _ = upsert_to_ledger(first)

    second = build_ledger_entry(_decision(), {"risk_check": {"status": "APPROVED"}})
    path, mode = upsert_to_ledger(second)

    assert mode == "updated"
    stored = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert stored["forward_outcome"] == {"status": "evaluated"}
