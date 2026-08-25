from __future__ import annotations

from dagster import materialize
import pytest

from orchestration.assets import native_batch
from orchestration.assets.native_batch import (
    NATIVE_BATCH_ASSETS,
    NATIVE_BATCH_CHECKS,
    build_data_gaps_native,
    build_native_batch_assets,
    native_batch_payload,
    select_native_pilot_steps,
)
from orchestration.definitions import defs, daily_job
from scripts.commands.weekly import build_artifact_registry as artifact_registry


def test_native_batch_is_registered_with_retry_and_shadow_metadata() -> None:
    asset_def = NATIVE_BATCH_ASSETS[0]

    assert asset_def.key.path == ["native_batch", "build_data_gaps"]
    assert asset_def in tuple(defs.assets or ())
    assert asset_def.op.retry_policy.max_retries == 1
    assert asset_def.op.retry_policy.delay == 5
    metadata = asset_def.metadata_by_key[asset_def.key]
    assert metadata["authority"] == "shadow_only"
    assert metadata["writes_legacy_output"] is False
    assert metadata["native_callable"] == (
        "scripts.commands.weekly.build_data_gaps:build_data_gaps"
    )
    assert len(NATIVE_BATCH_CHECKS) == len(NATIVE_BATCH_ASSETS)
    assert all(
        not spec.blocking
        for check in NATIVE_BATCH_CHECKS
        for spec in check.check_specs
    )
    assert NATIVE_BATCH_CHECKS[0] in tuple(defs.asset_checks or ())


def test_live_registry_compiles_native_pilot_from_direct_callable() -> None:
    selected = select_native_pilot_steps(native_batch.load_registry_document())

    assert selected == (
        {
            "step_id": "build_data_gaps",
            "failure_behavior": "continue_with_warning",
            "native_callable": "scripts.commands.weekly.build_data_gaps:build_data_gaps",
        },
        {
            "step_id": "evidence_grade_report",
            "failure_behavior": "continue_with_warning",
            "native_callable": (
                "scripts.commands.weekly.build_evidence_grade_report:"
                "build_evidence_grade_report"
            ),
        },
        {
            "step_id": "build_artifact_registry",
            "failure_behavior": "continue_with_warning",
            "native_callable": (
                "scripts.commands.weekly.build_artifact_registry:build_artifact_registry"
            ),
        },
        {
            "step_id": "change_analysis",
            "failure_behavior": "continue_with_warning",
            "native_callable": (
                "scripts.commands.weekly.build_change_analysis:build_change_analysis"
            ),
        },
    )


def test_native_pilot_rejects_invalid_registry_tags() -> None:
    document = {
        "steps": {
            "blocked": {
                "status": "active",
                "failure_behavior": "block_promotion",
                "allowed_to_affect_core_judgment": False,
                "execution": {
                    "dagster_native_asset": "native_pilot",
                    "native_callable": "fixture:run",
                },
            },
            "core": {
                "status": "active",
                "failure_behavior": "continue_with_warning",
                "allowed_to_affect_core_judgment": True,
                "execution": {
                    "dagster_native_asset": "native_pilot",
                    "native_callable": "fixture:run",
                },
            },
            "missing_callable": {
                "status": "active",
                "failure_behavior": "continue_with_warning",
                "allowed_to_affect_core_judgment": False,
                "execution": {"dagster_native_asset": "native_pilot"},
            },
        }
    }

    with pytest.raises(ValueError, match="invalid registry native_pilot tags"):
        select_native_pilot_steps(document)


def test_native_batch_rejects_unresolvable_direct_callable(monkeypatch) -> None:
    monkeypatch.delenv("SYSTEM_GENERATION_MODE", raising=False)
    monkeypatch.delenv("SYSTEM_GENERATION_DIR", raising=False)
    with pytest.raises(ValueError, match="callable cannot be resolved"):
        build_native_batch_assets(
            document={
                "steps": {
                    "broken": {
                        "status": "active",
                        "failure_behavior": "continue_with_warning",
                        "allowed_to_affect_core_judgment": False,
                        "execution": {
                            "dagster_native_asset": "native_pilot",
                            "native_callable": "missing.module:run",
                        },
                    }
                }
            }
        )


def test_native_batch_defers_callable_import_when_generation_dir_is_unset(
    monkeypatch,
) -> None:
    monkeypatch.setenv("SYSTEM_GENERATION_MODE", "1")
    monkeypatch.delenv("SYSTEM_GENERATION_DIR", raising=False)
    assets = build_native_batch_assets(
        document={
            "steps": {
                "broken": {
                    "status": "active",
                    "failure_behavior": "continue_with_warning",
                    "allowed_to_affect_core_judgment": False,
                    "execution": {
                        "dagster_native_asset": "native_pilot",
                        "native_callable": "missing.module:run",
                    },
                }
            }
        }
    )
    assert [asset.key.path[-1] for asset in assets] == ["broken"]


def test_native_batch_compiles_registry_callable_without_runner(monkeypatch) -> None:
    report = {"schema_version": "data_gaps.v2", "gaps": [], "summary": {}}
    calls: list[str] = []

    def fake_build_data_gaps() -> dict[str, object]:
        calls.append("build_data_gaps")
        return report

    monkeypatch.setattr(native_batch, "build_data_gaps", fake_build_data_gaps)
    assets = build_native_batch_assets(
        document={
            "steps": {
                "build_data_gaps": {
                    "status": "active",
                    "failure_behavior": "continue_with_warning",
                    "allowed_to_affect_core_judgment": False,
                    "execution": {
                        "dagster_native_asset": "native_pilot",
                        "native_callable": (
                            "scripts.commands.weekly.build_data_gaps:build_data_gaps"
                        ),
                    },
                }
            }
        }
    )

    result = materialize(list(assets))

    assert result.success
    assert calls == ["build_data_gaps"]
    assert result.output_for_node("native_batch__build_data_gaps") == native_batch_payload(
        report
    )


def test_native_batch_resolves_generic_module_callable(monkeypatch) -> None:
    report = {"schema_version": "artifact_registry.v1", "artifact_count": 0}
    calls: list[str] = []

    def fake_build_artifact_registry() -> dict[str, object]:
        calls.append("build_artifact_registry")
        return report

    monkeypatch.setattr(artifact_registry, "build_artifact_registry", fake_build_artifact_registry)
    assets = build_native_batch_assets(
        document={
            "steps": {
                "build_artifact_registry": {
                    "status": "active",
                    "failure_behavior": "continue_with_warning",
                    "allowed_to_affect_core_judgment": False,
                    "execution": {
                        "dagster_native_asset": "native_pilot",
                        "native_callable": (
                            "scripts.commands.weekly.build_artifact_registry:"
                            "build_artifact_registry"
                        ),
                    },
                }
            }
        }
    )

    result = materialize(list(assets))

    assert result.success
    assert calls == ["build_artifact_registry"]
    payload = result.output_for_node("native_batch__build_artifact_registry")
    assert payload["report"] == report
    assert payload["writes_legacy_output"] is False


def test_native_batch_maps_explicit_dependency_and_propagates_failure(monkeypatch) -> None:
    calls: list[str] = []

    def failing_upstream() -> dict[str, object]:
        calls.append("upstream")
        raise RuntimeError("synthetic upstream failure")

    def downstream() -> dict[str, object]:
        calls.append("downstream")
        return {"schema_version": "downstream.v1"}

    monkeypatch.setattr(native_batch, "build_data_gaps", failing_upstream)
    monkeypatch.setattr(artifact_registry, "build_artifact_registry", downstream)
    assets = build_native_batch_assets(
        document={
            "steps": {
                "upstream": {
                    "status": "active",
                    "failure_behavior": "continue_with_warning",
                    "allowed_to_affect_core_judgment": False,
                    "execution": {
                        "dagster_native_asset": "native_pilot",
                        "native_callable": (
                            "scripts.commands.weekly.build_data_gaps:build_data_gaps"
                        ),
                    },
                },
                "downstream": {
                    "status": "active",
                    "failure_behavior": "continue_with_warning",
                    "allowed_to_affect_core_judgment": False,
                    "execution": {
                        "dagster_native_asset": "native_pilot",
                        "native_callable": (
                            "scripts.commands.weekly.build_artifact_registry:"
                            "build_artifact_registry"
                        ),
                        "native_depends_on": ["upstream"],
                    },
                },
            }
        }
    )

    downstream_asset = next(asset for asset in assets if asset.key.path[-1] == "downstream")
    assert downstream_asset.metadata_by_key[downstream_asset.key]["native_depends_on"] == [
        "upstream"
    ]
    result = materialize(list(assets), raise_on_error=False)

    assert result.success is False
    assert calls
    assert set(calls) == {"upstream"}


def test_native_batch_rejects_dependency_outside_native_batch() -> None:
    with pytest.raises(ValueError, match="references non-native step"):
        build_native_batch_assets(
            document={
                "steps": {
                    "native": {
                        "status": "active",
                        "failure_behavior": "continue_with_warning",
                        "allowed_to_affect_core_judgment": False,
                        "execution": {
                            "dagster_native_asset": "native_pilot",
                            "native_callable": (
                                "scripts.commands.weekly.build_data_gaps:build_data_gaps"
                            ),
                            "native_depends_on": ["legacy_step"],
                        },
                    }
                }
            }
        )


def test_native_batch_materializes_direct_builder_without_legacy_write(
    monkeypatch,
) -> None:
    report = {"schema_version": "data_gaps.v2", "gaps": [], "summary": {}}
    calls: list[str] = []

    def fake_build_data_gaps() -> dict[str, object]:
        calls.append("build_data_gaps")
        return report

    monkeypatch.setattr(native_batch, "build_data_gaps", fake_build_data_gaps)
    result = materialize([build_data_gaps_native])

    assert result.success
    assert calls == ["build_data_gaps"]
    payload = result.output_for_node("native_batch__build_data_gaps")
    assert payload == native_batch_payload(report)
    assert payload["authority"] == "shadow_only"
    assert payload["writes_legacy_output"] is False


def test_native_batch_contract_check_is_non_blocking_and_passes(monkeypatch) -> None:
    report = {"schema_version": "data_gaps.v2", "gaps": [], "summary": {}}
    monkeypatch.setattr(native_batch, "build_data_gaps", lambda: report)

    result = materialize([build_data_gaps_native, NATIVE_BATCH_CHECKS[0]])

    assert result.success


def test_native_batch_does_not_change_daily_job_graph() -> None:
    assert {node.name for node in daily_job.nodes_in_topological_order} == {
        "daily_job_entry"
    }
