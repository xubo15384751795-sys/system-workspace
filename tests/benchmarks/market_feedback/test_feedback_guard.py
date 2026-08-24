"""Guard tests for executor diagnostics and Learning Hub admission."""

from __future__ import annotations

import json

from benchmarks.market_feedback import benchmark_gate, metrics_collector


def test_blocked_executor_metrics_become_inconclusive(tmp_path, monkeypatch) -> None:
    benchmark_id = "blocked"
    benchmark_dir = tmp_path / benchmark_id
    output_dir = benchmark_dir / "qlib_output"
    output_dir.mkdir(parents=True)
    (output_dir / "raw_metrics.json").write_text(
        json.dumps(
            {
                "baseline": {
                    "rank_ic": 0.02,
                    "rank_icir": 0.4,
                    "sharpe": 1.0,
                    "max_drawdown": -0.1,
                    "annual_return": 0.1,
                    "information_ratio": 1.0,
                    "feedback_blocked": False,
                },
                "treatment": {
                    "rank_ic": 0.02,
                    "rank_icir": 0.4,
                    "sharpe": 1.0,
                    "max_drawdown": -0.1,
                    "annual_return": 0.1,
                    "information_ratio": 1.0,
                    "feedback_blocked": True,
                    "feedback_block_reasons": ["deformation_features_not_integrated"],
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(metrics_collector, "BENCHMARKS_ROOT", tmp_path)

    result = metrics_collector.collect_metrics(benchmark_id)

    assert result["status"] == "inconclusive"
    summary = json.loads((benchmark_dir / "feedback" / "metrics_summary.json").read_text())
    assert summary["feedback_blocked_experiments"][0]["experiment"] == "treatment"


def test_inconclusive_feedback_cannot_enter_learning_hub(tmp_path, monkeypatch) -> None:
    benchmark_id = "inconclusive"
    benchmark_dir = tmp_path / benchmark_id
    for artifact in benchmark_gate.REQUIRED_ARTIFACTS:
        path = benchmark_dir / artifact
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    (benchmark_dir / "isolation_audit.json").write_text(
        json.dumps({"isolation_status": "passed"}), encoding="utf-8"
    )
    (benchmark_dir / "feedback" / "feedback_decision.json").write_text(
        json.dumps({"feedback_type": "inconclusive"}), encoding="utf-8"
    )
    monkeypatch.setattr(benchmark_gate, "BENCHMARKS_ROOT", tmp_path)

    result = benchmark_gate.check_benchmark_gate(benchmark_id)

    assert result["feedback_usable"] is False
    assert result["gate_passed"] is False
