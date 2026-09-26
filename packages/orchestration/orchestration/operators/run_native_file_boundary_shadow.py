#!/usr/bin/env python3
"""Compare generation-local native file boundaries with legacy writers.

The command runs the registry-tagged current-surface writers twice, using the
same read-only workspace inputs but two different temporary generation roots:

* the native adapter calls the pure builder plus its explicit writer;
* the legacy side calls the registry ``future_callable`` entry point.

Neither side is allowed to write ``Output/current``.  The report is evidence
for the Wave 4 file-boundary migration only; it never enables a Dagster job,
changes a publication pointer, or grants promotion authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import yaml

from orchestration.native_file_boundaries import (
    execute_native_file_boundary,
    select_native_file_boundary_steps,
)
from verity.runtime.runtime_io import ROOT

DEFAULT_REPORT = ROOT / "Output" / "state" / "health" / "native_file_boundary_shadow.json"
_TIMESTAMP = re.compile(
    r"\b20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)\b"
)
_INPUT_SURFACES = ("current", "judgment", "trade_decision", "quality")


def _surface_fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    if not path.exists():
        return "MISSING"
    for item in sorted(path.rglob("*")):
        if item.is_file():
            digest.update(str(item.relative_to(path)).encode("utf-8"))
            digest.update(item.read_bytes())
    return digest.hexdigest()


def _copy_input_surfaces(root: Path, generation_root: Path) -> None:
    """Seed both temporary generations from the same read-only inputs."""
    output_root = root / "Output"
    for name in _INPUT_SURFACES:
        source = output_root / name
        if source.exists():
            shutil.copytree(
                source.resolve(),
                generation_root / name,
                dirs_exist_ok=True,
                symlinks=False,
            )
    (generation_root / "current").mkdir(parents=True, exist_ok=True)


@contextmanager
def _generation_environment(root: Path, generation_root: Path) -> Iterator[None]:
    """Route generation-aware readers/writers to one temporary generation."""
    keys = (
        "SYSTEM_WORKSPACE_ROOT",
        "SYSTEM_ROOT",
        "SYSTEM_GENERATION_MODE",
        "SYSTEM_GENERATION_DIR",
        "CURRENT_OUTPUT_DIR",
        "DAILY_OUTPUT_ROOT",
    )
    previous = {key: os.environ.get(key) for key in keys}
    os.environ.update(
        {
            "SYSTEM_WORKSPACE_ROOT": str(root),
            "SYSTEM_ROOT": str(root),
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


def _run_legacy_callable(
    *,
    callable_spec: str,
    root: Path,
    generation_root: Path,
) -> dict[str, Any]:
    """Run one legacy writer in a temporary generation subprocess."""
    if callable_spec.count(":") != 1:
        return {"status": "invalid_callable", "callable": callable_spec}
    module_name, function_name = callable_spec.rsplit(":", 1)
    code = (
        f"from {module_name} import {function_name}; "
        f"result = {function_name}(); "
        "raise SystemExit(result if isinstance(result, int) else 0)"
    )
    environment = os.environ.copy()
    environment.update(
        {
            "SYSTEM_WORKSPACE_ROOT": str(root),
            "SYSTEM_ROOT": str(root),
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
    existing = [part for part in environment.get("PYTHONPATH", "").split(os.pathsep) if part]
    environment["PYTHONPATH"] = os.pathsep.join([*pythonpath, *existing])
    try:
        completed = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(root),
            env=environment,
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


def _canonical_file(path: Path, *, generation_root: Path | None = None) -> Any:
    if not path.is_file():
        return None
    raw = path.read_bytes()
    aliases = (
        (str(generation_root), str(generation_root.resolve()))
        if generation_root is not None
        else ()
    )
    if path.suffix.lower() == ".json":
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {"sha256": hashlib.sha256(raw).hexdigest()}

        def normalize(value: Any) -> Any:
            if isinstance(value, dict):
                return {
                    str(key): normalize(child)
                    for key, child in sorted(value.items(), key=lambda item: str(item[0]))
                    if str(key) != "generated_at"
                }
            if isinstance(value, list):
                return [normalize(child) for child in value]
            if isinstance(value, str) and generation_root is not None:
                for alias in aliases:
                    value = value.replace(alias, "<generation>")
                return value
            return value

        return normalize(payload)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return {"sha256": hashlib.sha256(raw).hexdigest()}
    if generation_root is not None:
        for alias in aliases:
            text = text.replace(alias, "<generation>")
    return _TIMESTAMP.sub("<timestamp>", text)


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _diff_values(left: Any, right: Any, *, path: str = "", limit: int = 20) -> list[dict[str, Any]]:
    """Return a small diagnostic diff without making the report enormous."""
    if limit <= 0:
        return []
    if isinstance(left, dict) and isinstance(right, dict):
        differences: list[dict[str, Any]] = []
        for key in sorted(set(left) | set(right), key=str):
            child_path = f"{path}.{key}" if path else str(key)
            if key not in left or key not in right:
                differences.append({"path": child_path, "native": left.get(key), "legacy": right.get(key)})
            else:
                differences.extend(
                    _diff_values(left[key], right[key], path=child_path, limit=limit - len(differences))
                )
            if len(differences) >= limit:
                break
        return differences[:limit]
    if isinstance(left, list) and isinstance(right, list):
        differences = []
        for index, (native_item, legacy_item) in enumerate(zip(left, right, strict=False)):
            differences.extend(
                _diff_values(
                    native_item,
                    legacy_item,
                    path=f"{path}[{index}]",
                    limit=limit - len(differences),
                )
            )
            if len(differences) >= limit:
                break
        if len(left) != len(right) and len(differences) < limit:
            differences.append({"path": path, "native_length": len(left), "legacy_length": len(right)})
        return differences[:limit]
    if left != right:
        return [{"path": path, "native": left, "legacy": right}]
    return []


def _relative_output_paths(paths: list[str], generation_root: Path) -> list[str]:
    current = (generation_root / "current").resolve()
    relative: list[str] = []
    for raw_path in paths:
        path = Path(raw_path).resolve()
        try:
            relative.append(str(path.relative_to(current)))
        except ValueError:
            relative.append(str(path))
    return sorted(set(relative))


def _compare_files(
    native_current: Path,
    legacy_current: Path,
    *,
    native_generation: Path,
    legacy_generation: Path,
    relative_paths: list[str],
) -> list[dict[str, Any]]:
    comparisons: list[dict[str, Any]] = []
    for relative in relative_paths:
        native_path = native_current / relative
        legacy_path = legacy_current / relative
        native_payload = _canonical_file(native_path, generation_root=native_generation)
        legacy_payload = _canonical_file(legacy_path, generation_root=legacy_generation)
        status = (
            "MATCH"
            if native_payload is not None and native_payload == legacy_payload
            else "MISMATCH"
        )
        item: dict[str, Any] = {
            "path": relative,
            "status": status,
            "native_present": native_payload is not None,
            "legacy_present": legacy_payload is not None,
        }
        if native_payload is not None:
            item["native_digest"] = _canonical_digest(native_payload)
        if legacy_payload is not None:
            item["legacy_digest"] = _canonical_digest(legacy_payload)
        if status == "MISMATCH":
            item["differences"] = _diff_values(native_payload, legacy_payload)
        comparisons.append(item)
    return comparisons


def _load_registry(root: Path) -> dict[str, Any]:
    path = root / "governance" / "daily_pipeline_registry.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("pipeline registry must be a mapping")
    return payload


def run_shadow(*, root: Path = ROOT) -> dict[str, Any]:
    """Run the eleven current-surface boundaries against identical inputs."""
    root = root.resolve()
    document = _load_registry(root)
    selected_ids = select_native_file_boundary_steps(document)
    specs = document.get("steps") or {}
    ordered = sorted(
        selected_ids,
        key=lambda step_id: float((specs[step_id] or {}).get("order") or 0),
    )
    current_before = _surface_fingerprint(root / "Output" / "current")
    step_reports: dict[str, Any] = {}

    with tempfile.TemporaryDirectory(prefix="native-file-boundary-shadow-") as temporary:
        temporary_root = Path(temporary)
        native_generation = temporary_root / "native"
        legacy_generation = temporary_root / "legacy"
        _copy_input_surfaces(root, native_generation)
        _copy_input_surfaces(root, legacy_generation)

        for step_id in ordered:
            spec = specs[step_id] or {}
            execution = spec.get("execution") or {}
            native_result: dict[str, Any]
            with _generation_environment(root, native_generation):
                native_result = execute_native_file_boundary(step_id)
            relative_paths = _relative_output_paths(
                list(native_result.get("output_paths") or []),
                native_generation,
            )
            legacy_result = _run_legacy_callable(
                callable_spec=str(execution.get("future_callable") or ""),
                root=root,
                generation_root=legacy_generation,
            )
            file_comparisons = _compare_files(
                native_generation / "current",
                legacy_generation / "current",
                native_generation=native_generation,
                legacy_generation=legacy_generation,
                relative_paths=relative_paths,
            )
            if native_result.get("status") != "success":
                status = "NATIVE_ERROR"
            elif legacy_result.get("status") != "success":
                status = "LEGACY_ERROR"
            elif all(item["status"] == "MATCH" for item in file_comparisons):
                status = "MATCH"
            else:
                status = "MISMATCH"
            step_reports[step_id] = {
                "status": status,
                "failure_behavior": spec.get("failure_behavior"),
                "native": native_result,
                "legacy": legacy_result,
                "outputs": file_comparisons,
            }

    current_after = _surface_fingerprint(root / "Output" / "current")
    statuses = [str(item.get("status")) for item in step_reports.values()]
    if current_before != current_after:
        overall = "MISMATCH"
    elif any(status == "MISMATCH" for status in statuses):
        overall = "MISMATCH"
    elif any(status in {"NATIVE_ERROR", "LEGACY_ERROR"} for status in statuses):
        overall = "INCOMPLETE"
    elif statuses and all(status == "MATCH" for status in statuses):
        overall = "MATCH"
    else:
        overall = "NO_DATA"
    return {
        "schema_version": "system.orchestration_native_file_boundary_shadow.v1",
        "status": overall,
        "authority": "shadow_only",
        "promotion_allowed": False,
        "execution_mode": "same_inputs_temporary_generations",
        "selected_steps": ordered,
        "step_count": len(ordered),
        "steps": step_reports,
        "workspace_current_unchanged": current_before == current_after,
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
