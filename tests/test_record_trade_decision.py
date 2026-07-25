from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from record_trade_decision import (
    build_ledger_entry,
    decision_fingerprint,
    upsert_to_ledger,
)

from system_runtime.events import payload_of


def _stored_payload(path: Path) -> dict:
    return payload_of(json.loads(path.read_text(encoding="utf-8").splitlines()[0]))


def _decision(claim: str = "mechanism hypothesis") -> dict:
    return {
        "date": "2026-06-18",
        "decision": "RISK_ON",
        "stance": "RISK_ON",
        "size": 0.5,
        "effective_size": 0.5,
        "confidence": "medium",
        "evidence_grade": "D",
        "allowed_size": "medium",
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
    monkeypatch.setattr(
        "record_trade_decision._resolve_velocity_gate_state",
        lambda: {"state": "FULL", "position": 1.0, "trigger": False, "source": "test"},
    )

    first = build_ledger_entry(_decision(), {"risk_check": {"status": "APPROVED"}})
    path, mode = upsert_to_ledger(first)
    assert mode == "inserted"

    second = build_ledger_entry(_decision(), {"risk_check": {"status": "APPROVED"}})
    second["recorded_at"] = "later"
    path, mode = upsert_to_ledger(second)
    assert mode == "updated"

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert payload_of(json.loads(lines[0]))["recorded_at"] == "later"


def test_upsert_preserves_forward_outcome(tmp_path, monkeypatch) -> None:
    output_dir = tmp_path / "trade_ledger"
    monkeypatch.setattr("record_trade_decision.OUTPUT_DIR", output_dir)
    monkeypatch.setattr(
        "record_trade_decision._resolve_velocity_gate_state",
        lambda: {"state": "FULL", "position": 1.0, "trigger": False, "source": "test"},
    )

    first = build_ledger_entry(_decision(), {"risk_check": {"status": "APPROVED"}})
    first["forward_outcome"] = {"status": "evaluated"}
    path, _ = upsert_to_ledger(first)

    second = build_ledger_entry(_decision(), {"risk_check": {"status": "APPROVED"}})
    path, mode = upsert_to_ledger(second)

    assert mode == "updated"
    stored = _stored_payload(path)
    assert stored["forward_outcome"] == {"status": "evaluated"}


def test_build_ledger_entry_is_v2_with_velocity_gate(monkeypatch) -> None:
    monkeypatch.setattr(
        "record_trade_decision._resolve_velocity_gate_state",
        lambda: {
            "state": "FULL",
            "position": 1.0,
            "trigger": False,
            "trigger_reason": "calm",
            "source": "test",
            "as_of_date": "2026-06-18",
        },
    )
    entry = build_ledger_entry(_decision(), {"risk_check": {"status": "APPROVED"}})
    assert entry["schema_version"] == "trade_ledger_entry.v2"
    assert entry["velocity_gate_state"] == "FULL"
    assert entry["velocity_gate"]["state"] == "FULL"
    assert entry["stance"] == "RISK_ON"
    assert entry["size"] == 0.5
    assert entry["market_forward_outcome"] is None


def test_build_ledger_entry_preserves_learning_trace(monkeypatch) -> None:
    monkeypatch.setattr(
        "record_trade_decision._resolve_velocity_gate_state",
        lambda: {"state": "FULL", "position": 1.0, "source": "test"},
    )
    decision = _decision()
    decision["learning_trace"] = {
        "schema_version": "decision_learning_trace.v1",
        "authority": "shadow_only",
    }
    entry = build_ledger_entry(decision, {"risk_check": {"status": "APPROVED"}})

    assert entry["learning_trace"] == decision["learning_trace"]


def test_upsert_preserves_market_forward_outcome(tmp_path, monkeypatch) -> None:
    output_dir = tmp_path / "trade_ledger"
    monkeypatch.setattr("record_trade_decision.OUTPUT_DIR", output_dir)
    monkeypatch.setattr(
        "record_trade_decision._resolve_velocity_gate_state",
        lambda: {"state": "EXIT", "position": 0.0, "trigger": True, "source": "test"},
    )

    first = build_ledger_entry(_decision(), {"risk_check": {"status": "APPROVED"}})
    first["market_forward_outcome"] = {"status": "evaluated"}
    path, _ = upsert_to_ledger(first)

    second = build_ledger_entry(_decision(), {"risk_check": {"status": "APPROVED"}})
    path, mode = upsert_to_ledger(second)

    assert mode == "updated"
    stored = _stored_payload(path)
    assert stored["market_forward_outcome"] == {"status": "evaluated"}
    assert stored["velocity_gate_state"] == "EXIT"
