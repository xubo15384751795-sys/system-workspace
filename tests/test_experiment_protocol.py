"""Tests for the engine-neutral Experiment Protocol boundary."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from benchmarks.experiment_protocol import (
    build_result_artifact,
    load_registry,
    load_spec,
    spec_sha256,
    validate_result,
    validate_spec,
)
from benchmarks.market_feedback import benchmark_gate, metrics_collector
from benchmarks.market_feedback.qlib_job_spec import generate_job_spec
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]


def _spec() -> dict:
    return {
        "schema_version": "system.experiment_spec.v1",
        "experiment_id": "EXP-QLIB-LIQUIDITY-001",
        "research_question": "Does funding pressure explain forward equity drawdown risk?",
        "hypothesis": {
            "claim": "Higher funding pressure increases forward equity drawdown risk.",
            "variables": {"funding_pressure": "macro measurement"},
            "targets": ["forward_return_20d", "max_drawdown"],
            "expected_direction": "positive",
        },
        "engine": {
            "adapter": "qlib",
            "executor": "ExternalTools/qlib_benchmark_runner/run_qlib_benchmark.py",
            "mode": "isolated",
        },
        "dataset": {
            "release": "cross_asset_daily_panel@v1",
            "universe": ["SPY", "TLT"],
            "start_date": "2010-01-01",
            "end_date": "2025-12-31",
            "frequency": "daily",
            "features": ["price", "volume", "funding_pressure"],
            "label": "forward_return_20d",
            "point_in_time": True,
            "availability_policy": "official_release_time",
        },
        "models": [
            {"model_id": "baseline_alpha158", "config": "baseline.yaml", "role": "baseline"},
            {"model_id": "treatment_funding_pressure", "config": "treatment.yaml", "role": "treatment"},
        ],
        "evaluation": {
            "metrics": ["rank_ic", "sharpe", "max_drawdown"],
            "splits": {"train": "2010-2019", "test": "2020-2025"},
            "stability_checks": ["walk_forward", "regime_split"],
        },
        "governance": {
            "evidence_only": True,
            "judgment_authority": False,
            "isolation_required": True,
            "promotion_target": "candidate_evidence",
            "human_review_required": True,
        },
        "provenance": {
            "owner": "system",
            "created_at": "2026-08-24T00:00:00Z",
            "source_refs": ["cross_asset_daily_panel@v1"],
        },
    }


def _raw_metrics(*, blocked: bool = False) -> dict:
    return {
        "baseline": {"rank_ic": 0.02, "sharpe": 1.0, "feedback_blocked": False},
        "treatment": {
            "rank_ic": 0.03,
            "sharpe": 1.1,
            "feedback_blocked": blocked,
            "feedback_block_reasons": ["deformation_features_not_integrated"] if blocked else [],
        },
    }


def test_spec_and_registry_validate() -> None:
    spec = _spec()

    assert validate_spec(spec) == []
    assert len(spec_sha256(spec)) == 64

    invalid = copy.deepcopy(spec)
    invalid["governance"]["judgment_authority"] = True
    assert any("judgment_authority" in error for error in validate_spec(invalid))

    registry = load_registry()
    assert registry["adapters"]["qlib"]["communication"] == "file_interface_subprocess"
    assert registry["policy"]["judgment_write_allowed"] is False

    spec_relpath = registry["experiments"][0]["spec_path"]
    assert spec_relpath.startswith("governance/experiments/")
    spec_path = ROOT / spec_relpath
    assert spec_path.is_file()
    assert spec_path.parent != ROOT / "governance"
    real_spec = load_spec(spec_path)
    assert real_spec["governance"]["judgment_authority"] is False
    assert real_spec["governance"]["evidence_only"] is True

    unknown_adapter = copy.deepcopy(spec)
    unknown_adapter["engine"]["adapter"] = "unregistered-engine"
    with pytest.raises(ValueError, match="not active in the registry"):
        generate_job_spec("unregistered", experiment_spec=unknown_adapter)


def test_protocol_schemas_are_well_formed() -> None:
    for name in (
        "experiment_spec.schema.json",
        "experiment_result.schema.json",
        "experiment_registry.schema.json",
    ):
        schema = json.loads((ROOT / "protocols" / name).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)


def test_blocked_result_is_inconclusive_and_not_promotable() -> None:
    result = build_result_artifact(
        _spec(),
        _raw_metrics(blocked=True),
        input_artifacts=[{"path": "sandbox_input/panel.parquet", "role": "dataset"}],
    )

    assert validate_result(result) == []
    assert result["status"] == "inconclusive"
    assert result["evidence"]["verdict"] == "inconclusive"
    assert result["governance"]["feedback_usable"] is False
    assert result["governance"]["promotion_eligible"] is False


def test_protocol_spec_flows_through_qlib_job_and_gate(tmp_path, monkeypatch) -> None:
    benchmark_id = "protocol-backed"
    benchmark_dir = tmp_path / benchmark_id
    output_dir = benchmark_dir / "qlib_output"
    output_dir.mkdir(parents=True)
    (benchmark_dir / "qlib_job_spec.json").write_text(
        json.dumps(generate_job_spec(benchmark_id, experiment_spec=_spec())),
        encoding="utf-8",
    )
    (output_dir / "raw_metrics.json").write_text(json.dumps(_raw_metrics()), encoding="utf-8")

    monkeypatch.setattr(metrics_collector, "BENCHMARKS_ROOT", tmp_path)
    collected = metrics_collector.collect_metrics(benchmark_id)

    assert collected["status"] == "collected"
    result_path = benchmark_dir / "experiment_result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert validate_result(result) == []
    assert result["governance"]["feedback_usable"] is True

    for artifact in benchmark_gate.REQUIRED_ARTIFACTS:
        path = benchmark_dir / artifact
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}", encoding="utf-8")
    (benchmark_dir / "isolation_audit.json").write_text(
        json.dumps({"isolation_status": "passed"}), encoding="utf-8"
    )
    (benchmark_dir / "feedback" / "feedback_decision.json").write_text(
        json.dumps({"feedback_type": "positive_increment"}), encoding="utf-8"
    )

    monkeypatch.setattr(benchmark_gate, "BENCHMARKS_ROOT", tmp_path)
    gate = benchmark_gate.check_benchmark_gate(benchmark_id)

    assert gate["experiment_protocol_backed"] is True
    assert gate["experiment_result_artifact_valid"] is True
    assert gate["gate_passed"] is True
