#!/usr/bin/env python3
"""Compare the full native daily graph with the current generated-op graph.

This is an operator evidence command, not a production runner.  It loads the
real compiled registry plan and asks both Dagster paths to build every step's
invocation in ``dry_run`` mode.  No provider callable or subprocess is run;
the command only proves that the two orchestration mechanisms resolve the same
sequence and invocation contract.  The default daily path and publication
surfaces are left untouched, and promotion is always false.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from orchestration.native_daily import (
    NATIVE_DAILY_ENV,
    build_native_daily_assets,
    run_daily_sequence_via_native_assets,
)
from orchestration.native_daily_checks import build_native_daily_checks
from orchestration.runner import (
    DailyRunPayload,
    build_daily_step_job,
    run_daily_sequence_via_dagster,
)
from scripts._runtime_io import ROOT
from system_runtime.paths import WorkspacePaths
from system_runtime.pipeline import CompiledPlan, load_pipeline

DEFAULT_REPORT = ROOT / "Output" / "health" / "native_daily_plan_shadow.json"


def _surface_fingerprint(path: Path) -> str:
    """Return a stable digest for a read-only surface tree."""
    if not path.exists():
        return "MISSING"
    digest = hashlib.sha256()
    for item in sorted(path.rglob("*")):
        if not item.is_file():
            continue
        digest.update(str(item.relative_to(path)).encode("utf-8"))
        digest.update(item.read_bytes())
    return digest.hexdigest()


def _payload(
    plan: CompiledPlan,
    *,
    root: Path,
    recorded: list[dict[str, Any]],
) -> DailyRunPayload:
    def _unexpected_execution(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("dry-run parity attempted to execute a step")

    return DailyRunPayload(
        args=SimpleNamespace(
            force_weekly=True,
            skip_harvester=False,
            skip_etf=False,
        ),
        start_time=datetime.now(UTC),
        total_steps=len(plan.sequence()),
        run_step_fn=_unexpected_execution,
        record_fn=lambda result, input_artifacts=None: recorded.append(dict(result)),
        benchmark_panel_path=root
        / "Data"
        / "harvester"
        / "exports"
        / "latest"
        / "data"
        / "benchmark_panel.parquet",
        run_id="native-daily-plan-shadow",
        plan=plan,
        dry_run=True,
    )


def _first_difference(
    native_results: list[dict[str, Any]],
    generated_results: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for index, (native, generated) in enumerate(
        zip(native_results, generated_results, strict=False)
    ):
        if native != generated:
            return {
                "index": index,
                "native": native,
                "generated": generated,
            }
    if len(native_results) != len(generated_results):
        return {
            "index": min(len(native_results), len(generated_results)),
            "native_count": len(native_results),
            "generated_count": len(generated_results),
        }
    return None


def run_shadow(
    *,
    root: Path = ROOT,
    plan: CompiledPlan | None = None,
) -> dict[str, Any]:
    """Run full-plan dry parity without invoking business step bodies."""
    resolved_plan = plan or load_pipeline(WorkspacePaths(root=root))
    native_recorded: list[dict[str, Any]] = []
    generated_recorded: list[dict[str, Any]] = []
    native_payload = _payload(resolved_plan, root=root, recorded=native_recorded)
    generated_payload = _payload(resolved_plan, root=root, recorded=generated_recorded)
    current_surface = root / "Output" / "current"
    current_before = _surface_fingerprint(current_surface)
    previous_flag = os.environ.pop(NATIVE_DAILY_ENV, None)
    native_asset_definitions = build_native_daily_assets(native_payload, plan=resolved_plan)
    native_check_definitions = build_native_daily_checks(
        native_asset_definitions,
        blocking=False,
    )
    native_check_specs = [
        check_spec
        for check_definition in native_check_definitions
        for check_spec in check_definition.check_specs
    ]

    try:
        native_results = run_daily_sequence_via_native_assets(native_payload)
        generated_job = build_daily_step_job(generated_payload, plan=resolved_plan)
        generated_results = run_daily_sequence_via_dagster(generated_payload)
    finally:
        if previous_flag is None:
            os.environ.pop(NATIVE_DAILY_ENV, None)
        else:
            os.environ[NATIVE_DAILY_ENV] = previous_flag

    default_path_flag_restored = (
        os.environ.get(NATIVE_DAILY_ENV) == previous_flag
        if previous_flag is not None
        else NATIVE_DAILY_ENV not in os.environ
    )
    current_after = _surface_fingerprint(current_surface)
    expected_steps = [str(item.get("id", "")) for item in resolved_plan.sequence()]
    native_steps = [str(item.get("step", "")) for item in native_results]
    generated_steps = [str(item.get("step", "")) for item in generated_results]
    result_match = native_results == generated_results
    sequence_match = native_steps == generated_steps == expected_steps
    current_unchanged = current_before == current_after
    report: dict[str, Any] = {
        "status": "MATCH"
        if result_match and sequence_match and current_unchanged
        else "MISMATCH",
        "promotion_allowed": False,
        "authority": "shadow_only",
        "plan_digest": resolved_plan.plan_digest,
        "expected_step_count": len(expected_steps),
        "native_result_count": len(native_results),
        "generated_result_count": len(generated_results),
        "native_asset_check_count": len(native_check_specs),
        "native_asset_check_blocking": any(
            bool(check_spec.blocking) for check_spec in native_check_specs
        ),
        "native_steps": native_steps,
        "generated_steps": generated_steps,
        "sequence_match": sequence_match,
        "result_match": result_match,
        "workspace_current_unchanged": current_unchanged,
        "generated_job_node_count": len(generated_job.graph.node_names()),
        "execution_mode": "dry_run_no_business_execution",
        "business_step_execution_attempted": False,
        "default_path_flag_restored": default_path_flag_restored,
    }
    difference = _first_difference(native_results, generated_results)
    if difference is not None:
        report["first_difference"] = difference
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    report = run_shadow(root=ROOT)
    output_path = args.report if args.report.is_absolute() else ROOT / args.report
    _write_json_atomically(output_path, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "MATCH" else 2


if __name__ == "__main__":
    raise SystemExit(main())
