"""Signal card experimental validation section tests."""
from __future__ import annotations

import json

from build_signal_card import _build_experimental_validation


def test_experimental_validation_includes_walk_forward(tmp_path, monkeypatch) -> None:
    import _runtime_io as rio
    import build_signal_card as sc

    validation = tmp_path / "Output" / "validation"
    validation.mkdir(parents=True)
    (validation / "walk_forward_report.json").write_text(
        json.dumps(
            {
                "status": "complete",
                "best_channel": "K",
                "best_direction_accuracy": 0.58,
                "channel_summaries": {"K": {"windows": 3}},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(rio, "ROOT", tmp_path)
    monkeypatch.setattr(sc, "ROOT", tmp_path)
    monkeypatch.setattr(sc, "VALIDATION", validation)
    monkeypatch.setattr(sc, "MARKET_FEEDBACK", tmp_path / "Output" / "market_feedback" / "feedback_decision.json")
    monkeypatch.setattr(sc, "SHADOW_OUTCOMES", tmp_path / "missing.json")

    section = _build_experimental_validation()
    assert section["can_affect_core_judgment"] is False
    assert section["walk_forward"]["best_channel"] == "K"
    assert section["qlib_structural_bridge"]["status"] == "missing"


def test_experimental_validation_reads_qlib_named_bridge_and_feedback(tmp_path, monkeypatch) -> None:
    import _runtime_io as rio
    import build_signal_card as sc

    validation = tmp_path / "Output" / "validation"
    validation.mkdir(parents=True)
    (validation / "qlib_structural_bridge.json").write_text(
        json.dumps(
            {
                "bridge_verdict": "positive",
                "experiment_summary": {"deformation_features_add_value": True},
                "backtest_summary": {"overlay_improves_sharpe": True},
                "anti_gaming_checks": [],
            }
        ),
        encoding="utf-8",
    )
    feedback_path = tmp_path / "Output" / "market_feedback" / "feedback_decision.json"
    feedback_path.parent.mkdir(parents=True)
    feedback_path.write_text(
        json.dumps(
            {
                "schema_version": "market_feedback.v1",
                "generated_at": "2026-08-24T00:00:00+00:00",
                "feedback_type": "qlib_benchmark",
                "qlib_feedback_type": "inconclusive",
                "source": "qlib",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(rio, "ROOT", tmp_path)
    monkeypatch.setattr(sc, "ROOT", tmp_path)
    monkeypatch.setattr(sc, "VALIDATION", validation)
    monkeypatch.setattr(sc, "MARKET_FEEDBACK", feedback_path)
    monkeypatch.setattr(sc, "SHADOW_OUTCOMES", tmp_path / "missing.json")

    section = _build_experimental_validation()
    assert section["qlib_structural_bridge"]["status"] == "available"
    assert section["qlib_structural_bridge"]["bridge_verdict"] == "positive"
    assert section["market_feedback"]["status"] == "available"
    assert section["market_feedback"]["source"] == "qlib"
    assert section["market_feedback"]["qlib_feedback_type"] == "inconclusive"
    assert section["market_feedback"]["feedback_usable"] is False
