#!/usr/bin/env python3
"""Materialize native pilot assets and compare them to registry artifacts.

This operator command is read-only with respect to the legacy pipeline by
default. The native builders are selected from explicit registry tags,
materialized into Dagster's ephemeral execution context, and compared with
existing JSON artifacts. It does not run ``pipeline_runner``, write
``Output/current``, or promote any asset. The explicit ``--same-inputs`` mode
runs only the selected legacy pure report writers in a temporary generation.
Each native report is then materialized against the corresponding per-step
legacy generation snapshot, so order-sensitive current-surface inputs are
equal without allowing either track to touch the workspace current surface.
This is a report-input parity gate; the separate native pilot job still proves
the selected assets can materialize together.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from dagster import materialize

from orchestration.assets.native_batch import (
    NATIVE_BATCH_ASSETS,
    load_registry_document,
    select_native_pilot_steps,
)
from orchestration.assets.native_quality import (
    NATIVE_QUALITY_ASSETS,
    select_native_quality_steps,
)
from orchestration.native_parity import build_native_parity_report, compare_native_report
from scripts._runtime_io import ROOT

DEFAULT_REPORT = ROOT / "Output" / "health" / "native_batch_shadow_parity.json"


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _surface_fingerprint(path: Path) -> str:
    """Hash a surface tree so the shadow command can prove it stayed read-only."""
    digest = hashlib.sha256()
    if not path.exists():
        return "MISSING"
    for item in sorted(path.rglob("*")):
        if not item.is_file():
            continue
        digest.update(str(item.relative_to(path)).encode("utf-8"))
        digest.update(item.read_bytes())
    return digest.hexdigest()


def _copy_input_surfaces(root: Path, generation_root: Path) -> None:
    """Copy only read surfaces needed by the legacy pure report builders."""
    output_root = root / "Output"
    for name in ("current", "judgment", "trade_decision", "quality"):
        source = output_root / name
        if not source.exists():
            continue
        shutil.copytree(
            source.resolve(),
            generation_root / name,
            dirs_exist_ok=True,
            symlinks=False,
        )


def _generation_artifact_path(generation_root: Path, artifact_path: str, root: Path) -> Path:
    """Map an ``Output/...`` registry path into an isolated generation."""
    if artifact_path.startswith("Output/"):
        return generation_root / Path(artifact_path).relative_to("Output")
    return root / artifact_path


def _run_legacy_callable(
    *,
    callable_spec: str,
    root: Path,
    generation_root: Path,
) -> dict[str, Any]:
    """Run one legacy report writer in the isolated generation directory."""
    module_name, function_name = callable_spec.rsplit(":", 1)
    code = (
        f"from {module_name} import {function_name}; "
        f"result = {function_name}(); "
        "raise SystemExit(result if isinstance(result, int) else 0)"
    )
    env = os.environ.copy()
    env.update(
        {
            "SYSTEM_WORKSPACE_ROOT": str(root),
            "SYSTEM_GENERATION_MODE": "1",
            "SYSTEM_GENERATION_DIR": str(generation_root),
            "CURRENT_OUTPUT_DIR": str(generation_root / "current"),
            "DAILY_OUTPUT_ROOT": str(generation_root),
        }
    )
    pythonpath = [
        str(root),
        str(root / "scripts"),
        str(root / "packages" / "orchestration"),
        str(root / "packages" / "harvester" / "src"),
        str(root / "packages" / "workbench" / "src"),
    ]
    existing = [part for part in env.get("PYTHONPATH", "").split(os.pathsep) if part]
    env["PYTHONPATH"] = os.pathsep.join([*pythonpath, *existing])
    try:
        completed = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(root),
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "status": "error",
            "callable": callable_spec,
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {
        "status": "success" if completed.returncode == 0 else "failed",
        "callable": callable_spec,
        "returncode": completed.returncode,
        "stdout_tail": (completed.stdout or "")[-500:],
        "stderr_tail": (completed.stderr or "")[-1000:],
    }


@contextmanager
def _isolated_generation_environment(
    *,
    root: Path,
    generation_root: Path,
) -> Iterator[None]:
    """Route generation-aware builders to one temporary input snapshot."""
    keys = (
        "SYSTEM_WORKSPACE_ROOT",
        "SYSTEM_GENERATION_MODE",
        "SYSTEM_GENERATION_DIR",
        "CURRENT_OUTPUT_DIR",
        "DAILY_OUTPUT_ROOT",
    )
    previous = {key: os.environ.get(key) for key in keys}
    os.environ.update(
        {
            "SYSTEM_WORKSPACE_ROOT": str(root),
            "SYSTEM_GENERATION_MODE": "1",
            "SYSTEM_GENERATION_DIR": str(generation_root),
            "CURRENT_OUTPUT_DIR": str(generation_root / "current"),
            "DAILY_OUTPUT_ROOT": str(generation_root),
        }
    )
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def run_shadow(
    *,
    root: Path = ROOT,
    same_inputs: bool = False,
) -> dict[str, Any]:
    """Run native parity, optionally rebuilding legacy reports in isolation.

    The default compares against existing registry artifacts.  With
    ``same_inputs=True`` the legacy ``future_callable`` writers run in a
    temporary generation seeded from current input surfaces. Each native
    asset is then materialized against the matching legacy generation
    snapshot; no workspace ``Output/current`` file is touched.
    """
    document = load_registry_document(root)
    selected = [
        *(
            {**item, "asset_group": "native_batch", "node_prefix": "native_batch"}
            for item in select_native_pilot_steps(document)
        ),
        *(
            {**item, "asset_group": "native_quality", "node_prefix": "native_quality"}
            for item in select_native_quality_steps(document)
        ),
    ]
    comparisons: dict[str, dict[str, Any]] = {}
    legacy_runs: dict[str, dict[str, Any]] = {}
    legacy_snapshots: dict[str, Path] = {}
    native_payloads: dict[str, dict[str, Any] | None] = {}
    native_materialize_success = True
    workspace_current_before = (
        _surface_fingerprint(root / "Output" / "current") if same_inputs else None
    )

    with tempfile.TemporaryDirectory(prefix="native-batch-parity-") as temporary:
        generation_root = Path(temporary) / "legacy" if same_inputs else None
        native_input_root = Path(temporary) / "native-inputs" if same_inputs else None
        if generation_root is not None and native_input_root is not None:
            _copy_input_surfaces(root, generation_root)
            for item in selected:
                step_id = item["step_id"]
                spec = document["steps"][step_id]
                execution = spec.get("execution") or {}
                future_callable = str(execution.get("future_callable") or "").strip()
                comparison_key = f"{item['asset_group']}:{step_id}"
                if future_callable.count(":") != 1:
                    legacy_runs[comparison_key] = {
                        "status": "invalid_callable",
                        "callable": future_callable,
                    }
                else:
                    legacy_runs[comparison_key] = _run_legacy_callable(
                        callable_spec=future_callable,
                        root=root,
                        generation_root=generation_root,
                    )
                snapshot = native_input_root / f"{len(legacy_snapshots):03d}_{step_id}"
                shutil.copytree(generation_root, snapshot, dirs_exist_ok=True)
                legacy_snapshots[comparison_key] = snapshot

            native_assets_by_node = {
                f"{item['node_prefix']}__{item['step_id']}": asset_def
                for item, asset_def in zip(
                    selected,
                    [*NATIVE_BATCH_ASSETS, *NATIVE_QUALITY_ASSETS],
                    strict=False,
                )
            }
            for item in selected:
                comparison_key = f"{item['asset_group']}:{item['step_id']}"
                node_name = f"{item['node_prefix']}__{item['step_id']}"
                snapshot = legacy_snapshots[comparison_key]
                asset_def = native_assets_by_node[node_name]
                with _isolated_generation_environment(
                    root=root,
                    generation_root=snapshot,
                ):
                    native_execution = materialize([asset_def], raise_on_error=False)
                native_materialize_success = (
                    native_materialize_success and native_execution.success
                )
                if native_execution.success:
                    try:
                        payload = native_execution.output_for_node(node_name)
                    except Exception:  # noqa: BLE001 - convert execution failure to evidence
                        payload = None
                    native_payloads[comparison_key] = (
                        payload["report"]
                        if isinstance(payload, dict)
                        and isinstance(payload.get("report"), dict)
                        else None
                    )
                else:
                    native_payloads[comparison_key] = None
        else:
            result = materialize([*NATIVE_BATCH_ASSETS, *NATIVE_QUALITY_ASSETS])
            native_materialize_success = bool(result.success)

        for item in selected:
            step_id = item["step_id"]
            comparison_key = f"{item['asset_group']}:{step_id}"
            node_name = f"{item['node_prefix']}__{step_id}"
            native_report: dict[str, Any] | None = None
            if same_inputs:
                native_report = native_payloads.get(comparison_key)
            elif result.success:
                try:
                    payload = result.output_for_node(node_name)
                except Exception:  # noqa: BLE001 - convert execution failure to evidence
                    payload = None
                if isinstance(payload, dict) and isinstance(payload.get("report"), dict):
                    native_report = payload["report"]

            spec = document["steps"][step_id]
            artifact_path = str(spec.get("artifact_path") or "").strip()
            if generation_root is not None:
                legacy_snapshot = legacy_snapshots.get(comparison_key, generation_root)
                legacy_path = (
                    _generation_artifact_path(legacy_snapshot, artifact_path, root)
                    if artifact_path
                    else legacy_snapshot / "__missing__"
                )
                legacy_artifact_label = (
                    f"<temporary-generation>/{Path(artifact_path).relative_to('Output')}"
                    if artifact_path.startswith("Output/")
                    else str(legacy_path)
                )
            else:
                legacy_path = root / artifact_path if artifact_path else root / "__missing__"
                legacy_artifact_label = str(legacy_path)
            comparisons[comparison_key] = compare_native_report(
                step_id=step_id,
                native_report=native_report,
                legacy_report=_read_json(legacy_path) if legacy_path.is_file() else None,
            )
            comparisons[comparison_key]["asset_group"] = item["asset_group"]
            comparisons[comparison_key]["legacy_artifact"] = legacy_artifact_label

    report = build_native_parity_report(comparisons)
    report["dagster_materialize_success"] = native_materialize_success
    report["same_inputs"] = same_inputs
    if same_inputs:
        report["input_preparation"] = "per_asset_legacy_generation_snapshot"
        report["legacy_execution"] = legacy_runs
        workspace_current_after = _surface_fingerprint(root / "Output" / "current")
        report["workspace_current_unchanged"] = (
            workspace_current_before == workspace_current_after
        )
        if not report["workspace_current_unchanged"]:
            report["status"] = "MISMATCH"
            report["workspace_mutation"] = "Output/current changed during shadow run"
        if any(item.get("status") != "success" for item in legacy_runs.values()):
            report["status"] = "INCOMPLETE"
            report["legacy_execution_failure"] = True
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
    parser.add_argument(
        "--same-inputs",
        action="store_true",
        help="Rebuild legacy pure reports in a temporary generation before comparing.",
    )
    args = parser.parse_args()
    report = run_shadow(root=ROOT, same_inputs=args.same_inputs)
    output_path = args.report if args.report.is_absolute() else ROOT / args.report
    _write_json_atomically(output_path, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "MATCH" else 2


if __name__ == "__main__":
    raise SystemExit(main())
