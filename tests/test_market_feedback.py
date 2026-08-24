"""Market feedback path and contract-boundary tests."""
from __future__ import annotations

import json

from scripts import market_feedback as feedback


def _write_qlib_decision(root, benchmark_id: str, generated_at: str, rank_ic_delta: float) -> None:
    path = (
        root
        / "Output"
        / "benchmarks"
        / "market_feedback"
        / benchmark_id
        / "feedback"
        / "feedback_decision.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "benchmark_id": benchmark_id,
                "feedback_type": "positive_increment",
                "summary": "test",
                "metric_deltas": {"rank_ic_delta": rank_ic_delta},
                "recommended_action": ["review"],
                "generated_at": generated_at,
            }
        ),
        encoding="utf-8",
    )


def test_reads_newest_workbench_qlib_feedback_and_adapts(tmp_path, monkeypatch) -> None:
    _write_qlib_decision(tmp_path, "old", "2026-08-23T00:00:00+00:00", 0.01)
    _write_qlib_decision(tmp_path, "new", "2026-08-24T00:00:00+00:00", 0.02)
    monkeypatch.setattr(feedback, "ROOT", tmp_path)

    result = feedback.read_qlib_feedback()

    assert result is not None
    assert result["schema_version"] == "market_feedback.v1"
    assert result["feedback_type"] == "qlib_benchmark"
    assert result["benchmark_id"] == "new"
    assert result["details"][0]["metric"] == "rank_ic_delta"


def test_missing_qlib_feedback_is_explicitly_diagnosed(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(feedback, "ROOT", tmp_path)
    monkeypatch.setattr(feedback, "read_calibration_feedback", lambda: None)

    result = feedback.build_market_feedback()

    assert result["source"] == "none"
    assert result["diagnostics"]["qlib_feedback"]["status"] == "missing"
