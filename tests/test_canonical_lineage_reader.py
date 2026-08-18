"""Reader-level dual-read contract for SYS-21 canonical lineage context."""
from __future__ import annotations

import json
from pathlib import Path

from scripts import _notify, daily_run
from system_runtime.canonical_lineage import summarize_step_lineage


def _chain() -> dict:
    return json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "tests"
            / "fixtures"
            / "canonical_chain_parity.json"
        ).read_text(encoding="utf-8")
    )


def test_reader_reports_match_without_granting_authority() -> None:
    chain = _chain()
    ids = {
        "schema_version": chain["schema_version"],
        "observation_id": chain["observation"]["observation_id"],
        "measurement_id": chain["measurement"]["measurement_id"],
        "evidence_id": chain["evidence"]["evidence_id"],
        "claim_id": chain["claim"]["claim_id"],
    }

    result = summarize_step_lineage(
        [
            {
                "step": "neutral_pressure_measurement",
                "status": "success",
                "canonical_chain": chain,
                "canonical_ids": ids,
            }
        ],
        run_id="run-1",
    )

    assert result["status"] == "MATCH"
    assert result["authority"] == "shadow_only"
    assert result["promotion_allowed"] is False
    assert result["run_id"] == "run-1"


def test_reader_surfaces_id_chain_mismatch_without_blocking_publish() -> None:
    chain = _chain()
    ids = {
        "schema_version": chain["schema_version"],
        "observation_id": chain["observation"]["observation_id"],
        "measurement_id": "mea_wrong",
        "evidence_id": chain["evidence"]["evidence_id"],
        "claim_id": chain["claim"]["claim_id"],
    }

    result = summarize_step_lineage(
        [
            {
                "step": "neutral_pressure_measurement",
                "status": "success",
                "canonical_chain": chain,
                "canonical_ids": ids,
            }
        ],
        run_id="run-1",
    )

    assert result["status"] == "PARITY_MISMATCH"
    assert result["promotion_allowed"] is False
    assert result["violations"] == [
        "neutral_pressure_measurement:canonical_ids_chain_mismatch"
    ]


def test_reader_ignores_failed_and_unstamped_steps() -> None:
    chain = _chain()
    ids = {
        "schema_version": chain["schema_version"],
        "observation_id": chain["observation"]["observation_id"],
        "measurement_id": chain["measurement"]["measurement_id"],
        "evidence_id": chain["evidence"]["evidence_id"],
        "claim_id": chain["claim"]["claim_id"],
    }

    result = summarize_step_lineage(
        [
            {
                "step": "failed_step",
                "status": "failed",
                "canonical_chain": chain,
                "canonical_ids": ids,
            },
            {
                "step": "unstamped_step",
                "status": "success",
            },
        ],
        run_id="run-1",
    )

    assert result["status"] == "UNAVAILABLE"
    assert result["entry_count"] == 0


def test_alert_and_notification_read_the_same_shadow_context(tmp_path, monkeypatch) -> None:
    chain = _chain()
    ids = {
        "schema_version": chain["schema_version"],
        "observation_id": chain["observation"]["observation_id"],
        "measurement_id": chain["measurement"]["measurement_id"],
        "evidence_id": chain["evidence"]["evidence_id"],
        "claim_id": chain["claim"]["claim_id"],
    }
    steps = [
        {
            "step": "neutral_pressure_measurement",
            "status": "failed",
            "canonical_chain": chain,
            "canonical_ids": ids,
        }
    ]
    context = summarize_step_lineage(steps, run_id="run-1")
    daily_run.write_alert(
        ["fixture warning"],
        steps,
        output_root=tmp_path,
        outcome={"run_id": "run-1", "exit_code": 3},
    )
    alert = json.loads(
        (tmp_path / "alerts" / "latest_alert.json").read_text(encoding="utf-8")
    )
    assert alert["canonical_lineage"] == context

    calls: list[str] = []
    monkeypatch.setattr(
        _notify,
        "notify_deviations",
        lambda _title, deviations, **_kwargs: calls.append("; ".join(deviations)) or True,
    )
    _notify.notify_daily_run_result(
        status="partial_failure",
        failed_steps=["neutral_pressure_measurement"],
        warnings=[],
        outcome={"run_id": "run-1", "exit_code": 3},
        canonical_lineage=context,
    )
    assert calls and "canonical_lineage=UNAVAILABLE" in calls[0]
