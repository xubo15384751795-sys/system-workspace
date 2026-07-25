"""Pending Evaluation — tests for the feedback loop entry point.

Verifies that judgment and trade decision outputs write records
to Output/evaluations/pending.jsonl with correct structure.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from pending_evaluation import (
    _compute_eval_windows,
    _make_eval_id,
    write_pending_evaluation,
)


@pytest.fixture(autouse=True)
def _isolated_eval_dir(tmp_path, monkeypatch):
    """Redirect pending.jsonl writes to a temp directory."""
    eval_dir = tmp_path / "evaluations"
    eval_dir.mkdir()
    pending = eval_dir / "pending.jsonl"
    monkeypatch.setattr("pending_evaluation.EVAL_DIR", eval_dir)
    monkeypatch.setattr("pending_evaluation.PENDING_PATH", pending)
    return pending


# ── ID generation ────────────────────────────────────────────────────────────

def test_eval_id_deterministic():
    """Same inputs produce the same eval_id."""
    a = _make_eval_id("judgment_layer", "2026-06-17", "2026-06-17T10:00:00Z")
    b = _make_eval_id("judgment_layer", "2026-06-17", "2026-06-17T10:00:00Z")
    assert a == b


def test_eval_id_differs_by_source():
    """Different sources produce different eval_ids."""
    a = _make_eval_id("judgment_layer", "2026-06-17", "2026-06-17T10:00:00Z")
    b = _make_eval_id("trade_decision_layer", "2026-06-17", "2026-06-17T10:00:00Z")
    assert a != b


def test_eval_id_format():
    """eval_id follows eval_YYYY-MM-DD_<8-char-hex> format."""
    eid = _make_eval_id("judgment_layer", "2026-06-17", "2026-06-17T10:00:00Z")
    assert eid.startswith("eval_2026-06-17_")
    # Last segment after the date prefix is the 8-char hex hash
    hash_part = eid.split("eval_2026-06-17_")[1]
    assert len(hash_part) == 8
    assert all(c in "0123456789abcdef" for c in hash_part)


# ── Window computation ──────────────────────────────────────────────────────

def test_eval_windows_correct():
    """1d/1w/1m windows are computed correctly."""
    windows = _compute_eval_windows("2026-06-17")
    assert windows["eval_after_1d"] == "2026-06-18"
    assert windows["eval_after_1w"] == "2026-06-24"
    assert windows["eval_after_1m"] == "2026-07-17"


def test_eval_windows_invalid_date():
    """Invalid date falls back to now (no crash)."""
    windows = _compute_eval_windows("not-a-date")
    assert "eval_after_1d" in windows
    assert "eval_after_1w" in windows
    assert "eval_after_1m" in windows


# ── Write records ───────────────────────────────────────────────────────────

def test_write_judgment_card(tmp_path, _isolated_eval_dir):
    """Judgment card writes correct pending record."""
    card = {
        "as_of": "2026-06-17",
        "generated_at": "2026-06-17T10:00:00Z",
        "decision": "WATCH_ONLY",
        "confidence": {"level": "medium", "reasons": ["test"]},
    }
    write_pending_evaluation("judgment_layer", card)

    records = _read_jsonl(_isolated_eval_dir)
    assert len(records) == 1
    r = records[0]
    assert r["source"] == "judgment_layer"
    assert r["date"] == "2026-06-17"
    assert r["decision"] == "WATCH_ONLY"
    assert r["confidence"] == "medium"  # unwrapped from dict
    assert r["status"] == "pending"
    assert r["evaluations"] == {"1d": None, "1w": None, "1m": None}
    assert r["eval_id"].startswith("eval_2026-06-17_")


def test_write_trade_decision(tmp_path, _isolated_eval_dir):
    """Trade decision writes correct pending record."""
    decision = {
        "date": "2026-06-17",
        "generated_at": "2026-06-17T10:00:00Z",
        "decision": "NO_TRADE",
        "confidence": "low",
        "learning_trace": {"schema_version": "decision_learning_trace.v1"},
        "trigger_conditions": ["Velocity gate FULL"],
        "invalidation": ["Velocity gate EXIT"],
    }
    write_pending_evaluation("trade_decision_layer", decision)

    records = _read_jsonl(_isolated_eval_dir)
    assert len(records) == 1
    r = records[0]
    assert r["source"] == "trade_decision_layer"
    assert r["decision"] == "NO_TRADE"
    assert r["confidence"] == "low"
    assert r["learning_trace"] == decision["learning_trace"]
    assert r["active_inference_spec"]["trigger_conditions"] == ["Velocity gate FULL"]
    assert r["active_inference_spec"]["invalidation_conditions"] == ["Velocity gate EXIT"]


def test_append_only(tmp_path, _isolated_eval_dir):
    """Multiple writes append, not overwrite."""
    for i in range(3):
        card = {
            "date": f"2026-06-{17+i}",
            "generated_at": f"2026-06-{17+i}T10:00:00Z",
            "decision": "WATCH_ONLY",
            "confidence": "medium",
        }
        write_pending_evaluation("judgment_layer", card)

    records = _read_jsonl(_isolated_eval_dir)
    assert len(records) == 3
    dates = [r["date"] for r in records]
    assert dates == ["2026-06-17", "2026-06-18", "2026-06-19"]


def test_same_observation_is_upserted_not_duplicated(tmp_path, _isolated_eval_dir):
    card = {
        "date": "2026-06-17",
        "generated_at": "2026-06-17T10:00:00Z",
        "decision": "WATCH_ONLY",
        "confidence": "medium",
    }
    write_pending_evaluation("judgment_layer", card)
    card["generated_at"] = "2026-06-17T11:00:00Z"
    write_pending_evaluation("judgment_layer", card)

    records = _read_jsonl(_isolated_eval_dir)
    assert len(records) == 1
    assert records[0]["generated_at"] == "2026-06-17T11:00:00Z"
    assert records[0]["observation_fingerprint"]


def test_missing_date_fallback(tmp_path, _isolated_eval_dir):
    """Card with no date/as_of still writes a record."""
    card = {
        "generated_at": "2026-06-17T10:00:00Z",
        "decision": "UNKNOWN",
        "confidence": "low",
    }
    write_pending_evaluation("judgment_layer", card)

    records = _read_jsonl(_isolated_eval_dir)
    assert len(records) == 1
    # Should use today's date as fallback
    assert records[0]["date"] is not None


def test_record_has_all_required_fields(tmp_path, _isolated_eval_dir):
    """Record contains all fields needed for evaluation."""
    card = {
        "date": "2026-06-17",
        "generated_at": "2026-06-17T10:00:00Z",
        "decision": "WATCH_ONLY",
        "confidence": "medium",
    }
    write_pending_evaluation("judgment_layer", card)
    records = _read_jsonl(_isolated_eval_dir)
    r = records[0]

    required = [
        "eval_id", "source", "date", "decision", "confidence",
        "generated_at", "eval_after_1d", "eval_after_1w", "eval_after_1m",
        "status", "evaluations",
    ]
    for field in required:
        assert field in r, f"Missing field: {field}"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _read_jsonl(path: Path) -> list[dict]:
    records = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records
