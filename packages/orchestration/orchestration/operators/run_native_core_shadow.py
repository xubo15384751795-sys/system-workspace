#!/usr/bin/env python3
"""Run the stopped core-boundary pilot and persist a shadow-only evidence report.

The command materializes ``native_core_pilot_job`` into its health-only shadow
root.  It never writes ``Output/current``, publication pointers, or promotion
state.  A real core check failure is reported as ``BLOCKED_UPSTREAM`` when the
dependent quality asset is consequently not executed; that is evidence of
failure propagation, not permission to promote the pilot.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from dagster import materialize

from orchestration.assets.native_core import (
    build_native_core_assets,
    build_native_core_checks,
)
from orchestration.definitions import defs
from orchestration.native_core_boundaries import execute_native_core_boundary
from workbench.measurement.neutral_pressure_measurement import DEFAULT_PANEL
from verity.runtime.runtime_io import ROOT

DEFAULT_REPORT = ROOT / "Output" / "state" / "health" / "native_core_shadow.json"
SHADOW_ROOT = ROOT / "Output" / "state" / "health" / "native_core_shadow"


def _surface_fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    if not path.exists():
        return "MISSING"
    for item in sorted(path.rglob("*")):
        if item.is_file():
            digest.update(str(item.relative_to(path)).encode("utf-8"))
            digest.update(item.read_bytes())
    return digest.hexdigest()


def _event_step(event: Any) -> str | None:
    step_key = getattr(event, "step_key", None)
    return str(step_key) if step_key else None


def _asset_key(event: Any) -> str | None:
    asset_key = getattr(event, "asset_key", None)
    if asset_key is None:
        specific_data = getattr(event, "event_specific_data", None)
        evaluation = getattr(specific_data, "asset_check_evaluation", None)
        if evaluation is None and hasattr(specific_data, "asset_key"):
            evaluation = specific_data
        asset_key = getattr(evaluation, "asset_key", None)
    if asset_key is None:
        step = _event_step(event) or ""
        for step_id in ("neutral_pressure_measurement", "quality_validation"):
            if f"native_core_{step_id}" in step:
                return f"native_core_pilot/{step_id}"
        return None
    try:
        return asset_key.to_user_string()
    except AttributeError:
        return str(asset_key)


def _output_for_node(result: Any, node_name: str) -> dict[str, Any] | None:
    try:
        payload = result.output_for_node(node_name)
    except Exception:  # noqa: BLE001 - evidence command converts missing output
        return None
    return payload if isinstance(payload, dict) else None


def run_shadow(
    *,
    root: Path = ROOT,
    benchmark_panel_path: Path | None = None,
) -> dict[str, Any]:
    """Materialize the core pilot and classify its observed propagation.

    The default path resolves the registered stopped job.  An explicit panel
    is a shadow-only requalification seam: it builds the same native assets
    and checks with a runner bound to that panel, while keeping the workspace
    current surface and promotion authority untouched.  This makes a fresh
    provider release testable without smuggling scratch data into the default
    path.
    """
    current = root / "Output" / "current"
    shadow_root = root / "Output" / "state" / "health" / "native_core_shadow"
    current_before = _surface_fingerprint(current)
    use_registered_job = benchmark_panel_path is None and root.resolve() == ROOT.resolve()
    effective_panel_path: Path | None = None
    if use_registered_job:
        job = defs.resolve_job_def("native_core_pilot_job")
        result = job.execute_in_process(raise_on_error=False)
        materialization_mode = "registered_stopped_job"
    else:
        effective_panel_path = (
            benchmark_panel_path.expanduser().resolve()
            if benchmark_panel_path is not None
            else root
            / "Data"
            / "harvester"
            / "exports"
            / "latest"
            / "data"
            / "benchmark_panel.parquet"
        ).resolve()

        def _runner(step_id: str) -> dict[str, Any]:
            boundary_result = execute_native_core_boundary(
                step_id,
                benchmark_panel_path=effective_panel_path,
                current_output=shadow_root,
            )
            return {**boundary_result, "writes_active_generation": False}

        assets = build_native_core_assets(boundary_runner=_runner)
        checks = build_native_core_checks(assets)
        result = materialize([*assets, *checks], raise_on_error=False)
        materialization_mode = (
            "explicit_panel_shadow"
            if benchmark_panel_path is not None
            else "isolated_default_panel_shadow"
        )
    current_after = _surface_fingerprint(current)

    neutral_payload = _output_for_node(
        result,
        "native_core_pilot__neutral_pressure_measurement",
    )
    quality_payload = _output_for_node(
        result,
        "native_core_pilot__quality_validation",
    )
    materialized = sorted(
        key
        for event in result.all_events
        if event.event_type_value == "ASSET_MATERIALIZATION"
        for key in [_asset_key(event)]
        if key
    )
    checks = []
    for event in result.all_events:
        if event.event_type_value != "ASSET_CHECK_EVALUATION":
            continue
        specific_data = getattr(event, "event_specific_data", None)
        evaluation = getattr(specific_data, "asset_check_evaluation", None)
        if evaluation is None and hasattr(specific_data, "passed"):
            evaluation = specific_data
        passed = getattr(evaluation, "passed", None)
        if passed is None:
            asset = _asset_key(event) or ""
            step_id = asset.rsplit("/", 1)[-1] if "/" in asset else ""
            payload = _output_for_node(
                result,
                f"native_core_pilot__{step_id}",
            )
            passed = payload.get("check_passed") if payload else None
        checks.append(
            {
                "asset": _asset_key(event),
                "passed": passed,
                "step": _event_step(event),
            }
        )
    failed_steps = sorted(
        step
        for event in result.all_events
        if event.event_type_value == "STEP_FAILURE"
        for step in [_event_step(event)]
        if step
    )
    neutral_check_failed = bool(
        neutral_payload
        and neutral_payload.get("check_passed") is False
    )
    quality_not_materialized = "native_core_pilot/quality_validation" not in materialized
    if neutral_check_failed and quality_not_materialized:
        status = "BLOCKED_UPSTREAM"
    elif result.success:
        status = "PASS"
    else:
        status = "FAIL"

    report: dict[str, Any] = {
        "schema_version": "system.native_core_shadow.v1",
        "status": status,
        "authority": "shadow_only",
        "promotion_allowed": False,
        "job": "native_core_pilot_job",
        "materialization_mode": materialization_mode,
        "benchmark_panel_path": (
            str(effective_panel_path)
            if effective_panel_path is not None
            else str(DEFAULT_PANEL.expanduser().resolve())
        ),
        "schedule_status": "STOPPED",
        "materialized_assets": materialized,
        "asset_checks": checks,
        "failed_steps": failed_steps,
        "neutral_payload": neutral_payload,
        "quality_payload": quality_payload,
        "failure_propagation": {
            "neutral_check_failed": neutral_check_failed,
            "quality_not_materialized": quality_not_materialized,
            "blocked_upstream_observed": neutral_check_failed and quality_not_materialized,
        },
        "shadow_output_root": str(shadow_root),
        "shadow_output_paths": sorted(
            str(path) for path in shadow_root.rglob("*") if path.is_file()
        )
        if shadow_root.exists()
        else [],
        "workspace_current_unchanged": current_before == current_after,
        "business_default_path_changed": False,
    }
    return report


def _write_json_atomically(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            mode="w",
            encoding="utf-8",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(payload, temporary, ensure_ascii=False, indent=2, sort_keys=True)
            temporary.write("\n")
        temporary_path.replace(path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="Workspace root whose current surface and health directory are inspected.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="Report path; defaults to <root>/Output/state/health/native_core_shadow.json.",
    )
    parser.add_argument(
        "--benchmark-panel",
        type=Path,
        help=(
            "Optional explicit panel for a shadow-only requalification run; "
            "the default admitted panel is used when omitted."
        ),
    )
    args = parser.parse_args(argv)
    root = args.root.expanduser().resolve()
    report_path = (
        args.report.expanduser().resolve()
        if args.report is not None
        else root / "Output" / "state" / "health" / "native_core_shadow.json"
    )
    report = run_shadow(root=root, benchmark_panel_path=args.benchmark_panel)
    _write_json_atomically(report_path, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
