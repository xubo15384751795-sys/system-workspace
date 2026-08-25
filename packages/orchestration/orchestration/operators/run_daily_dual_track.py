#!/usr/bin/env python3
"""Run and compare one isolated legacy/native daily pair.

This is an explicit observation-window operator, not a production scheduler.
By default it performs only a no-write preflight.  ``--execute`` is required
to launch the two real Dagster daily paths.  Each path must use a separate
workspace root and output root so provider/data writes and generation
surfaces cannot collide with the other track or with the operator checkout.

The command always leaves promotion disabled.  A non-zero runner exit, a
missing run bundle, or any comparator mismatch is retained in the report and
never relabelled as a successful parity result.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from orchestration.run_parity import compare_daily_run_bundles
from scripts._runtime_io import ROOT
from system_runtime.publish_transaction import PublishTransaction

SCHEMA_VERSION = "system.orchestration_dual_track_execution.v1"
PROMOTION_ALLOWED = False
_WORKSPACE_MARKER = Path("governance/daily_pipeline_registry.yaml")
_OUTPUT_SURFACES = (
    "live",
    "current",
    "position",
    "judgment",
    "trade_decision",
    "trade_ledger",
    "quality",
    "system_learning",
    "ledgers",
)


@dataclass(frozen=True)
class TrackSpec:
    name: str
    workspace_root: Path
    output_root: Path
    native: bool


def _resolve(path: Path) -> Path:
    return path.expanduser().resolve()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _paths_overlap(left: Path, right: Path) -> bool:
    """Return whether either path contains the other in its directory tree."""
    left_resolved = _resolve(left)
    right_resolved = _resolve(right)
    return _is_relative_to(left_resolved, right_resolved) or _is_relative_to(
        right_resolved, left_resolved
    )


def _admitted_release_identity(workspace_root: Path) -> dict[str, Any]:
    """Read the frozen release identity used by a dual-track workspace."""
    latest = workspace_root / "Data" / "harvester" / "exports" / "latest"
    catalog_path = latest / "catalog.json"
    manifest_path = latest / "manifests" / "benchmark_panel.manifest.json"
    result: dict[str, Any] = {
        "status": "MISSING",
        "latest_path": str(latest),
        "catalog_path": str(catalog_path),
        "manifest_path": str(manifest_path),
        "release_id": None,
        "vintage_date": None,
        "as_of_date": None,
    }
    if not latest.exists():
        result["reason"] = "latest_release_missing"
        return result
    if not catalog_path.is_file():
        result["reason"] = "catalog_missing"
        return result
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        result["reason"] = f"catalog_invalid:{type(exc).__name__}"
        return result
    release_id = catalog.get("release_id") if isinstance(catalog, dict) else None
    if not isinstance(release_id, str) or not release_id.strip():
        result["reason"] = "release_id_missing"
        return result
    result["release_id"] = release_id.strip()
    if not manifest_path.is_file():
        result["reason"] = "benchmark_manifest_missing"
        return result
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        result["reason"] = f"manifest_invalid:{type(exc).__name__}"
        return result
    if isinstance(manifest, dict):
        for key in ("vintage_date", "as_of_date"):
            value = manifest.get(key)
            if isinstance(value, str) and value.strip():
                result[key] = value.strip()
    if not result["vintage_date"] or not result["as_of_date"]:
        result["reason"] = "benchmark_manifest_identity_missing"
        return result
    result["status"] = "READY"
    return result


def _preflight_track(track: TrackSpec, *, operator_root: Path) -> list[str]:
    errors: list[str] = []
    if not track.workspace_root.is_dir():
        errors.append(f"{track.name}: workspace root missing: {track.workspace_root}")
    elif not (track.workspace_root / _WORKSPACE_MARKER).is_file():
        errors.append(
            f"{track.name}: workspace marker missing: "
            f"{track.workspace_root / _WORKSPACE_MARKER}"
        )
    if not (track.workspace_root / "scripts" / "daily_run.py").is_file():
        errors.append(f"{track.name}: scripts/daily_run.py missing")
    if track.workspace_root == operator_root:
        errors.append(f"{track.name}: workspace must be isolated from operator checkout")
    if track.output_root == operator_root / "Output":
        errors.append(f"{track.name}: output root points at operator Output")
    if _paths_overlap(track.output_root, track.workspace_root):
        errors.append(
            f"{track.name}: output root must not overlap workspace root: "
            f"{track.output_root} <-> {track.workspace_root}"
        )
    if track.output_root.exists() and not track.output_root.is_dir():
        errors.append(f"{track.name}: output root is not a directory: {track.output_root}")
    if _is_relative_to(track.output_root, operator_root) or _is_relative_to(
        operator_root, track.output_root
    ):
        errors.append(
            f"{track.name}: output root must not overlap operator checkout: "
            f"{track.output_root}"
        )
    for surface in _OUTPUT_SURFACES:
        candidate = track.output_root / surface
        if candidate.exists() and not candidate.is_symlink():
            errors.append(
                f"{track.name}: real compatibility surface requires explicit migration: {candidate}"
            )
    if track.output_root.exists():
        reconciliation = PublishTransaction.reconcile(
            track.workspace_root,
            output_root=track.output_root,
        )
        if reconciliation.get("status") in {"recovery_required", "rollback"}:
            errors.append(
                f"{track.name}: output root reconciliation is not clean: "
                f"{reconciliation.get('status')}"
            )
    return errors


def preflight_tracks(
    legacy: TrackSpec,
    native: TrackSpec,
    *,
    operator_root: Path = ROOT,
    require_admitted_release: bool = False,
) -> dict[str, Any]:
    """Validate isolation and generation prerequisites without creating files."""
    operator_root = _resolve(operator_root)
    errors = [
        *_preflight_track(legacy, operator_root=operator_root),
        *_preflight_track(native, operator_root=operator_root),
    ]
    legacy_identity = _admitted_release_identity(legacy.workspace_root)
    native_identity = _admitted_release_identity(native.workspace_root)
    if require_admitted_release:
        for identity, name in ((legacy_identity, "legacy"), (native_identity, "native")):
            if identity["status"] != "READY":
                errors.append(
                    f"{name}: admitted release identity unavailable: "
                    f"{identity.get('reason', identity['status'])}"
                )
        if legacy_identity["status"] == native_identity["status"] == "READY":
            identity_keys = ("release_id", "vintage_date", "as_of_date")
            mismatched = [
                key
                for key in identity_keys
                if legacy_identity.get(key) != native_identity.get(key)
            ]
            if mismatched:
                errors.append(
                    "legacy/native admitted release identity mismatch: "
                    + ", ".join(mismatched)
                )
    if _paths_overlap(legacy.workspace_root, native.workspace_root):
        errors.append("legacy and native workspace roots must not overlap")
    if _paths_overlap(legacy.output_root, native.output_root):
        errors.append("legacy and native output roots must not overlap")
    for output_name, output_root in (
        ("legacy", legacy.output_root),
        ("native", native.output_root),
    ):
        for workspace_name, workspace_root in (
            ("legacy", legacy.workspace_root),
            ("native", native.workspace_root),
        ):
            if _paths_overlap(output_root, workspace_root):
                errors.append(
                    f"{output_name} output root must not overlap "
                    f"{workspace_name} workspace root"
                )
    return {
        "status": "READY" if not errors else "BLOCKED",
        "operator_root": str(operator_root),
        "legacy": {
            "workspace_root": str(legacy.workspace_root),
            "output_root": str(legacy.output_root),
            "native": legacy.native,
            "admitted_release": legacy_identity,
        },
        "native": {
            "workspace_root": str(native.workspace_root),
            "output_root": str(native.output_root),
            "native": native.native,
            "admitted_release": native_identity,
        },
        "require_admitted_release": require_admitted_release,
        "errors": errors,
        "writes_performed": False,
    }


def _run_ids(output_root: Path) -> set[str]:
    runs = output_root / "runs"
    if not runs.is_dir():
        return set()
    return {path.name for path in runs.iterdir() if path.is_dir()}


def _build_command(track: TrackSpec, args: argparse.Namespace) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "orchestration.cli",
        "daily",
        "--",
        "--output-root",
        str(track.output_root),
        "--tag",
        args.tag,
        "--execution-mode",
        args.execution_mode,
    ]
    if args.skip_harvester:
        command.append("--skip-harvester")
    if args.skip_etf:
        command.append("--skip-etf")
    if args.use_horizon_sample:
        command.append("--use-horizon-sample")
    if args.force_weekly:
        command.append("--force-weekly")
    return command


def _run_track(
    track: TrackSpec,
    args: argparse.Namespace,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    before = _run_ids(track.output_root)
    env = os.environ.copy()
    env.update(
        {
            "SYSTEM_WORKSPACE_ROOT": str(track.workspace_root),
            "SYSTEM_ROOT": str(track.workspace_root),
            "SYSTEM_ORCHESTRATOR": "dagster",
            "SYSTEM_GENERATION_MODE": "1",
            "SYSTEM_USE_LEGACY_DAILY_RUN": "0",
            "SYSTEM_USE_NATIVE_DAILY_ASSETS": "1" if track.native else "0",
            "SYSTEM_USE_NATIVE_FILE_BOUNDARIES": "1" if track.native else "0",
            "SYSTEM_RUN_ORIGIN": "dual_track_operator",
            "DAILY_OUTPUT_ROOT": str(track.output_root),
            "PYTHONPATH": os.pathsep.join(
                [
                    str(track.workspace_root),
                    str(track.workspace_root / "packages" / "orchestration"),
                    env.get("PYTHONPATH", ""),
                ]
            ).rstrip(os.pathsep),
        }
    )
    command = _build_command(track, args)
    try:
        completed = runner(
            command,
            cwd=str(track.workspace_root),
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=args.timeout_seconds or None,
        )
        runner_error = None
    except (OSError, subprocess.SubprocessError) as exc:
        completed = None
        runner_error = f"{type(exc).__name__}: {exc}"
    after = _run_ids(track.output_root)
    new_ids = sorted(after - before)
    run_dir: Path | None = None
    if len(new_ids) == 1:
        run_dir = track.output_root / "runs" / new_ids[0]
    elif new_ids:
        candidates = [track.output_root / "runs" / run_id for run_id in new_ids]
        run_dir = max(candidates, key=lambda path: path.stat().st_mtime)
    generation: Path | None = None
    if run_dir is not None:
        committed = track.output_root / "generations" / run_dir.name
        candidate = run_dir / "publish_candidate"
        if committed.is_dir():
            generation = committed
        elif candidate.is_dir():
            generation = candidate
    return {
        "name": track.name,
        "native": track.native,
        "command": command,
        "workspace_root": str(track.workspace_root),
        "output_root": str(track.output_root),
        "exit_code": completed.returncode if completed is not None else None,
        "runner_error": runner_error,
        "run_ids_created": new_ids,
        "run_dir": str(run_dir) if run_dir else None,
        "generation": str(generation) if generation else None,
        "stdout_tail": (completed.stdout or "")[-4000:] if completed is not None else "",
        "stderr_tail": (completed.stderr or "")[-4000:] if completed is not None else "",
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
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        temporary_path.replace(path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def execute_dual_track(
    legacy: TrackSpec,
    native: TrackSpec,
    args: argparse.Namespace,
    *,
    operator_root: Path = ROOT,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    """Preflight, optionally execute both tracks, then compare their bundles."""
    observed_at = datetime.now(UTC)
    preflight = preflight_tracks(
        legacy,
        native,
        operator_root=operator_root,
        require_admitted_release=bool(args.execute),
    )
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "authority": "shadow_only",
        "promotion_allowed": PROMOTION_ALLOWED,
        "observed_at": observed_at.isoformat(),
        "observation_date": observed_at.date().isoformat(),
        "execution_requested": bool(args.execute),
        "writes_performed": False,
        "preflight": preflight,
    }
    if preflight["status"] != "READY":
        report["status"] = "INCOMPLETE"
        report["reason"] = "preflight_blocked"
        return report
    if not args.execute:
        report["status"] = "READY"
        report["reason"] = "preflight_only"
        return report

    report["writes_performed"] = True
    legacy_result = _run_track(legacy, args, runner=runner)
    native_result = _run_track(native, args, runner=runner)
    report["legacy_run"] = legacy_result
    report["native_run"] = native_result
    legacy_dir = Path(legacy_result["run_dir"]) if legacy_result["run_dir"] else None
    native_dir = Path(native_result["run_dir"]) if native_result["run_dir"] else None
    if legacy_dir is None or native_dir is None:
        report["status"] = "INCOMPLETE"
        report["reason"] = "run_bundle_missing"
        return report
    parity = compare_daily_run_bundles(
        legacy_dir,
        native_dir,
        legacy_generation=Path(legacy_result["generation"])
        if legacy_result["generation"]
        else None,
        native_generation=Path(native_result["generation"])
        if native_result["generation"]
        else None,
    )
    report["parity"] = parity
    report["status"] = parity.get("status", "INCOMPLETE")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-workspace-root", type=Path, required=True)
    parser.add_argument("--native-workspace-root", type=Path, required=True)
    parser.add_argument("--legacy-output-root", type=Path, required=True)
    parser.add_argument("--native-output-root", type=Path, required=True)
    parser.add_argument("--execute", action="store_true", help="launch both real daily paths")
    parser.add_argument("--report", type=Path, default=ROOT / "Output" / "health" / "native_current_dual_track_execution.json")
    parser.add_argument("--tag", default="wave4_dual_track")
    parser.add_argument(
        "--execution-mode",
        choices=("subprocess", "callable", "auto"),
        default="subprocess",
    )
    parser.add_argument("--skip-harvester", action="store_true")
    parser.add_argument("--skip-etf", action="store_true")
    parser.add_argument("--use-horizon-sample", action="store_true")
    parser.add_argument("--force-weekly", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=0)
    args = parser.parse_args(argv)

    legacy = TrackSpec(
        name="legacy",
        workspace_root=_resolve(args.legacy_workspace_root),
        output_root=_resolve(args.legacy_output_root),
        native=False,
    )
    native = TrackSpec(
        name="native",
        workspace_root=_resolve(args.native_workspace_root),
        output_root=_resolve(args.native_output_root),
        native=True,
    )
    report = execute_dual_track(legacy, native, args)
    output_path = args.report if args.report.is_absolute() else ROOT / args.report
    _write_json_atomically(output_path, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] in {"READY", "MATCH"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
