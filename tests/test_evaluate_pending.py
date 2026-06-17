"""Evaluate Pending — tests for the 1d/1w/1m window evaluator.

Verifies that pending evaluation records are correctly evaluated
against actual market returns when their windows elapse.
"""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from evaluate_pending import (
    classify_outcome,
    compute_forward_return,
    evaluate_record,
    load_pending_records,
    run_evaluation,
    save_pending_records,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _isolated_eval_dir(tmp_path, monkeypatch):
    """Redirect all file I/O to a temp directory."""
    eval_dir = tmp_path / "evaluations"
    eval_dir.mkdir()
    pending = eval_dir / "pending.jsonl"
    log_path = eval_dir / "eval_log.jsonl"
    monkeypatch.setattr("evaluate_pending.EVAL_DIR", eval_dir)
    monkeypatch.setattr("evaluate_pending.PENDING_PATH", pending)
    monkeypatch.setattr("evaluate_pending.EVAL_LOG_PATH", log_path)
    return eval_dir


@pytest.fixture
def mock_market_series():
    """Build synthetic SPY/HYG/TLT price series for testing."""
    dates = pd.date_range("2026-06-01", periods=30, freq="B", tz=UTC)
    # SPY goes up ~2% over the period
    spy_prices = [500.0 + i * 0.35 for i in range(30)]
    # HYG goes up ~1%
    hyg_prices = [75.0 + i * 0.03 for i in range(30)]
    # TLT goes down ~1%
    tlt_prices = [90.0 - i * 0.03 for i in range(30)]

    return {
        "SPY": pd.Series(spy_prices, index=dates, name="close"),
        "HYG": pd.Series(hyg_prices, index=dates, name="close"),
        "TLT": pd.Series(tlt_prices, index=dates, name="close"),
    }


@pytest.fixture
def pending_record():
    """A pending evaluation record from June 2."""
    return {
        "eval_id": "eval_2026-06-02_abc12345",
        "source": "judgment_layer",
        "date": "2026-06-02",
        "decision": "NO_TRADE",
        "confidence": "low",
        "generated_at": "2026-06-02T10:00:00Z",
        "eval_after_1d": "2026-06-03",
        "eval_after_1w": "2026-06-09",
        "eval_after_1m": "2026-07-02",
        "status": "pending",
        "evaluations": {"1d": None, "1w": None, "1m": None},
    }


# ── Forward return computation ──────────────────────────────────────────────

def test_forward_return_basic(mock_market_series):
    """Forward return computes correctly."""
    spy = mock_market_series["SPY"]
    ret = compute_forward_return(spy, "2026-06-02", 1)
    assert ret is not None
    # SPY goes from ~500.35 to ~500.70 → positive return
    assert ret > 0


def test_forward_return_none_when_insufficient_data(mock_market_series):
    """Returns None when horizon extends beyond available data."""
    spy = mock_market_series["SPY"]
    ret = compute_forward_return(spy, "2026-06-02", 100)
    assert ret is None


def test_forward_return_none_for_missing_series():
    """Returns None for empty series."""
    empty = pd.Series([], dtype=float)
    ret = compute_forward_return(empty, "2026-06-02", 1)
    assert ret is None


# ── Outcome classification ──────────────────────────────────────────────────

def test_classify_no_trade_market_down():
    """NO_TRADE when market goes down is correct."""
    assert classify_outcome("NO_TRADE", "low", -1.5) == "correct"


def test_classify_no_trade_market_up_small():
    """NO_TRADE when market goes up slightly is neutral."""
    assert classify_outcome("NO_TRADE", "low", 0.3) == "neutral"


def test_classify_no_trade_market_up_big():
    """NO_TRADE when market goes up a lot is incorrect."""
    assert classify_outcome("NO_TRADE", "low", 2.0) == "incorrect"


def test_classify_watch_only_market_down():
    """WATCH_ONLY when market goes down is correct."""
    assert classify_outcome("WATCH_ONLY", "medium", -0.8) == "correct"


def test_classify_watch_neutral():
    """WATCH is always neutral (no position taken)."""
    assert classify_outcome("WATCH", "medium", 3.0) == "neutral"


def test_classify_unverifiable():
    """Missing return data → unverifiable."""
    assert classify_outcome("NO_TRADE", "low", None) == "unverifiable"


# ── Record evaluation ───────────────────────────────────────────────────────

def test_evaluate_record_1d_window(pending_record, mock_market_series):
    """1d window is evaluated when due; 1w/1m remain pending."""
    # Today is past eval_after_1d (2026-06-03) but before 1w (2026-06-09)
    today = datetime(2026, 6, 4, tzinfo=UTC)
    updated, logs = evaluate_record(pending_record, mock_market_series, today)

    assert updated["evaluations"]["1d"] is not None
    assert updated["evaluations"]["1w"] is None  # not due yet (June 4 < June 9)
    assert updated["evaluations"]["1m"] is None  # not due yet (June 4 < July 2)
    assert updated["status"] == "pending"  # not all windows done
    assert len(logs) == 1


def test_evaluate_record_all_windows(pending_record, mock_market_series):
    """All windows evaluated when far in the future."""
    today = datetime(2026, 8, 1, tzinfo=UTC)
    updated, logs = evaluate_record(pending_record, mock_market_series, today)

    assert updated["evaluations"]["1d"] is not None
    assert updated["evaluations"]["1w"] is not None
    assert updated["evaluations"]["1m"] is not None
    assert updated["status"] == "evaluated"
    assert len(logs) == 3


def test_evaluate_record_no_market_data(pending_record):
    """No market data → no evaluation."""
    today = datetime(2026, 8, 1, tzinfo=UTC)
    updated, logs = evaluate_record(pending_record, {}, today)

    # With empty market series, forward returns are all None → unverifiable
    assert updated["evaluations"]["1d"]["outcome"] == "unverifiable"


def test_evaluate_already_evaluated_skipped(mock_market_series):
    """Already-evaluated records are not re-evaluated."""
    record = {
        "eval_id": "eval_2026-06-02_xyz",
        "date": "2026-06-02",
        "decision": "NO_TRADE",
        "confidence": "low",
        "eval_after_1d": "2026-06-03",
        "eval_after_1w": "2026-06-09",
        "eval_after_1m": "2026-07-02",
        "status": "evaluated",
        "evaluations": {
            "1d": {"outcome": "correct", "spy_return_pct": -0.5},
            "1w": {"outcome": "correct", "spy_return_pct": -1.2},
            "1m": {"outcome": "correct", "spy_return_pct": -2.0},
        },
    }
    today = datetime(2026, 8, 1, tzinfo=UTC)
    updated, logs = evaluate_record(record, mock_market_series, today)
    assert len(logs) == 0  # no new evaluations


# ── Full pipeline ────────────────────────────────────────────────────────────

def test_run_evaluation_empty(_isolated_eval_dir, monkeypatch):
    """Empty pending file → no-op."""
    monkeypatch.setattr("evaluate_pending.load_market_series", lambda: {"SPY": pd.Series([1.0])})
    result = run_evaluation()
    assert result["total"] == 0


def test_run_evaluation_with_records(
    _isolated_eval_dir, pending_record, mock_market_series, monkeypatch,
):
    """Full pipeline evaluates due records."""
    # Write a pending record
    save_pending_records([pending_record])
    monkeypatch.setattr("evaluate_pending.load_market_series", lambda: mock_market_series)

    # Evaluate with today far in the future
    monkeypatch.setattr("evaluate_pending.datetime", type("dt", (), {
        "now": staticmethod(lambda tz=None: datetime(2026, 8, 1, tzinfo=UTC)),
        "strptime": datetime.strptime,
    }))

    result = run_evaluation()
    assert result["total"] == 1
    assert result["evaluated"] == 3  # 3 windows evaluated


def test_save_and_reload_roundtrip(_isolated_eval_dir, pending_record):
    """Save → load preserves all fields."""
    save_pending_records([pending_record])
    loaded = load_pending_records()
    assert len(loaded) == 1
    assert loaded[0]["eval_id"] == pending_record["eval_id"]
    assert loaded[0]["status"] == "pending"


def test_log_entries_written(
    _isolated_eval_dir, pending_record, mock_market_series, monkeypatch,
):
    """Evaluation writes to eval_log.jsonl."""
    save_pending_records([pending_record])
    monkeypatch.setattr("evaluate_pending.load_market_series", lambda: mock_market_series)

    # Force all windows to be due
    today = datetime(2026, 8, 1, tzinfo=UTC)
    records = load_pending_records()
    updated, logs = evaluate_record(records[0], mock_market_series, today)
    save_pending_records([updated])

    from evaluate_pending import EVAL_LOG_PATH, append_eval_log
    append_eval_log(logs)

    assert EVAL_LOG_PATH.exists()
    log_records = []
    with EVAL_LOG_PATH.open() as f:
        for line in f:
            log_records.append(json.loads(line.strip()))
    assert len(log_records) == 3
    assert all("outcome" in r for r in log_records)
