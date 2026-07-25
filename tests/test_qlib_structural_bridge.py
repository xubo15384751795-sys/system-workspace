"""Tests for Qlib ↔ structural bridge report."""
from __future__ import annotations

import json

from scripts.commands.weekly.build_qlib_structural_bridge import build_bridge_report


def test_build_bridge_report_with_experiment(tmp_path, monkeypatch) -> None:
    import _runtime_io as rio

    import scripts.commands.weekly.build_qlib_structural_bridge as bridge

    exp_dir = tmp_path / "Output" / "strategy_lab" / "qlib_experiment"
    exp_dir.mkdir(parents=True)
    (exp_dir / "lightgbm_experiment.json").write_text(
        json.dumps(
            {
                "baseline": {"auc": 0.52},
                "treatment": {"auc": 0.55},
                "delta": {"auc": 0.03},
                "n_test": 500,
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(rio, "ROOT", tmp_path)
    monkeypatch.setattr(bridge, "ROOT", tmp_path)
    monkeypatch.setattr(bridge, "QLIB_EXPERIMENT", exp_dir / "lightgbm_experiment.json")
    monkeypatch.setattr(bridge, "BACKTEST_RESULT", tmp_path / "missing.json")
    monkeypatch.setattr(bridge, "OUTPUT_PATH", tmp_path / "Output" / "validation" / "qlib_structural_bridge.json")

    report = build_bridge_report()
    assert report["can_affect_core_judgment"] is False
    assert report["experiment_summary"]["deformation_features_add_value"] is True
    assert report["bridge_verdict"] in {"positive", "review", "inconclusive"}
