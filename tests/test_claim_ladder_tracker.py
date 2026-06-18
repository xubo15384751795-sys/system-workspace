"""Claim Ladder Tracker — tests for cross-run claim progression.

Verifies that claim ladder tracker correctly evaluates M/D persistence,
CaseLab improvement, HMM conflict, and invalidation across runs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from claim_ladder_tracker import (
    check_caselab_improvement,
    check_hmm_conflict,
    check_invalidation,
    check_md_persistence,
    evaluate_progression,
    find_previous_run_dir,
    load_previous_pending,
)


@pytest.fixture(autouse=True)
def _isolated_dirs(tmp_path, monkeypatch):
    """Redirect I/O to temp directory."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    output_dir = tmp_path / "claim_ladder"
    caselab_dir = tmp_path / "caselab"
    caselab_dir.mkdir(parents=True, exist_ok=True)
    hmm_dir = tmp_path / "ml_signals" / "latest"
    hmm_dir.mkdir(parents=True)
    judgment_dir = tmp_path / "judgment"
    judgment_dir.mkdir()

    monkeypatch.setattr("claim_ladder_tracker.RUNS_DIR", runs_dir)
    monkeypatch.setattr("claim_ladder_tracker.OUTPUT_DIR", output_dir)
    monkeypatch.setattr("claim_ladder_tracker.CASELAB_DIR", caselab_dir)
    monkeypatch.setattr("claim_ladder_tracker.HMM_PATH", hmm_dir / "regime_hmm.json")
    monkeypatch.setattr("claim_ladder_tracker.JUDGMENT_PATH", judgment_dir / "latest.json")
    return runs_dir, output_dir, caselab_dir, hmm_dir, judgment_dir


def _make_run(runs_dir: Path, run_id: str, status: str = "success", pending_items=None):
    """Create a mock run bundle."""
    run_dir = runs_dir / run_id
    run_dir.mkdir(exist_ok=True)
    (run_dir / "manifest.json").write_text(json.dumps({"status": status}))
    if pending_items is not None:
        (run_dir / "feedback_pending.json").write_text(json.dumps(pending_items))
    return run_dir


def _make_claim_item(hypothesis="stress_relief in M/D", tier=1, gap=0.12):
    return {
        "item": f"Claim ladder: tier={tier} — {hypothesis}",
        "source": "claim_ladder",
        "validation_type": "claim_verification",
        "priority": "high",
        "metadata": {
            "claim_tier": tier,
            "claim_label": "mechanism_hypothesis",
            "mechanism_hypothesis": hypothesis,
            "watch_conditions": ["M persists"],
            "invalidation_conditions": ["M reverses sign"],
            "caselab_score_gap": gap,
            "md_persistence_requirement": "persisted >= 2 runs",
        },
    }


def _make_judgment(meaning=None, gate_status=None):
    return {
        "decision": "WATCH_ONLY",
        "meaning": meaning or ["M=-2.09 stress building, D=-0.76"],
        "claim_ladder": {"tier": 1, "label": "mechanism_hypothesis"},
        "gate_status": gate_status or {},
    }


# ── find_previous_run_dir ───────────────────────────────────────────────────

def test_find_previous_run_dir(_isolated_dirs):
    runs_dir = _isolated_dirs[0]
    _make_run(runs_dir, "run_1", "success")
    _make_run(runs_dir, "run_2", "running")  # not complete
    found = find_previous_run_dir()
    assert found is not None
    assert found.name == "run_1"


def test_find_previous_run_dir_none(_isolated_dirs):
    assert find_previous_run_dir() is None


# ── check_md_persistence ────────────────────────────────────────────────────

def test_md_persistence_confirmed(_isolated_dirs):
    item = _make_claim_item("stress_relief in M/D values")
    judgment = _make_judgment(meaning=["M shows stress relief pattern"])
    result = check_md_persistence(item, judgment)
    assert result["persisted"] is True
    assert result["status"] == "confirmed"


def test_md_persistence_reversed(_isolated_dirs):
    item = _make_claim_item("stress_relief in M/D values")
    judgment = _make_judgment(meaning=["M shows stress building pattern"])
    result = check_md_persistence(item, judgment)
    assert result["persisted"] is False
    assert result["status"] == "reversed"


# ── check_caselab_improvement ───────────────────────────────────────────────

def test_caselab_improvement_no_data(_isolated_dirs):
    item = _make_claim_item(gap=0.15)
    result = check_caselab_improvement(item)
    # No CaseLab file → gap unchanged → stable
    assert result["status"] == "stable"


def test_caselab_improvement_with_data(_isolated_dirs, tmp_path, monkeypatch):
    caselab_dir = _isolated_dirs[2]
    caselab_dir.mkdir(parents=True, exist_ok=True)
    import datetime as _dt
    today = _dt.date.today().isoformat()
    caselab = {"match_quality": {"top_score": 0.50, "thresholds": {"usable": 0.55}}}
    (caselab_dir / f"{today}.json").write_text(json.dumps(caselab))

    item = _make_claim_item(gap=0.15)  # previous gap was 0.15
    result = check_caselab_improvement(item)
    assert result["current_gap"] == pytest.approx(0.05)
    assert result["improved"] is True
    assert result["status"] == "improved"


# ── check_hmm_conflict ─────────────────────────────────────────────────────

def test_hmm_conflict_no_data(_isolated_dirs):
    item = _make_claim_item("stress_relief")
    result = check_hmm_conflict(item)
    assert result["status"] == "no_data"


def test_hmm_conflict_detected(_isolated_dirs):
    hmm_dir = _isolated_dirs[3]
    (hmm_dir / "regime_hmm.json").write_text(json.dumps({"regime": "volatile"}))

    item = _make_claim_item("stress_relief hypothesis")
    result = check_hmm_conflict(item)
    assert result["conflict"] is True
    assert result["status"] == "conflict"


def test_hmm_aligned(_isolated_dirs):
    hmm_dir = _isolated_dirs[3]
    (hmm_dir / "regime_hmm.json").write_text(json.dumps({"regime": "volatile"}))

    item = _make_claim_item("stress_building hypothesis")
    result = check_hmm_conflict(item)
    assert result["conflict"] is False
    assert result["status"] == "aligned"


# ── check_invalidation ──────────────────────────────────────────────────────

def test_invalidation_no_conditions(_isolated_dirs):
    item = {"metadata": {"invalidation_conditions": []}}
    judgment = _make_judgment()
    result = check_invalidation(item, judgment)
    assert result["status"] == "no_conditions"


def test_invalidation_triggered_hmm(_isolated_dirs):
    item = _make_claim_item()
    item["metadata"]["invalidation_conditions"] = ["HMM stability degrades"]
    judgment = _make_judgment(gate_status={"hmm_stability": "WEAK"})
    result = check_invalidation(item, judgment)
    assert len(result["triggered"]) == 1
    assert result["status"] == "triggered"


def test_invalidation_not_triggered(_isolated_dirs):
    item = _make_claim_item()
    judgment = _make_judgment(gate_status={"hmm_stability": "ADEQUATE"})
    result = check_invalidation(item, judgment)
    assert len(result["triggered"]) == 0
    assert result["status"] == "not_triggered"


# ── evaluate_progression ────────────────────────────────────────────────────

def test_evaluate_progression_tracking(_isolated_dirs):
    items = [_make_claim_item("stress_relief hypothesis")]
    judgment = _make_judgment(meaning=["M shows stress relief pattern"])
    results = evaluate_progression(items, judgment)
    assert len(results) == 1
    assert results[0]["overall_status"] in ("tracking", "progressing")


def test_evaluate_progression_invalidated(_isolated_dirs):
    hmm_dir = _isolated_dirs[3]
    (hmm_dir / "regime_hmm.json").write_text(json.dumps({"regime": "stress"}))

    items = [_make_claim_item("stress_building hypothesis")]
    items[0]["metadata"]["invalidation_conditions"] = ["M reverses sign"]
    judgment = _make_judgment(
        meaning=["M shows stress relief pattern"],
        gate_status={"hmm_stability": "WEAK"},
    )
    results = evaluate_progression(items, judgment)
    assert len(results) == 1
    # Should be invalidated or reversed
    assert results[0]["overall_status"] in ("invalidated", "reversed")


def test_evaluate_progression_empty(_isolated_dirs):
    results = evaluate_progression([], _make_judgment())
    assert results == []


# ── load_previous_pending ──────────────────────────────────────────────────

def test_load_previous_pending(_isolated_dirs):
    runs_dir = _isolated_dirs[0]
    items = [_make_claim_item()]
    run_dir = _make_run(runs_dir, "test_run", pending_items=items)
    loaded = load_previous_pending(run_dir)
    assert len(loaded) == 1
    assert loaded[0]["source"] == "claim_ladder"


def test_load_previous_pending_missing(_isolated_dirs):
    runs_dir = _isolated_dirs[0]
    run_dir = runs_dir / "empty_run"
    run_dir.mkdir()
    loaded = load_previous_pending(run_dir)
    assert loaded == []
