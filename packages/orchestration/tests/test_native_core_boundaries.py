from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from dagster import materialize
from dagster._core.errors import DagsterAssetCheckFailedError

from orchestration.assets.native_core import (
    NATIVE_CORE_ASSETS,
    NATIVE_CORE_CHECKS,
    build_native_core_assets,
    build_native_core_checks,
    native_core_payload,
)
from orchestration.definitions import defs, native_core_pilot_job, native_core_pilot_schedule
from orchestration.native_core_boundaries import (
    NATIVE_CORE_BOUNDARY_STEPS,
    execute_native_core_boundary,
    select_native_core_boundary_steps,
)


def _panel() -> pd.DataFrame:
    dates = pd.date_range("2020-01-01", periods=220, freq="B")
    series_ids = (
        "DERIVED:CP_TBILL_SPREAD",
        "DERIVED:SOFR_IORB_SPREAD",
        "FRED:NFCICREDIT",
        "FRED:NFCIRISK",
        "CBOE:MOVE",
        "DERIVED:SPX_ROLL_SPREAD",
    )
    rows = []
    for series_index, series_id in enumerate(series_ids):
        for index, date in enumerate(dates):
            rows.append(
                {
                    "date": date,
                    "series_id": series_id,
                    "value": index / 50 + series_index / 10,
                }
            )
    return pd.DataFrame(rows)


def _prepare_generation(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    generation = tmp_path / "generation"
    current = generation / "current"
    current.mkdir(parents=True)
    monkeypatch.setenv("SYSTEM_GENERATION_DIR", str(generation))
    monkeypatch.setenv("CURRENT_OUTPUT_DIR", str(current))
    monkeypatch.setenv("SYSTEM_GENERATION_MODE", "1")
    return generation, current


def test_live_registry_selects_only_the_two_core_boundaries() -> None:
    assert NATIVE_CORE_BOUNDARY_STEPS == {
        "neutral_pressure_measurement",
        "quality_validation",
    }

    selected = select_native_core_boundary_steps(
        {
            "steps": {
                "neutral_pressure_measurement": {
                    "status": "active",
                    "allowed_to_affect_core_judgment": True,
                    "failure_behavior": "block_current_readout",
                    "execution": {"native_core_boundary": "shadow_pilot"},
                },
                "quality_validation": {
                    "status": "active",
                    "allowed_to_affect_core_judgment": True,
                    "failure_behavior": "block_promotion",
                    "execution": {"native_core_boundary": "shadow_pilot"},
                },
            }
        }
    )
    assert selected == (
        {
            "step_id": "neutral_pressure_measurement",
            "failure_behavior": "block_current_readout",
        },
        {
            "step_id": "quality_validation",
            "failure_behavior": "block_promotion",
        },
    )


def test_native_core_pilot_is_registered_stopped_with_blocking_checks() -> None:
    assert native_core_pilot_job in tuple(defs.jobs or ())
    assert native_core_pilot_schedule in tuple(defs.schedules or ())
    assert native_core_pilot_schedule.default_status.value == "STOPPED"
    assert len(NATIVE_CORE_ASSETS) == 2
    assert len(NATIVE_CORE_CHECKS) == 2
    quality_metadata = NATIVE_CORE_ASSETS[1].metadata_by_key[NATIVE_CORE_ASSETS[1].key]
    assert quality_metadata["upstream_steps"] == ["neutral_pressure_measurement"]
    assert all(
        spec.blocking
        for check in NATIVE_CORE_CHECKS
        for spec in check.check_specs
    )


def test_native_core_asset_payload_is_shadow_only() -> None:
    payload = native_core_payload(
        {
            "status": "success",
            "artifact_status": "PASS",
            "check_passed": True,
            "writes_active_generation": True,
            "output_paths": ["generation/current/quality_validation.json"],
        },
        step_id="quality_validation",
        failure_behavior="block_promotion",
    )

    assert payload["authority"] == "shadow_only"
    assert payload["promotion_allowed"] is False
    assert payload["writes_legacy_output"] is False
    assert payload["check_passed"] is True


def test_native_core_check_passes_for_valid_shadow_result() -> None:
    assets = build_native_core_assets(
        document={
            "steps": {
                "quality_validation": {
                    "status": "active",
                    "allowed_to_affect_core_judgment": True,
                    "failure_behavior": "block_promotion",
                    "execution": {"native_core_boundary": "shadow_pilot"},
                }
            }
        },
        boundary_runner=lambda _step_id: {
            "status": "success",
            "artifact_status": "PASS",
            "check_passed": True,
            "writes_active_generation": True,
        },
    )
    checks = build_native_core_checks(assets)

    result = materialize([*assets, *checks])

    assert result.success
    payload = result.output_for_node("native_core_pilot__quality_validation")
    assert payload["check_passed"] is True
    assert payload["authority"] == "shadow_only"


def test_native_core_check_blocks_failed_artifact_inside_pilot_graph() -> None:
    assets = build_native_core_assets(
        document={
            "steps": {
                "quality_validation": {
                    "status": "active",
                    "allowed_to_affect_core_judgment": True,
                    "failure_behavior": "block_promotion",
                    "execution": {"native_core_boundary": "shadow_pilot"},
                }
            }
        },
        boundary_runner=lambda _step_id: {
            "status": "success",
            "artifact_status": "FAIL",
            "check_passed": False,
            "writes_active_generation": True,
        },
    )
    checks = build_native_core_checks(assets)

    with pytest.raises(DagsterAssetCheckFailedError, match="blocking asset check.*failed"):
        materialize([*assets, *checks])


def test_core_boundary_rejects_non_core_or_unknown_tags() -> None:
    with pytest.raises(ValueError, match="requires core authority"):
        select_native_core_boundary_steps(
            {
                "steps": {
                    "quality_validation": {
                        "status": "active",
                        "allowed_to_affect_core_judgment": False,
                        "failure_behavior": "block_promotion",
                        "execution": {"native_core_boundary": "shadow_pilot"},
                    }
                }
            }
        )

    with pytest.raises(ValueError, match="no native core boundary adapter"):
        select_native_core_boundary_steps(
            {
                "steps": {
                    "unknown_core": {
                        "status": "active",
                        "allowed_to_affect_core_judgment": True,
                        "failure_behavior": "block_promotion",
                        "execution": {"native_core_boundary": "shadow_pilot"},
                    }
                }
            }
        )


def test_neutral_core_boundary_writes_only_active_generation(tmp_path: Path, monkeypatch) -> None:
    _generation, current = _prepare_generation(tmp_path, monkeypatch)
    panel_path = tmp_path / "benchmark_panel.parquet"
    _panel().to_parquet(panel_path)

    result = execute_native_core_boundary(
        "neutral_pressure_measurement",
        benchmark_panel_path=panel_path,
        current_output=current,
    )

    assert result["status"] == "success"
    assert result["mode"] == "native_core_boundary"
    assert result["failure_behavior"] == "block_current_readout"
    assert result["artifact_status"] == "ACTIVE_PARTIAL"
    assert result["check_passed"] is True
    assert result["authority"] == "shadow_only"
    assert result["promotion_allowed"] is False
    assert result["writes_legacy_output"] is False
    assert result["writes_active_generation"] is True
    assert result["measurement_evidence"]["as_of"]
    assert result["measurement_evidence"]["common_sample"]["status"] == (
        "diagnostic_only_common_sample"
    )
    assert result["measurement_evidence"]["common_sample"]["used_for_default_readout"] is False
    assert result["measurement_evidence"]["carry_forward_policy"]
    assert (current / "neutral_pressure_snapshot.json").is_file()
    assert (current / "framework_output.json").is_file()
    assert (current / ".native_shadow" / "neutral_pressure" / "pressure_history.parquet").is_file()
    assert not (tmp_path / "Output").exists()


def test_quality_core_boundary_exposes_failed_artifact_without_legacy_write(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _generation, current = _prepare_generation(tmp_path, monkeypatch)
    (current / "framework_output.json").write_text(
        '{"as_of":"2026-08-25","basic":{},'
        '"advanced":{"channel_confidence":{"K":{"readout_role":"operational"}}}}\n',
        encoding="utf-8",
    )

    result = execute_native_core_boundary(
        "quality_validation",
        current_output=current,
        caselab_dir=tmp_path / "caselab",
        hmm_path=tmp_path / "regime_hmm.json",
    )

    assert result["status"] == "success"
    assert result["mode"] == "native_core_boundary"
    assert result["failure_behavior"] == "block_promotion"
    assert result["artifact_status"] == "FAIL"
    assert result["check_passed"] is False
    assert result["authority"] == "shadow_only"
    assert result["promotion_allowed"] is False
    assert result["writes_legacy_output"] is False
    assert (current / "quality_validation.json").is_file()
    assert not (tmp_path / "Output").exists()


def test_missing_neutral_panel_is_typed_shadow_error(tmp_path: Path, monkeypatch) -> None:
    _generation, current = _prepare_generation(tmp_path, monkeypatch)

    result = execute_native_core_boundary(
        "neutral_pressure_measurement",
        benchmark_panel_path=tmp_path / "missing.parquet",
        current_output=current,
    )

    assert result["status"] == "error"
    assert result["failure_behavior"] == "block_current_readout"
    assert result["authority"] == "shadow_only"
    assert result["promotion_allowed"] is False
    assert result["writes_legacy_output"] is False
    assert result["check_passed"] is False
