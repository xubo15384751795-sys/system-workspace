"""Module Contribution Report — tests for effectiveness aggregation.

Verifies that eval_log.jsonl entries are correctly aggregated by
contributing module with hit rates and effectiveness grades.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_module_contribution_report import (
    aggregate_by_module,
    build_report,
    load_eval_log,
    write_outputs,
)


@pytest.fixture(autouse=True)
def _isolated_output(tmp_path, monkeypatch):
    """Redirect file I/O to temp directory."""
    eval_dir = tmp_path / "evaluations"
    eval_dir.mkdir()
    output_dir = tmp_path / "calibration_summary"
    monkeypatch.setattr("build_module_contribution_report.EVAL_LOG_PATH", eval_dir / "eval_log.jsonl")
    monkeypatch.setattr("build_module_contribution_report.OUTPUT_DIR", output_dir)
    return eval_dir, output_dir


def _make_entry(
    modules=None,
    outcome="correct",
    spy_return=-0.5,
    window="1d",
    decision="NO_TRADE",
    source="judgment_layer",
):
    return {
        "eval_id": f"eval_2026-06-02_test",
        "source": source,
        "contributing_modules": modules or ["Workbench"],
        "window": window,
        "evaluated_at": "2026-06-03T00:00:00Z",
        "decision": decision,
        "confidence": "low",
        "returns": {"SPY": spy_return, "HYG": -0.2, "TLT": 0.3},
        "outcome": outcome,
    }


def _write_eval_log(eval_dir: Path, entries: list[dict]):
    log_path = eval_dir / "eval_log.jsonl"
    with log_path.open("w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


# ── Empty ────────────────────────────────────────────────────────────────────

def test_empty_log(_isolated_output):
    """No entries → empty report."""
    report = build_report([])
    assert report["total_evaluations"] == 0
    assert report["modules"] == []


# ── Single module ────────────────────────────────────────────────────────────

def test_single_module_aggregation(_isolated_output):
    """Entries for one module aggregate correctly."""
    entries = [
        _make_entry(modules=["Workbench"], outcome="correct"),
        _make_entry(modules=["Workbench"], outcome="correct"),
        _make_entry(modules=["Workbench"], outcome="incorrect"),
    ]
    modules = aggregate_by_module(entries)
    assert len(modules) == 1
    wb = modules[0]
    assert wb["module"] == "Workbench"
    assert wb["total_contributions"] == 3
    assert wb["correct"] == 2
    assert wb["incorrect"] == 1
    assert wb["hit_rate"] == pytest.approx(2 / 3, abs=0.001)


# ── Multi module ─────────────────────────────────────────────────────────────

def test_multi_module_separate(_isolated_output):
    """Different modules are tracked separately."""
    entries = [
        _make_entry(modules=["Workbench", "ML Signals"], outcome="correct"),
        _make_entry(modules=["Workbench"], outcome="incorrect"),
        _make_entry(modules=["ML Signals"], outcome="correct"),
    ]
    modules = aggregate_by_module(entries)
    by_name = {m["module"]: m for m in modules}

    # Workbench: 2 contributions (1 correct, 1 incorrect)
    assert by_name["Workbench"]["total_contributions"] == 2
    assert by_name["Workbench"]["correct"] == 1
    assert by_name["Workbench"]["incorrect"] == 1

    # ML Signals: 2 contributions (both correct)
    assert by_name["ML Signals"]["total_contributions"] == 2
    assert by_name["ML Signals"]["correct"] == 2


def test_shared_contribution(_isolated_output):
    """Entry with multiple modules credits all of them."""
    entries = [
        _make_entry(modules=["Workbench", "ML Signals", "CaseLab Context"], outcome="correct"),
    ]
    modules = aggregate_by_module(entries)
    assert len(modules) == 3
    for mod in modules:
        assert mod["total_contributions"] == 1
        assert mod["correct"] == 1


# ── Grading ──────────────────────────────────────────────────────────────────

def test_grade_a(_isolated_output):
    """High hit rate with enough volume → grade A."""
    entries = [_make_entry(outcome="correct") for _ in range(5)]
    entries.append(_make_entry(outcome="incorrect"))
    modules = aggregate_by_module(entries)
    assert modules[0]["grade"] == "A"


def test_grade_d(_isolated_output):
    """Low hit rate → grade D."""
    entries = [_make_entry(outcome="incorrect") for _ in range(5)]
    entries.append(_make_entry(outcome="correct"))
    modules = aggregate_by_module(entries)
    assert modules[0]["grade"] == "D"


def test_insufficient_data(_isolated_output):
    """Fewer than 3 evaluations → insufficient_data."""
    entries = [_make_entry(outcome="correct"), _make_entry(outcome="correct")]
    modules = aggregate_by_module(entries)
    assert modules[0]["grade"] == "insufficient_data"


# ── Window and decision breakdown ────────────────────────────────────────────

def test_by_window_tracking(_isolated_output):
    """Window distribution is tracked per module."""
    entries = [
        _make_entry(window="1d", outcome="correct"),
        _make_entry(window="1w", outcome="correct"),
        _make_entry(window="1m", outcome="neutral"),
    ]
    modules = aggregate_by_module(entries)
    assert modules[0]["by_window"]["1d"] == 1
    assert modules[0]["by_window"]["1w"] == 1
    assert modules[0]["by_window"]["1m"] == 1


def test_by_decision_tracking(_isolated_output):
    """Decision distribution is tracked per module."""
    entries = [
        _make_entry(decision="NO_TRADE", outcome="correct"),
        _make_entry(decision="WATCH_ONLY", outcome="neutral"),
    ]
    modules = aggregate_by_module(entries)
    assert modules[0]["by_decision"]["NO_TRADE"] == 1
    assert modules[0]["by_decision"]["WATCH_ONLY"] == 1


# ── Return averaging ────────────────────────────────────────────────────────

def test_avg_spy_return_per_module(_isolated_output):
    """Average SPY return is computed per module."""
    entries = [
        _make_entry(spy_return=1.0, outcome="correct"),
        _make_entry(spy_return=-0.5, outcome="incorrect"),
    ]
    modules = aggregate_by_module(entries)
    assert modules[0]["avg_spy_return_pct"] == pytest.approx(0.25)


# ── Sorting ─────────────────────────────────────────────────────────────────

def test_sorted_by_contributions(_isolated_output):
    """Modules are sorted by total contributions descending."""
    entries = [
        _make_entry(modules=["CaseLab Context"], outcome="correct"),
        _make_entry(modules=["Workbench"], outcome="correct"),
        _make_entry(modules=["Workbench"], outcome="correct"),
        _make_entry(modules=["Workbench"], outcome="correct"),
    ]
    modules = aggregate_by_module(entries)
    assert modules[0]["module"] == "Workbench"
    assert modules[1]["module"] == "CaseLab Context"


# ── Write outputs ────────────────────────────────────────────────────────────

def test_write_creates_files(_isolated_output):
    """write_outputs creates JSON and markdown."""
    entries = [_make_entry()]
    report = build_report(entries)
    paths = write_outputs(report)

    assert paths["json"].exists()
    assert paths["markdown"].exists()

    loaded = json.loads(paths["json"].read_text())
    assert loaded["schema_version"] == "module_contribution.v1"
    assert len(loaded["modules"]) == 1


def test_markdown_has_grades(_isolated_output):
    """Markdown output includes module grades."""
    entries = [_make_entry() for _ in range(5)]
    report = build_report(entries)
    paths = write_outputs(report)

    md = paths["markdown"].read_text()
    assert "# Module Contribution Effectiveness" in md
    assert "Workbench" in md
    assert "Grade" in md


# ── Full pipeline ────────────────────────────────────────────────────────────

def test_full_pipeline(_isolated_output):
    """End-to-end: write log → load → aggregate → report."""
    eval_dir, _ = _isolated_output
    entries = [
        _make_entry(modules=["Workbench", "ML Signals"], outcome="correct", window="1d"),
        _make_entry(modules=["Workbench"], outcome="incorrect", window="1w"),
        _make_entry(modules=["ML Signals"], outcome="correct", window="1d"),
        _make_entry(modules=["CaseLab Context"], outcome="neutral", window="1m"),
    ]
    _write_eval_log(eval_dir, entries)

    loaded = load_eval_log()
    assert len(loaded) == 4

    report = build_report(loaded)
    assert report["total_evaluations"] == 4
    assert len(report["modules"]) == 3

    paths = write_outputs(report)
    reloaded = json.loads(paths["json"].read_text())
    assert reloaded["total_evaluations"] == 4
