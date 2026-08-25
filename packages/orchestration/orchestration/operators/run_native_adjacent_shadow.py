#!/usr/bin/env python3
"""Run the stopped ledger/paper-position pilot and persist evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from orchestration.definitions import defs
from scripts._runtime_io import ROOT

DEFAULT_REPORT = ROOT / "Output" / "health" / "native_adjacent_shadow.json"
_STEP_IDS = ("record_trade_decision", "paper_portfolio")


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
        for step_id in _STEP_IDS:
            if f"native_adjacent_{step_id}" in step:
                return f"native_adjacent_pilot/{step_id}"
        return None
    try:
        return asset_key.to_user_string()
    except AttributeError:
        return str(asset_key)


def _output_for_node(result: Any, step_id: str) -> dict[str, Any] | None:
    try:
        payload = result.output_for_node(f"native_adjacent_pilot__{step_id}")
    except Exception:  # noqa: BLE001 - missing output is evidence
        return None
    return payload if isinstance(payload, dict) else None


def run_shadow(*, root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    shared_surfaces = {
        name: root / "Output" / name
        for name in ("current", "trade_ledger", "system_learning", "position")
    }
    before = {
        name: _surface_fingerprint(path) for name, path in shared_surfaces.items()
    }
    job = defs.resolve_job_def("native_adjacent_pilot_job")
    result = job.execute_in_process(raise_on_error=False)
    after = {name: _surface_fingerprint(path) for name, path in shared_surfaces.items()}

    payloads = {step_id: _output_for_node(result, step_id) for step_id in _STEP_IDS}
    materialized = sorted(
        key
        for event in result.all_events
        if event.event_type_value == "ASSET_MATERIALIZATION"
        for key in [_asset_key(event)]
        if key
    )
    checks: list[dict[str, Any]] = []
    for event in result.all_events:
        if event.event_type_value != "ASSET_CHECK_EVALUATION":
            continue
        specific_data = getattr(event, "event_specific_data", None)
        evaluation = getattr(specific_data, "asset_check_evaluation", None)
        if evaluation is None and hasattr(specific_data, "passed"):
            evaluation = specific_data
        checks.append(
            {
                "asset": _asset_key(event),
                "passed": getattr(evaluation, "passed", None),
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
    materialized_ids = {
        key.rsplit("/", 1)[-1]
        for key in materialized
        if key.startswith("native_adjacent_pilot/")
    }
    missing_steps = [
        step_id for step_id in _STEP_IDS if step_id not in materialized_ids
    ]
    upstream_blocked = bool(missing_steps and any(payloads.values()))
    if result.success and not missing_steps:
        status = "PASS"
    elif upstream_blocked:
        status = "BLOCKED_UPSTREAM"
    else:
        status = "FAIL"

    shadow_root = root / "Output" / "health" / "native_adjacent_shadow"
    return {
        "schema_version": "system.native_adjacent_shadow.v1",
        "status": status,
        "authority": "shadow_only",
        "promotion_allowed": False,
        "job": "native_adjacent_pilot_job",
        "schedule_status": "STOPPED",
        "selected_steps": list(_STEP_IDS),
        "materialized_assets": materialized,
        "missing_steps": missing_steps,
        "asset_checks": checks,
        "failed_steps": failed_steps,
        "step_payloads": payloads,
        "failure_propagation": {
            "blocked_upstream_observed": upstream_blocked,
            "missing_downstream_steps": missing_steps,
        },
        "shadow_output_root": str(shadow_root),
        "shadow_output_paths": sorted(
            str(path) for path in shadow_root.rglob("*") if path.is_file()
        )
        if shadow_root.exists()
        else [],
        "shared_surface_fingerprints_before": before,
        "shared_surface_fingerprints_after": after,
        "shared_surfaces_unchanged": before == after,
        "business_default_path_changed": False,
    }


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
        help="Workspace root whose shared surfaces are fingerprinted.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="Report path; defaults to <root>/Output/health/native_adjacent_shadow.json.",
    )
    args = parser.parse_args(argv)
    root = args.root.expanduser().resolve()
    report_path = (
        args.report.expanduser().resolve()
        if args.report is not None
        else root / "Output" / "health" / "native_adjacent_shadow.json"
    )
    report = run_shadow(root=root)
    _write_json_atomically(report_path, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
