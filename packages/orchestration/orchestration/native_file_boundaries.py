"""Explicit file-boundary adapters for the first native asset migration batch.

These adapters keep the existing report/calculation code as the business
authority while moving current-surface writes behind a materialization-time
path boundary. They are opt-in from ``native_daily`` and remain shadow-only
until a real dual-run window proves parity.
"""
from __future__ import annotations

import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from verity.runtime.runtime_io import ROOT, current_dir, surface_dir

_SUPPORTED_FILE_BOUNDARY_STEPS = frozenset(
    {
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
)
_FILE_BOUNDARY_TAG = "shadow_pilot"


def select_native_file_boundary_steps(
    document: Mapping[str, Any],
) -> frozenset[str]:
    """Select registry-tagged adapters and reject unimplemented declarations."""
    steps = document.get("steps") or {}
    if not isinstance(steps, Mapping):
        raise ValueError("pipeline registry steps must be a mapping")
    selected = {
        str(step_id)
        for step_id, spec in steps.items()
        if isinstance(spec, Mapping)
        and isinstance(spec.get("execution"), Mapping)
        and spec["execution"].get("native_file_boundary") == _FILE_BOUNDARY_TAG
    }
    unsupported = sorted(selected - _SUPPORTED_FILE_BOUNDARY_STEPS)
    if unsupported:
        raise ValueError(
            "registry native_file_boundary tags have no adapter: "
            + ", ".join(unsupported)
        )
    return frozenset(selected)


def load_native_file_boundary_steps(root: Path = ROOT) -> frozenset[str]:
    """Load the file-boundary selection from the authoritative registry."""
    path = root / "governance" / "daily_pipeline_registry.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(document, Mapping):
        raise ValueError("pipeline registry must be a mapping")
    return select_native_file_boundary_steps(document)


NATIVE_FILE_BOUNDARY_STEPS = load_native_file_boundary_steps()


def execute_native_file_boundary(step_id: str) -> dict[str, Any]:
    """Run one explicitly migrated writer against the active generation."""
    from workbench.surfaces.build_current_status import gather_status, write_status
    from workbench.surfaces.build_signal_card import build_signal_card, write_signal_card
    from workbench.surfaces.build_work_brief import build_work_brief, write_work_brief
    from workbench.surfaces.build_artifact_registry import (
        build_artifact_registry,
        write_artifact_registry,
    )
    from workbench.surfaces.build_change_analysis import (
        build_change_analysis,
        write_change_analysis,
    )
    from workbench.surfaces.build_data_gaps import (
        build_data_gaps,
        write_data_gaps_files,
    )
    from workbench.surfaces.build_evidence_grade_report import (
        build_evidence_grade_report,
        write_evidence_grade_report,
    )
    from workbench.measurement.build_measurement_quality_report import (
        build_report,
        write_report,
    )
    from workbench.surfaces.build_next_actions import (
        build_next_actions,
        write_next_actions,
    )
    from workbench.surfaces.build_readme_first import (
        build_readme_content,
        write_readme,
    )
    from workbench.surfaces.signal_consensus import build_consensus, write_signal_consensus

    if step_id not in NATIVE_FILE_BOUNDARY_STEPS:
        raise ValueError(f"no native file boundary registered for {step_id!r}")

    started = time.monotonic()
    current = current_dir()
    judgment = surface_dir("judgment") / "latest.json"
    try:
        if step_id == "build_data_gaps":
            report = build_data_gaps(
                current_path=current,
                judgment_path=judgment.parent,
                data_authority_path=ROOT / "governance" / "authority_registry.yaml",
                data_request_path=ROOT / "governance" / "data_request_registry.yaml",
            )
            json_path, markdown_path = write_data_gaps_files(
                report,
                current_path=current,
            )
            output_paths = [str(json_path), str(markdown_path)]
        elif step_id == "evidence_grade_report":
            report = build_evidence_grade_report(
                paths={
                    "judgment": judgment,
                    "promotion_gate": judgment.parent / "promotion_gate.json",
                    "trade_decision": surface_dir("trade_decision") / "latest.json",
                    # These are shared, read-only diagnostic inputs rather
                    # than generation-owned current writers.  Keep the same
                    # source paths as the existing callable until their own
                    # asset boundaries are migrated.
                    "k_gate": ROOT / "Output" / "k_measurement" / "k_measurement_gate.json",
                    "x_gate": ROOT / "Output" / "x_measurement" / "x_measurement_gate.json",
                    "hmm_audit": ROOT / "Output" / "state" / "hmm_stability" / "hmm_stability_audit.json",
                    "freshness": surface_dir("quality") / "freshness_report.json",
                    "paper_manifest": ROOT / "Data" / "paper_world_model" / "manifest.json",
                    "harvester_catalog": (
                        ROOT
                        / "Data"
                        / "harvester"
                        / "exports"
                        / "latest"
                        / "catalog.json"
                    ),
                    "data_request": ROOT / "governance" / "data_request_registry.yaml",
                    "output": current / "evidence_grade_report.json",
                }
            )
            output_path = write_evidence_grade_report(
                report,
                output_path=current / "evidence_grade_report.json",
            )
            output_paths = [str(output_path)]
        elif step_id == "build_artifact_registry":
            registry = build_artifact_registry(
                root=ROOT,
                routing_policy_path=ROOT / "governance" / "output_routing_policy.yaml",
                pipeline_registry_path=ROOT / "governance" / "daily_pipeline_registry.yaml",
                current_path=current,
            )
            output_path = write_artifact_registry(
                registry,
                output_path=current / "artifact_registry.json",
            )
            output_paths = [str(output_path)]
        elif step_id == "change_analysis":
            analysis = build_change_analysis(
                judgment_dir=ROOT / "Output" / "judgment",
                caselab_dir=ROOT / "Output" / "state" / "caselab",
                current_path=current,
                active_judgment_path=judgment,
            )
            json_path, markdown_path = write_change_analysis(
                analysis,
                output_dir=current,
            )
            output_paths = [str(json_path), str(markdown_path)]
        elif step_id == "signal_card":
            card = build_signal_card(
                paths={
                    "current": current,
                    "judgment": judgment.parent,
                    "trade_decision": surface_dir("trade_decision"),
                    "caselab": ROOT / "Output" / "state" / "caselab",
                    "hmm": ROOT / "Output" / "state" / "ml_signals" / "latest",
                }
            )
            json_path, markdown_path = write_signal_card(
                card,
                output_dir=current,
            )
            output_paths = [str(json_path), str(markdown_path)]
        elif step_id == "signal_consensus":
            result = build_consensus(
                paths={
                    "output": current,
                    "framework_output": current / "framework_output.json",
                    "judgment": judgment,
                    "promotion_gate": judgment.parent / "promotion_gate.json",
                    "hmm": ROOT / "Output" / "state" / "ml_signals" / "daily" / "regime_hmm.json",
                    "k_gate": ROOT / "Output" / "k_measurement" / "k_measurement_gate.json",
                    "x_gate": ROOT / "Output" / "x_measurement" / "x_measurement_gate.json",
                    "prob_context": ROOT / "Output" / "probabilistic_context" / "latest.json",
                    "caselab": ROOT / "Output" / "state" / "caselab",
                }
            )
            json_path, markdown_path = write_signal_consensus(
                result,
                output_dir=current,
            )
            output_paths = [str(json_path), str(markdown_path)]
        elif step_id == "measurement_quality_report":
            report = build_report()
            output_path = write_report(
                report,
                output_path=current / "measurement_quality.json",
            )
            output_paths = [str(output_path)]
        elif step_id == "work_brief":
            brief = build_work_brief(
                paths={
                    "current": current,
                    "judgment": judgment.parent,
                    "trade": surface_dir("trade_decision"),
                    "ml_signals": ROOT / "Output" / "state" / "ml_signals",
                    "caselab": ROOT / "Output" / "state" / "caselab",
                    "harvester_catalog": (
                        ROOT / "Data" / "harvester" / "exports" / "latest" / "catalog.json"
                    ),
                }
            )
            json_path, markdown_path = write_work_brief(
                brief,
                output_dir=current,
            )
            output_paths = [str(json_path), str(markdown_path)]
        elif step_id == "current_status":
            status = gather_status(
                paths={
                    "judgment": judgment,
                    "promotion_gate": judgment.parent / "promotion_gate.json",
                    "index": ROOT / "Data" / "system_index" / "latest.json",
                    "k_gate": ROOT / "Output" / "k_measurement" / "k_measurement_gate.json",
                    "x_gate": ROOT / "Output" / "x_measurement" / "x_measurement_gate.json",
                    "hmm_audit": ROOT / "Output" / "state" / "hmm_stability" / "hmm_stability_audit.json",
                    "caselab": ROOT / "Output" / "state" / "caselab",
                    "output": current,
                }
            )
            output_path = write_status(status, output_dir=current)
            output_paths = [str(output_path)]
        elif step_id == "readme_first":
            readme = build_readme_content(
                paths={
                    "index": ROOT / "Data" / "system_index" / "latest.json",
                    "current": current,
                    "framework_output": current / "framework_output.json",
                    "evidence_report": current / "evidence_grade_report.json",
                    "trade_decision": surface_dir("trade_decision") / "latest.json",
                }
            )
            if readme is None:
                raise FileNotFoundError("system index is missing for readme_first")
            output_path = write_readme(
                readme,
                output_path=current / "00_READ_ME_FIRST.md",
            )
            output_paths = [str(output_path)]
        elif step_id == "next_actions":
            status, actions = build_next_actions(
                paths={
                    "output": current,
                    "improvement_ledger": (
                        ROOT
                        / "Data"
                        / "system_learning"
                        / "ledgers"
                        / "improvement_queue.parquet"
                    ),
                }
            )
            output_path = write_next_actions(
                status,
                actions,
                output_path=current / "NEXT_ACTIONS.md",
            )
            output_paths = [str(output_path)]
        else:  # pragma: no cover - guarded by registry selection above
            raise ValueError(f"no implementation for native file boundary {step_id!r}")
        return {
            "step": step_id,
            "status": "success",
            "mode": "native_file_boundary",
            "returncode": 0,
            "duration_s": round(time.monotonic() - started, 2),
            "output_paths": output_paths,
            "writes_active_generation": True,
            "writes_legacy_output": False,
            "authority": "shadow_only",
            "promotion_allowed": False,
        }
    except Exception as exc:  # noqa: BLE001 - preserve typed step failure shape
        return {
            "step": step_id,
            "status": "error",
            "mode": "native_file_boundary",
            "duration_s": round(time.monotonic() - started, 2),
            "error": str(exc),
            "writes_active_generation": False,
            "writes_legacy_output": False,
            "authority": "shadow_only",
            "promotion_allowed": False,
        }


__all__ = [
    "NATIVE_FILE_BOUNDARY_STEPS",
    "execute_native_file_boundary",
    "load_native_file_boundary_steps",
    "select_native_file_boundary_steps",
]
