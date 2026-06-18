"""Tests for mechanism calibration gate evaluation."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from _mechanism_calibration_gate import evaluate_gate


def _report(
    episodes: list[dict],
    *,
    total: int | None = None,
) -> dict:
    return {
        "total_episodes": total if total is not None else len(episodes),
        "per_episode": episodes,
    }


def test_gate_none_when_holdout_fails() -> None:
    episodes = [
        {"id": "covid_2020", "dir_acc": 0.4, "mae": 1.2, "predicted": {"M": 1}, "actual": {"M": -1}},
        {"id": "svb_2023", "dir_acc": 0.5, "mae": 1.1, "predicted": {"M": 1}, "actual": {"M": -1}},
        {"id": "uk_pension_2022", "dir_acc": 0.5, "mae": 1.0, "predicted": {"M": 1}, "actual": {"M": -1}},
        {"id": "lehman_2008", "dir_acc": 0.8, "mae": 0.5, "predicted": {"M": 1}, "actual": {"M": 1}},
    ]
    policy = {
        "holdout_episode_ids": ["covid_2020", "svb_2023", "uk_pension_2022"],
        "levels": {
            "research": {
                "min_holdout_episodes": 3,
                "min_holdout_direction_accuracy": 0.55,
                "max_holdout_mean_absolute_error": 1.0,
                "min_per_dimension_direction_accuracy": 0.50,
            },
        },
    }
    gate = evaluate_gate(_report(episodes), policy)
    assert gate["achieved_level"] == "none"
    assert gate["allow_paper_export"] is False


def test_gate_research_when_holdout_passes() -> None:
    episodes = [
        {"id": "covid_2020", "dir_acc": 0.7, "mae": 0.8, "predicted": {"M": 1, "K": 1, "D": 1, "X": 1}, "actual": {"M": 1, "K": 1, "D": 1, "X": 1}},
        {"id": "svb_2023", "dir_acc": 0.6, "mae": 0.9, "predicted": {"M": 1, "K": 1, "D": 1, "X": 1}, "actual": {"M": 1, "K": 1, "D": 1, "X": 1}},
        {"id": "uk_pension_2022", "dir_acc": 0.65, "mae": 0.85, "predicted": {"M": 1, "K": 1, "D": 1, "X": 1}, "actual": {"M": 1, "K": 1, "D": 1, "X": 1}},
    ]
    policy = {
        "holdout_episode_ids": ["covid_2020", "svb_2023", "uk_pension_2022"],
        "levels": {
            "research": {
                "min_holdout_episodes": 3,
                "min_holdout_direction_accuracy": 0.55,
                "max_holdout_mean_absolute_error": 1.0,
                "min_per_dimension_direction_accuracy": 0.50,
            },
            "paper_draft": {
                "min_holdout_episodes": 3,
                "min_holdout_direction_accuracy": 0.99,
                "max_holdout_mean_absolute_error": 0.5,
                "min_per_dimension_direction_accuracy": 0.99,
                "min_total_episodes": 15,
            },
        },
    }
    gate = evaluate_gate(_report(episodes, total=16), policy)
    assert gate["achieved_level"] == "research"
    assert gate["allow_paper_export"] is False
