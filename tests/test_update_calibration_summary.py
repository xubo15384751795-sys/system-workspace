"""Update Calibration Summary — tests for aggregation logic.

Verifies that eval_log.jsonl entries are correctly aggregated by
source, decision type, and window into a calibration summary.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "archive"))

from update_calibration_summary import (
    aggregate_by_source_and_decision,
    build_summary,
    load_eval_log,
    write_outputs,
)


@pytest.fixture(autouse=True)
def _isolated_output(tmp_path, monkeypatch):
    """Redirect file I/O to temp directory."""
    eval_dir = tmp_path / "evaluations"
    eval_dir.mkdir()
    output_dir = tmp_path / "calibration_summary"
    monkeypatch.setattr("update_calibration_summary.EVAL_DIR", eval_dir)
    monkeypatch.setattr("update_calibration_summary.EVAL_LOG_PATH", eval_dir / "eval_log.jsonl")
    monkeypatch.setattr("update_calibration_summary.OUTPUT_DIR", output_dir)
    return eval_dir, output_dir


def _make_log_entry(
    source="judgment_layer",
    decision="NO_TRADE",
    window="1d",
    outcome="correct",
    spy_return=-0.5,
    hyg_return=-0.2,
    tlt_return=0.3,
):
    return {
        "eval_id": f"eval_2026-06-02_{source}_{window}",
        "source": source,
        "window": window,
        "evaluated_at": "2026-06-03T00:00:00Z",
        "decision": decision,
        "confidence": "low",
        "returns": {"SPY": spy_return, "HYG": hyg_return, "TLT": tlt_return},
        "outcome": outcome,
    }


def _write_eval_log(eval_dir: Path, entries: list[dict]):
    log_path = eval_dir / "eval_log.jsonl"
    with log_path.open("w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
    return log_path


# ── Empty / missing ─────────────────────────────────────────────────────────

def test_load_empty_log(_isolated_output):
    """Missing log file → empty list."""
    assert load_eval_log() == []


def test_build_summary_empty(_isolated_output):
    """Empty entries → zero totals."""
    summary = build_summary([])
    assert summary["total_evaluations"] == 0
    assert summary["summary"]["total"] == 0
    assert summary["summary"]["hit_rate"] is None


# ── Single source aggregation ───────────────────────────────────────────────

def test_single_source_single_decision(_isolated_output):
    """One source, one decision type aggregates correctly."""
    eval_dir, _ = _isolated_output
    entries = [
        _make_log_entry(outcome="correct"),
        _make_log_entry(outcome="correct"),
        _make_log_entry(outcome="incorrect"),
    ]
    _write_eval_log(eval_dir, entries)

    summary = build_summary(entries)
    by_src = summary["by_source"]["judgment_layer"]
    assert by_src["NO_TRADE"]["total"] == 3
    assert by_src["NO_TRADE"]["correct"] == 2
    assert by_src["NO_TRADE"]["incorrect"] == 1
    assert by_src["NO_TRADE"]["hit_rate"] == pytest.approx(2 / 3, abs=0.001)


def test_multiple_decisions(_isolated_output):
    """Multiple decision types are grouped separately."""
    entries = [
        _make_log_entry(decision="NO_TRADE", outcome="correct"),
        _make_log_entry(decision="WATCH_ONLY", outcome="neutral"),
        _make_log_entry(decision="WATCH_ONLY", outcome="incorrect"),
    ]
    summary = build_summary(entries)
    by_src = summary["by_source"]["judgment_layer"]
    assert by_src["NO_TRADE"]["total"] == 1
    assert by_src["WATCH_ONLY"]["total"] == 2


# ── Multi-source aggregation ────────────────────────────────────────────────

def test_two_sources_separate(_isolated_output):
    """Judgment and trade decision are aggregated separately."""
    entries = [
        _make_log_entry(source="judgment_layer", outcome="correct"),
        _make_log_entry(source="trade_decision_layer", outcome="incorrect"),
    ]
    summary = build_summary(entries)
    assert "judgment_layer" in summary["by_source"]
    assert "trade_decision_layer" in summary["by_source"]
    assert summary["by_source"]["judgment_layer"]["NO_TRADE"]["correct"] == 1
    assert summary["by_source"]["trade_decision_layer"]["NO_TRADE"]["incorrect"] == 1


# ── Window aggregation ──────────────────────────────────────────────────────

def test_by_window_separate(_isolated_output):
    """1d/1w/1m windows are aggregated separately."""
    entries = [
        _make_log_entry(window="1d", outcome="correct"),
        _make_log_entry(window="1w", outcome="incorrect"),
        _make_log_entry(window="1m", outcome="neutral"),
    ]
    summary = build_summary(entries)
    assert summary["by_window"]["1d"]["correct"] == 1
    assert summary["by_window"]["1w"]["incorrect"] == 1
    assert summary["by_window"]["1m"]["neutral"] == 1


# ── Return averaging ────────────────────────────────────────────────────────

def test_avg_spy_return(_isolated_output):
    """Average SPY return is computed correctly."""
    entries = [
        _make_log_entry(spy_return=1.0),
        _make_log_entry(spy_return=-0.5),
    ]
    summary = build_summary(entries)
    assert summary["summary"]["avg_spy_return_pct"] == pytest.approx(0.25)


def test_avg_returns_per_asset(_isolated_output):
    """HYG and TLT averages are tracked separately."""
    entries = [
        _make_log_entry(hyg_return=0.3, tlt_return=-0.1),
        _make_log_entry(hyg_return=0.5, tlt_return=0.2),
    ]
    summary = build_summary(entries)
    assert summary["summary"]["avg_hyg_return_pct"] == pytest.approx(0.4)
    assert summary["summary"]["avg_tlt_return_pct"] == pytest.approx(0.05)


def test_null_returns_excluded(_isolated_output):
    """None returns are excluded from averages."""
    entries = [
        _make_log_entry(spy_return=1.0),
        _make_log_entry(spy_return=None),
    ]
    summary = build_summary(entries)
    assert summary["summary"]["avg_spy_return_pct"] == pytest.approx(1.0)


# ── Overall summary ─────────────────────────────────────────────────────────

def test_overall_counts(_isolated_output):
    """Overall summary aggregates all sources and windows."""
    entries = [
        _make_log_entry(source="judgment_layer", window="1d", outcome="correct"),
        _make_log_entry(source="trade_decision_layer", window="1w", outcome="incorrect"),
        _make_log_entry(source="judgment_layer", window="1m", outcome="neutral"),
    ]
    summary = build_summary(entries)
    assert summary["summary"]["total"] == 3
    assert summary["summary"]["correct"] == 1
    assert summary["summary"]["incorrect"] == 1
    assert summary["summary"]["neutral"] == 1


# ── Write outputs ───────────────────────────────────────────────────────────

def test_write_creates_files(_isolated_output):
    """write_outputs creates JSON and markdown files."""
    eval_dir, output_dir = _isolated_output
    entries = [_make_log_entry()]
    summary = build_summary(entries)
    paths = write_outputs(summary)

    assert paths["json"].exists()
    assert paths["markdown"].exists()

    loaded = json.loads(paths["json"].read_text())
    assert loaded["schema_version"] == "calibration_summary.v1"
    assert loaded["total_evaluations"] == 1


def test_markdown_contains_key_sections(_isolated_output):
    """Markdown output has expected sections."""
    eval_dir, output_dir = _isolated_output
    entries = [_make_log_entry()]
    summary = build_summary(entries)
    paths = write_outputs(summary)

    md = paths["markdown"].read_text()
    assert "# Calibration Summary" in md
    assert "## Overall" in md
    assert "## By Source" in md
    assert "## By Window" in md
    assert "judgment_layer" in md


# ── Roundtrip ───────────────────────────────────────────────────────────────

def test_full_pipeline(_isolated_output):
    """Full pipeline: write log → load → aggregate → write summary."""
    eval_dir, output_dir = _isolated_output
    entries = [
        _make_log_entry(source="judgment_layer", decision="NO_TRADE", window="1d", outcome="correct", spy_return=-0.5),
        _make_log_entry(source="judgment_layer", decision="NO_TRADE", window="1w", outcome="correct", spy_return=-1.2),
        _make_log_entry(source="trade_decision_layer", decision="WATCH_ONLY", window="1d", outcome="neutral", spy_return=0.1),
    ]
    _write_eval_log(eval_dir, entries)

    loaded = load_eval_log()
    assert len(loaded) == 3

    summary = build_summary(loaded)
    assert summary["total_evaluations"] == 3
    assert summary["by_source"]["judgment_layer"]["NO_TRADE"]["correct"] == 2

    paths = write_outputs(summary)
    assert paths["json"].exists()
    reloaded = json.loads(paths["json"].read_text())
    assert reloaded["total_evaluations"] == 3
