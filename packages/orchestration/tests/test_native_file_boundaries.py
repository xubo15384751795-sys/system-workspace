from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from dagster import materialize
import yaml

from orchestration.native_daily import (
    NATIVE_FILE_BOUNDARY_ENV,
    build_native_daily_assets,
)
from orchestration.native_file_boundaries import (
    NATIVE_FILE_BOUNDARY_STEPS,
    execute_native_file_boundary,
    select_native_file_boundary_steps,
)
from orchestration.runner import DailyRunPayload
from workbench.surfaces.build_data_gaps import build_data_gaps
from system_runtime.pipeline import CompiledPipeline, CompiledStep
from verity.runtime.runtime_io import ROOT


def _plan() -> CompiledPipeline:
    return CompiledPipeline(
        schema_version="native-file-boundary-test.v1",
        steps=(
            CompiledStep(
                step_id="build_data_gaps",
                order=25,
                status="active",
                owner="Workbench",
                schedule="weekly",
                command="python -c pass",
                callable_spec="workbench.surfaces.build_data_gaps:build_data_gaps",
                execution_mode="callable",
                inputs=("Output/current/framework_output.json", "Output/judgment/latest.json"),
                outputs=("Output/current/data_gaps.json", "Output/current/data_gaps.md"),
                failure_behavior="continue_with_warning",
                affects_core_judgment=False,
            ),
        ),
        external_inputs=(),
        edges={},
        profiles={"daily": ("build_data_gaps",)},
    )


def _prepare_generation(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    generation = tmp_path / "generation"
    current = generation / "current"
    judgment = generation / "judgment"
    current.mkdir(parents=True)
    judgment.mkdir(parents=True)
    (current / "framework_output.json").write_text("{}\n", encoding="utf-8")
    (judgment / "latest.json").write_text(
        '{"confidence": {}, "gate_status": {}, "claim_ceiling": "diagnostic"}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("SYSTEM_GENERATION_DIR", str(generation))
    monkeypatch.setenv("CURRENT_OUTPUT_DIR", str(current))
    monkeypatch.setenv("SYSTEM_GENERATION_MODE", "1")
    return generation, current


def test_file_boundary_writes_only_active_generation(tmp_path: Path, monkeypatch) -> None:
    _generation, current = _prepare_generation(tmp_path, monkeypatch)

    result = execute_native_file_boundary("build_data_gaps")

    assert result["status"] == "success"
    assert result["mode"] == "native_file_boundary"
    assert result["writes_active_generation"] is True
    assert result["writes_legacy_output"] is False
    assert (current / "data_gaps.json").is_file()
    assert (current / "data_gaps.md").is_file()
    assert not (tmp_path / "Output").exists()


def test_evidence_grade_file_boundary_writes_only_active_generation(
    tmp_path: Path, monkeypatch
) -> None:
    _generation, current = _prepare_generation(tmp_path, monkeypatch)

    result = execute_native_file_boundary("evidence_grade_report")

    assert result["status"] == "success"
    assert result["mode"] == "native_file_boundary"
    assert result["writes_active_generation"] is True
    assert result["writes_legacy_output"] is False
    assert result["output_paths"] == [str(current / "evidence_grade_report.json")]
    assert (current / "evidence_grade_report.json").is_file()
    assert not (tmp_path / "Output").exists()


def test_measurement_quality_file_boundary_writes_only_active_generation(
    tmp_path: Path, monkeypatch
) -> None:
    _generation, current = _prepare_generation(tmp_path, monkeypatch)

    result = execute_native_file_boundary("measurement_quality_report")

    assert result["status"] == "success"
    assert result["mode"] == "native_file_boundary"
    assert result["writes_active_generation"] is True
    assert result["writes_legacy_output"] is False
    assert result["output_paths"] == [str(current / "measurement_quality.json")]
    assert (current / "measurement_quality.json").is_file()
    assert not (tmp_path / "Output").exists()


def test_work_brief_file_boundary_writes_only_active_generation(
    tmp_path: Path, monkeypatch
) -> None:
    _generation, current = _prepare_generation(tmp_path, monkeypatch)

    result = execute_native_file_boundary("work_brief")

    assert result["status"] == "success"
    assert result["mode"] == "native_file_boundary"
    assert result["writes_active_generation"] is True
    assert result["writes_legacy_output"] is False
    assert result["output_paths"] == [
        str(current / "work_brief.json"),
        str(current / "work_brief.md"),
    ]
    assert (current / "work_brief.json").is_file()
    assert (current / "work_brief.md").is_file()
    assert not (tmp_path / "Output").exists()


def test_current_status_file_boundary_writes_only_active_generation(
    tmp_path: Path, monkeypatch
) -> None:
    _generation, current = _prepare_generation(tmp_path, monkeypatch)

    result = execute_native_file_boundary("current_status")

    assert result["status"] == "success"
    assert result["mode"] == "native_file_boundary"
    assert result["writes_active_generation"] is True
    assert result["writes_legacy_output"] is False
    assert result["output_paths"] == [str(current / "status.json")]
    assert (current / "status.json").is_file()
    assert not (tmp_path / "Output").exists()


def test_readme_first_file_boundary_writes_only_active_generation(
    tmp_path: Path, monkeypatch
) -> None:
    _generation, current = _prepare_generation(tmp_path, monkeypatch)

    result = execute_native_file_boundary("readme_first")

    assert result["status"] == "success"
    assert result["mode"] == "native_file_boundary"
    assert result["writes_active_generation"] is True
    assert result["writes_legacy_output"] is False
    assert result["output_paths"] == [str(current / "00_READ_ME_FIRST.md")]
    assert (current / "00_READ_ME_FIRST.md").is_file()
    assert not (tmp_path / "Output").exists()


def test_next_actions_file_boundary_writes_only_active_generation(
    tmp_path: Path, monkeypatch
) -> None:
    _generation, current = _prepare_generation(tmp_path, monkeypatch)
    (current / "status.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-08-25T00:00:00+00:00",
                "date": "2026-08-25",
                "judgment": {},
                "promotion_gate": {
                    "blocked_gates": [],
                    "watch_gates": [],
                    "blocking_reasons": [],
                    "watch_reasons": [],
                    "forbidden_language": [],
                    "allowed_language": [],
                },
                "signals": {"caselab": {}, "hmm": {}, "k_gate": {}, "x_gate": {}},
            }
        ),
        encoding="utf-8",
    )

    result = execute_native_file_boundary("next_actions")

    assert result["status"] == "success"
    assert result["mode"] == "native_file_boundary"
    assert result["writes_active_generation"] is True
    assert result["writes_legacy_output"] is False
    assert result["output_paths"] == [str(current / "NEXT_ACTIONS.md")]
    assert (current / "NEXT_ACTIONS.md").is_file()
    assert not (tmp_path / "Output").exists()


def test_artifact_registry_file_boundary_writes_only_active_generation(
    tmp_path: Path, monkeypatch
) -> None:
    _generation, current = _prepare_generation(tmp_path, monkeypatch)

    result = execute_native_file_boundary("build_artifact_registry")

    assert result["status"] == "success"
    assert result["mode"] == "native_file_boundary"
    assert result["writes_active_generation"] is True
    assert result["writes_legacy_output"] is False
    assert result["output_paths"] == [str(current / "artifact_registry.json")]
    assert (current / "artifact_registry.json").is_file()
    assert not (tmp_path / "Output").exists()


def test_artifact_registry_no_argument_builder_reads_generation_current(
    tmp_path: Path, monkeypatch
) -> None:
    generation, current = _prepare_generation(tmp_path, monkeypatch)
    from workbench.surfaces.build_artifact_registry import build_artifact_registry

    report = build_artifact_registry()
    registered = next(
        item for item in report["artifacts"] if item["name"] == "artifact_registry.json"
    )

    assert registered["exists"] is False
    assert str(generation) not in json.dumps(report)
    assert current.is_dir()


def test_change_analysis_file_boundary_writes_only_active_generation(
    tmp_path: Path, monkeypatch
) -> None:
    _generation, current = _prepare_generation(tmp_path, monkeypatch)

    result = execute_native_file_boundary("change_analysis")

    assert result["status"] == "success"
    assert result["mode"] == "native_file_boundary"
    assert result["writes_active_generation"] is True
    assert result["writes_legacy_output"] is False
    assert result["output_paths"] == [
        str(current / "change_analysis.json"),
        str(current / "change_analysis.md"),
    ]
    assert (current / "change_analysis.json").is_file()
    assert (current / "change_analysis.md").is_file()
    assert not (tmp_path / "Output").exists()


def test_signal_card_file_boundary_writes_only_active_generation(
    tmp_path: Path, monkeypatch
) -> None:
    _generation, current = _prepare_generation(tmp_path, monkeypatch)

    result = execute_native_file_boundary("signal_card")

    assert result["status"] == "success"
    assert result["mode"] == "native_file_boundary"
    assert result["writes_active_generation"] is True
    assert result["writes_legacy_output"] is False
    assert result["output_paths"] == [
        str(current / "signal_card.json"),
        str(current / "signal_card.md"),
    ]
    assert (current / "signal_card.json").is_file()
    assert (current / "signal_card.md").is_file()
    assert not (tmp_path / "Output").exists()


def test_signal_consensus_file_boundary_writes_only_active_generation(
    tmp_path: Path, monkeypatch
) -> None:
    _generation, current = _prepare_generation(tmp_path, monkeypatch)

    result = execute_native_file_boundary("signal_consensus")

    assert result["status"] == "success"
    assert result["mode"] == "native_file_boundary"
    assert result["writes_active_generation"] is True
    assert result["writes_legacy_output"] is False
    assert result["output_paths"] == [
        str(current / "signal_consensus.json"),
        str(current / "signal_consensus.md"),
    ]
    assert (current / "signal_consensus.json").is_file()
    assert (current / "signal_consensus.md").is_file()
    assert not (tmp_path / "Output").exists()


def test_no_argument_builder_resolves_candidate_at_call_time(tmp_path: Path, monkeypatch) -> None:
    _generation, _current = _prepare_generation(tmp_path, monkeypatch)

    report = build_data_gaps()

    assert report["schema_version"] == "data_gaps.v2"
    assert "error" not in report


def test_file_boundary_selection_is_registry_driven_and_fail_closed() -> None:
    assert NATIVE_FILE_BOUNDARY_STEPS == {
        "build_data_gaps",
        "evidence_grade_report",
        "build_artifact_registry",
        "change_analysis",
        "measurement_quality_report",
        "work_brief",
        "current_status",
        "readme_first",
        "next_actions",
        "signal_card",
        "signal_consensus",
    }
    assert select_native_file_boundary_steps(
        {
            "steps": {
                "build_data_gaps": {
                    "execution": {"native_file_boundary": "shadow_pilot"}
                },
                "evidence_grade_report": {
                    "execution": {"native_file_boundary": "shadow_pilot"}
                },
                "build_artifact_registry": {
                    "execution": {"native_file_boundary": "shadow_pilot"}
                },
                "change_analysis": {
                    "execution": {"native_file_boundary": "shadow_pilot"}
                },
                "measurement_quality_report": {
                    "execution": {"native_file_boundary": "shadow_pilot"}
                },
                "work_brief": {
                    "execution": {"native_file_boundary": "shadow_pilot"}
                },
                "current_status": {
                    "execution": {"native_file_boundary": "shadow_pilot"}
                },
                "readme_first": {
                    "execution": {"native_file_boundary": "shadow_pilot"}
                },
                "next_actions": {
                    "execution": {"native_file_boundary": "shadow_pilot"}
                },
                "signal_card": {
                    "execution": {"native_file_boundary": "shadow_pilot"}
                },
                "signal_consensus": {
                    "execution": {"native_file_boundary": "shadow_pilot"}
                }
            }
        }
    ) == {
        "build_data_gaps",
        "evidence_grade_report",
        "build_artifact_registry",
        "change_analysis",
        "measurement_quality_report",
        "work_brief",
        "current_status",
        "readme_first",
        "next_actions",
        "signal_card",
        "signal_consensus",
    }

    try:
        select_native_file_boundary_steps(
            {
                "steps": {
                    "unimplemented": {
                        "execution": {"native_file_boundary": "shadow_pilot"}
                    }
                }
            }
        )
    except ValueError as exc:
        assert "no adapter" in str(exc)
    else:
        raise AssertionError("unknown file boundary declaration must fail closed")


def test_native_daily_uses_file_boundary_only_when_opted_in(tmp_path: Path, monkeypatch) -> None:
    _generation, current = _prepare_generation(tmp_path, monkeypatch)
    monkeypatch.setenv(NATIVE_FILE_BOUNDARY_ENV, "1")
    recorded: list[dict] = []

    payload = DailyRunPayload(
        args=SimpleNamespace(force_weekly=True, skip_harvester=False, skip_etf=False),
        start_time=datetime.now(UTC),
        total_steps=1,
        run_step_fn=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("legacy executor was invoked")
        ),
        record_fn=lambda result, input_artifacts=None: recorded.append(dict(result)),
        benchmark_panel_path=tmp_path / "benchmark.parquet",
        run_id="native-file-boundary-test",
        plan=_plan(),
        dry_run=False,
    )
    asset = build_native_daily_assets(payload, plan=payload.plan)[0]

    result = materialize([asset])

    assert result.success
    assert recorded[0]["mode"] == "native_file_boundary"
    assert (current / "data_gaps.json").is_file()


def test_file_boundary_flag_off_preserves_legacy_execution_metadata(monkeypatch) -> None:
    monkeypatch.delenv(NATIVE_FILE_BOUNDARY_ENV, raising=False)
    payload = DailyRunPayload(
        args=SimpleNamespace(force_weekly=True, skip_harvester=False, skip_etf=False),
        start_time=datetime.now(UTC),
        total_steps=1,
        run_step_fn=lambda *_args, **_kwargs: {"step": "build_data_gaps", "status": "success"},
        record_fn=lambda _result, input_artifacts=None: None,
        benchmark_panel_path=Path("benchmark.parquet"),
        run_id="native-file-boundary-disabled",
        plan=_plan(),
        dry_run=False,
    )

    asset = build_native_daily_assets(payload, plan=payload.plan)[0]
    metadata = asset.metadata_by_key[asset.key]

    assert metadata["file_boundary"] is False
    assert metadata["writes_legacy_output"] is True
    registry = yaml.safe_load(
        (ROOT / "governance" / "daily_pipeline_registry.yaml").read_text(encoding="utf-8")
    )
    assert (
        registry["steps"]["build_data_gaps"]["execution"]["native_file_boundary"]
        == "shadow_pilot"
    )
    assert (
        registry["steps"]["evidence_grade_report"]["execution"]["native_file_boundary"]
        == "shadow_pilot"
    )
    assert (
        registry["steps"]["build_artifact_registry"]["execution"]["native_file_boundary"]
        == "shadow_pilot"
    )
    assert (
        registry["steps"]["change_analysis"]["execution"]["native_file_boundary"]
        == "shadow_pilot"
    )
    assert (
        registry["steps"]["signal_card"]["execution"]["native_file_boundary"]
        == "shadow_pilot"
    )
    assert (
        registry["steps"]["work_brief"]["execution"]["native_file_boundary"]
        == "shadow_pilot"
    )
    assert (
        registry["steps"]["current_status"]["execution"]["native_file_boundary"]
        == "shadow_pilot"
    )
    assert (
        registry["steps"]["readme_first"]["execution"]["native_file_boundary"]
        == "shadow_pilot"
    )
    assert (
        registry["steps"]["next_actions"]["execution"]["native_file_boundary"]
        == "shadow_pilot"
    )
    assert (
        registry["steps"]["signal_consensus"]["execution"]["native_file_boundary"]
        == "shadow_pilot"
    )
