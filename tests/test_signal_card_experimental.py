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
    monkeypatch.setattr(sc, "SHADOW_OUTCOMES", tmp_path / "missing.json")

    section = _build_experimental_validation()
    assert section["can_affect_core_judgment"] is False
    assert section["walk_forward"]["best_channel"] == "K"
