"""Tests for the read-only orchestration canonical-lineage bridge."""
from __future__ import annotations

import json
from pathlib import Path

from orchestration.canonical_lineage import attach_output_lineage, read_output_lineage


ROOT = Path(__file__).resolve().parents[3]


def _fixture() -> dict:
    return json.loads(
        (ROOT / "tests" / "fixtures" / "canonical_chain_parity.json").read_text(
            encoding="utf-8"
        )
    )


def test_current_run_chain_is_attached_additively(tmp_path, monkeypatch) -> None:
    run_id = "shadow-run-001"
    payload = {"run_id": run_id, "canonical_chain": _fixture()}
    monkeypatch.setenv("CURRENT_OUTPUT_DIR", str(tmp_path))
    (tmp_path / "neutral_pressure_snapshot.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )

    result = {"step": "neutral_pressure_measurement", "status": "success"}
    attach_output_lineage(
        result,
        ["Output/current/neutral_pressure_snapshot.json"],
        run_id=run_id,
    )

    assert result["canonical_ids"]["observation_id"].startswith("obs_")
    assert result["canonical_ids"]["claim_id"].startswith("clm_")
    assert result["canonical_source_path"].endswith("neutral_pressure_snapshot.json")
    assert result["status"] == "success"


def test_prior_run_chain_is_not_attached_to_current_result(tmp_path, monkeypatch) -> None:
    payload = {"run_id": "old-run", "canonical_chain": _fixture()}
    monkeypatch.setenv("CURRENT_OUTPUT_DIR", str(tmp_path))
    (tmp_path / "neutral_pressure_snapshot.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )

    result = {"step": "neutral_pressure_measurement", "status": "success"}
    assert (
        read_output_lineage(
            ["Output/current/neutral_pressure_snapshot.json"],
            run_id="new-run",
        )
        is None
    )
    assert "canonical_ids" not in result


def test_failed_step_never_adopts_existing_lineage(tmp_path, monkeypatch) -> None:
    payload = {"run_id": "failed-run", "canonical_chain": _fixture()}
    monkeypatch.setenv("CURRENT_OUTPUT_DIR", str(tmp_path))
    (tmp_path / "neutral_pressure_snapshot.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )

    result = {"step": "neutral_pressure_measurement", "status": "failed"}
    attach_output_lineage(
        result,
        ["Output/current/neutral_pressure_snapshot.json"],
        run_id="failed-run",
    )
    assert "canonical_ids" not in result
