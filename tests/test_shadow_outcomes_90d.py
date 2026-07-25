"""Tests for Strategy Lab 90-day shadow outcomes aggregation."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from scripts.strategy_lab.shadow_card import (
    build_90d_outcomes_summary,
    save_90d_outcomes_summary,
)


def test_build_90d_outcomes_summary_counts_evaluations(tmp_path, monkeypatch) -> None:
    from scripts import _runtime_io as rio
    from scripts.strategy_lab import shadow_card as sc

    out_dir = tmp_path / "Output" / "strategy_lab" / "shadow_cards"
    out_dir.mkdir(parents=True)
    today = datetime.now(UTC).date()
    d1 = (today - timedelta(days=10)).isoformat()
    d2 = (today - timedelta(days=5)).isoformat()

    for date_str, evaluation, fwd20 in (
        (d1, "correct", 0.01),
        (d2, "wrong", -0.03),
    ):
        card = {
            "as_of_date": date_str,
            "recommendation": {"allow_open": False},
            "outcome_backfill": {
                "forward_20d_return": fwd20,
                "evaluation": evaluation,
            },
        }
        (out_dir / f"{date_str}.json").write_text(json.dumps(card), encoding="utf-8")

    monkeypatch.setattr(rio, "ROOT", tmp_path)
    monkeypatch.setattr(sc, "OUTPUT_DIR", tmp_path / "Output" / "strategy_lab")

    summary = build_90d_outcomes_summary(days=90)
    assert summary["cards_total"] == 2
    assert summary["cards_with_20d_outcome"] == 2
    assert summary["evaluation_counts"]["correct"] == 1
    assert summary["correct_rate"] == 0.5

    path = save_90d_outcomes_summary(summary)
    assert path.exists()
