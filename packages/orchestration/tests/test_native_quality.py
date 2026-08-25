from __future__ import annotations

import pytest
from dagster import materialize

from orchestration.assets import native_quality
from orchestration.assets.native_quality import (
    NATIVE_QUALITY_ASSETS,
    NATIVE_QUALITY_CHECKS,
    native_quality_payload,
    select_native_quality_steps,
)
from orchestration.definitions import daily_job, defs
from scripts.commands.weekly import build_measurement_quality_report


def test_live_quality_registry_compiles_one_native_quality_asset() -> None:
    selected = select_native_quality_steps(native_quality.load_registry_document())

    assert selected == (
        {
            "step_id": "measurement_quality_report",
            "failure_behavior": "continue_with_warning",
            "native_callable": (
                "scripts.commands.weekly.build_measurement_quality_report:build_report"
            ),
        },
    )
    assert NATIVE_QUALITY_ASSETS[0].key.path == [
        "native_quality",
        "measurement_quality_report",
    ]
    assert NATIVE_QUALITY_ASSETS[0] in tuple(defs.assets or ())
    assert NATIVE_QUALITY_CHECKS[0] in tuple(defs.asset_checks or ())
    assert NATIVE_QUALITY_ASSETS[0].op.retry_policy.max_retries == 1
    assert all(
        not spec.blocking
        for check in NATIVE_QUALITY_CHECKS
        for spec in check.check_specs
    )


def test_native_quality_rejects_blocking_or_core_tags() -> None:
    document = {
        "steps": {
            "quality": {
                "status": "active",
                "failure_behavior": "block_promotion",
                "allowed_to_affect_core_judgment": False,
                "execution": {
                    "dagster_native_asset": "native_quality_pilot",
                    "native_callable": "fixture:build",
                },
            },
            "core": {
                "status": "active",
                "failure_behavior": "continue_with_warning",
                "allowed_to_affect_core_judgment": True,
                "execution": {
                    "dagster_native_asset": "native_quality_pilot",
                    "native_callable": "fixture:build",
                },
            },
        }
    }

    with pytest.raises(ValueError, match="invalid registry native_quality_pilot tags"):
        select_native_quality_steps(document)


def test_native_quality_asset_materializes_without_legacy_write(monkeypatch) -> None:
    report = {
        "schema_version": "system.measurement_quality.v1",
        "overall_status": "OK",
    }
    calls: list[str] = []

    def fake_build_report() -> dict[str, object]:
        calls.append("build_report")
        return report

    monkeypatch.setattr(build_measurement_quality_report, "build_report", fake_build_report)
    result = materialize(list(NATIVE_QUALITY_ASSETS))

    assert result.success
    assert calls == ["build_report"]
    payload = result.output_for_node("native_quality__measurement_quality_report")
    assert payload == native_quality_payload(
        report,
        step_id="measurement_quality_report",
        failure_behavior="continue_with_warning",
    )
    assert payload["writes_legacy_output"] is False


def test_native_quality_check_is_non_blocking(monkeypatch) -> None:
    monkeypatch.setattr(
        build_measurement_quality_report,
        "build_report",
        lambda: {"overall_status": "DEGRADED"},
    )
    result = materialize([NATIVE_QUALITY_ASSETS[0], NATIVE_QUALITY_CHECKS[0]])

    assert result.success
    assert daily_job.nodes_in_topological_order[0].name == "daily_job_entry"
