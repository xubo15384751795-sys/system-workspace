"""Shadow file boundaries for the first core-judgment migration steps.

The two adapters in this module deliberately stop at the file boundary:

* ``neutral_pressure_measurement`` invokes the neutral-pressure model plugin
  and writes the snapshot/framework compatibility files to the active generation.
* ``quality_validation`` keeps its existing Pandera-like rule set and writes
  the report to the active generation.

The registry remains the authority for core status and ``failure_behavior``.
These adapters are shadow-only and are not used by the default runner.  They
also do not write ``steps.jsonl``, legacy run directories, or promotion state.
"""
from __future__ import annotations

import time
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from verity.runtime.runtime_io import ROOT, current_dir, load_json, utc_now

CORE_BOUNDARY_TAG = "shadow_pilot"
SUPPORTED_CORE_BOUNDARY_STEPS = frozenset(
    {
        "neutral_pressure_measurement",
        "quality_validation",
    }
)
ALLOWED_FAILURE_BEHAVIORS = frozenset(
    {
        "block_current_readout",
        "block_core_judgment",
        "block_promotion",
    }
)


def select_native_core_boundary_steps(
    document: Mapping[str, Any],
) -> tuple[dict[str, str], ...]:
    """Select explicitly tagged core boundaries and fail closed on bad tags."""
    steps = document.get("steps") or {}
    if not isinstance(steps, Mapping):
        raise ValueError("pipeline registry steps must be a mapping")

    selected: list[dict[str, str]] = []
    errors: list[str] = []
    for step_id, spec in steps.items():
        if not isinstance(spec, Mapping):
            continue
        execution = spec.get("execution") or {}
        if not isinstance(execution, Mapping):
            continue
        if execution.get("native_core_boundary") != CORE_BOUNDARY_TAG:
            continue

        authority = spec.get("authority") if isinstance(spec.get("authority"), Mapping) else {}
        failure_behavior = str(
            spec.get("failure_behavior") or authority.get("failure_behavior") or ""
        )
        affects_core = bool(
            spec.get("allowed_to_affect_core_judgment")
            or authority.get("affects_core_judgment")
        )
        status = str(spec.get("status") or "")
        step_name = str(step_id)
        if step_name not in SUPPORTED_CORE_BOUNDARY_STEPS:
            errors.append(f"{step_name}: no native core boundary adapter")
        if status != "active":
            errors.append(f"{step_name}: core shadow boundary requires status=active")
        if not affects_core:
            errors.append(f"{step_name}: core shadow boundary requires core authority")
        if failure_behavior not in ALLOWED_FAILURE_BEHAVIORS:
            errors.append(
                f"{step_name}: core shadow boundary forbids failure_behavior={failure_behavior!r}"
            )
        if execution.get("native_file_boundary"):
            errors.append(
                f"{step_name}: core shadow boundary cannot share native_file_boundary"
            )
        selected.append(
            {
                "step_id": step_name,
                "failure_behavior": failure_behavior,
            }
        )

    if errors:
        raise ValueError("invalid registry native_core_boundary tags: " + "; ".join(errors))
    return tuple(selected)


def load_native_core_boundary_steps(root: Path = ROOT) -> frozenset[str]:
    """Load core-boundary selection from the authoritative registry."""
    path = root / "governance" / "daily_pipeline_registry.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(document, Mapping):
        raise ValueError("pipeline registry must be a mapping")
    return frozenset(
        item["step_id"] for item in select_native_core_boundary_steps(document)
    )


NATIVE_CORE_BOUNDARY_STEPS = load_native_core_boundary_steps()


def _neutral_history_path(output_dir: Path) -> Path:
    """Keep shadow history inside the active generation, away from legacy runs."""
    return output_dir / ".native_shadow" / "neutral_pressure" / "pressure_history.parquet"


def _result_base(step_id: str, failure_behavior: str) -> dict[str, Any]:
    return {
        "step": step_id,
        "failure_behavior": failure_behavior,
        "authority": "shadow_only",
        "promotion_allowed": False,
        "writes_legacy_output": False,
    }


def execute_native_core_boundary(
    step_id: str,
    *,
    benchmark_panel_path: Path | None = None,
    current_output: Path | None = None,
    caselab_dir: Path | None = None,
    hmm_path: Path | None = None,
) -> dict[str, Any]:
    """Execute one core writer against explicit active-generation paths."""
    selected = {
        item["step_id"]: item["failure_behavior"]
        for item in select_native_core_boundary_steps(_load_registry_document())
    }
    if step_id not in NATIVE_CORE_BOUNDARY_STEPS or step_id not in selected:
        raise ValueError(f"no native core boundary registered for {step_id!r}")

    from workbench.measurement import quality_field_validator as quality
    from workbench.measurement import neutral_pressure_measurement as neutral
    from workbench.plugins.neutral_pressure_md.cli import evaluate_neutral_pressure
    from workbench.plugins.neutral_pressure_md.legacy_output import build_legacy_snapshot

    failure_behavior = selected[step_id]
    started = time.monotonic()
    output_dir = current_output or current_dir()
    try:
        if step_id == "neutral_pressure_measurement":
            panel_path = benchmark_panel_path or neutral.DEFAULT_PANEL
            history_path = _neutral_history_path(output_dir)
            run_id = os.environ.get("ZCODE_BUNDLE_RUN_ID") or "native_core_boundary"
            evaluation = evaluate_neutral_pressure(
                panel_path=panel_path,
                history_path=history_path,
                run_id=run_id,
                release_id=neutral._release_id(),
            )
            snapshot, history = build_legacy_snapshot(
                evaluation,
                panel_path=panel_path,
                history_path=history_path,
                mechanism_cards=ROOT / "docs" / "measurements" / "macro_pressure_mechanism_cards.md",
            )
            snapshot_path, framework_path, history_path = neutral.write_snapshot_files(
                snapshot,
                history,
                output_dir=output_dir,
                history_path=history_path,
            )
            output_paths = [str(snapshot_path), str(framework_path), str(history_path)]
            artifact_status = str(snapshot.get("status") or "UNKNOWN").upper()
            check_passed = artifact_status in {"ACTIVE_PARTIAL", "ACTIVE_FULL"}
            advanced = snapshot.get("advanced")
            advanced = advanced if isinstance(advanced, Mapping) else {}
            common_sample = history.dropna(subset=["M", "D"])
            if common_sample.empty:
                common_sample_evidence: dict[str, Any] | None = None
            else:
                common_date = str(common_sample.index[-1])[:10]
                common_row = common_sample.iloc[-1]
                common_sample_evidence = {
                    "as_of": common_date,
                    "values": {
                        "M": round(float(common_row["M"]), 4),
                        "D": round(float(common_row["D"]), 4),
                    },
                    "used_for_default_readout": False,
                    "status": "diagnostic_only_common_sample",
                }
            measurement_evidence = {
                "as_of": snapshot.get("as_of"),
                "snapshot_status": snapshot.get("status"),
                "quality_status": advanced.get("quality_status"),
                "harvester_release": advanced.get("harvester_release"),
                "sigma_vector": advanced.get("sigma_vector"),
                "channel_coverage": advanced.get("channel_coverage"),
                "component_metadata": advanced.get("component_metadata"),
                "common_sample": common_sample_evidence,
                "carry_forward_policy": (
                    "component_ffill_limit_5_on_shared_business_day_calendar; "
                    "no cross-gauge carry-forward"
                ),
            }
        elif step_id == "quality_validation":
            framework_path = output_dir / "framework_output.json"
            framework = load_json(framework_path)
            date_str = str(framework.get("as_of") or utc_now().date())[:10]
            report = quality.build_validation_report(
                framework or None,
                date_str,
                caselab_dir=caselab_dir or quality.CASELAB_DIR,
                hmm_path=hmm_path or quality.HMM_PATH,
            )
            output_path = quality.write_validation_report(
                report,
                output_path=output_dir / "quality_validation.json",
            )
            output_paths = [str(output_path)]
            artifact_status = str(report.get("status") or "UNKNOWN").upper()
            check_passed = artifact_status == "PASS"
            measurement_evidence = None
        else:  # pragma: no cover - selection is fail-closed above
            raise ValueError(f"no implementation for native core boundary {step_id!r}")

        return {
            **_result_base(step_id, failure_behavior),
            "status": "success",
            "mode": "native_core_boundary",
            "duration_s": round(time.monotonic() - started, 2),
            "artifact_status": artifact_status,
            "check_passed": check_passed,
            "output_paths": output_paths,
            "measurement_evidence": measurement_evidence,
            "writes_active_generation": True,
        }
    except Exception as exc:  # noqa: BLE001 - preserve typed step failure shape
        return {
            **_result_base(step_id, failure_behavior),
            "status": "error",
            "mode": "native_core_boundary",
            "duration_s": round(time.monotonic() - started, 2),
            "error": str(exc),
            "writes_active_generation": False,
            "check_passed": False,
        }


def _load_registry_document() -> dict[str, Any]:
    path = ROOT / "governance" / "daily_pipeline_registry.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("pipeline registry must be a mapping")
    return payload


__all__ = [
    "ALLOWED_FAILURE_BEHAVIORS",
    "CORE_BOUNDARY_TAG",
    "NATIVE_CORE_BOUNDARY_STEPS",
    "SUPPORTED_CORE_BOUNDARY_STEPS",
    "execute_native_core_boundary",
    "load_native_core_boundary_steps",
    "select_native_core_boundary_steps",
]
