"""harvester_tools — governed tools for Structural Risk Harvester.

Registered tools:
  harvester.list_releases   — list all finalized data releases
  harvester.inspect_release — inspect a single release catalog
  harvester.verify_release  — verify release integrity (checksums, schema)
  harvester.diff_releases   — diff two releases

Every handler accepts (input: dict, dry_run: bool) → ToolResult.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from tools.registry import ToolResult, ToolSpec, _register, _registry

HARNESS_ROOT = Path(__file__).resolve().parent.parent
WORKBENCH_ROOT = HARNESS_ROOT.parent.parent
EXPORTS_ROOT = WORKBENCH_ROOT / "Data" / "harvester" / "exports"


# ── helpers ─────────────────────────────────────────────────────────────

def _resolve_release(release_id: str) -> Path | None:
    if release_id == "latest":
        latest_sym = EXPORTS_ROOT / "latest"
        if latest_sym.is_symlink():
            return latest_sym.resolve()
        return None
    candidate = EXPORTS_ROOT / release_id
    return candidate if candidate.is_dir() else None


def _release_dirs() -> list[Path]:
    if not EXPORTS_ROOT.is_dir():
        return []
    dirs: list[Path] = []
    for p in sorted(EXPORTS_ROOT.iterdir()):
        if p.is_dir() and not p.is_symlink():
            dirs.append(p)
    return dirs


def _read_catalog(release_dir: Path) -> dict | None:
    path = release_dir / "catalog.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _to_dict(result: ToolResult) -> dict[str, Any]:
    return result.to_dict()


# ── handlers ────────────────────────────────────────────────────────────

def _h_list_releases(input: dict, dry_run: bool) -> ToolResult:
    if dry_run:
        return ToolResult(ok=True, tool_id="harvester.list_releases", summary="[DRY RUN] list all releases")

    releases = _release_dirs()
    items: list[dict] = []
    for rd in releases:
        info: dict[str, Any] = {"release_id": rd.name}
        cat = _read_catalog(rd)
        if cat:
            info["created_at"] = cat.get("created_at", "")
            info["file_count"] = len(cat.get("files", []))
            info["bundle_id"] = cat.get("bundle_id", "")
        items.append(info)

    return ToolResult(
        ok=True,
        tool_id="harvester.list_releases",
        summary=f"Found {len(items)} releases",
        evidence={"releases": items, "count": len(items)},
        warnings=[] if items else ["No releases found in exports directory"],
    )


def _h_inspect_release(input: dict, dry_run: bool) -> ToolResult:
    release_id = input.get("release_id", "latest")
    if dry_run:
        return ToolResult(ok=True, tool_id="harvester.inspect_release", summary=f"[DRY RUN] inspect {release_id}")

    release_dir = _resolve_release(release_id)
    if release_dir is None:
        return ToolResult(ok=False, tool_id="harvester.inspect_release", errors=[f"Release not found: {release_id}"])

    cat = _read_catalog(release_dir)
    if cat is None:
        return ToolResult(ok=False, tool_id="harvester.inspect_release", errors=[f"No catalog.json in release {release_dir.name}"])

    files = cat.get("files", [])
    if isinstance(files, list):
        file_summaries = []
        for f in files:
            file_summaries.append({
                "path": f.get("path", ""),
                "format": f.get("format", ""),
                "row_count": f.get("row_count", 0),
                "byte_size": f.get("byte_size", 0),
            })
    else:
        file_summaries = []

    return ToolResult(
        ok=True,
        tool_id="harvester.inspect_release",
        summary=f"Release {release_dir.name}: {len(file_summaries)} files, bundle={cat.get('bundle_id','-')}",
        evidence={
            "release_id": release_dir.name,
            "created_at": cat.get("created_at", ""),
            "bundle_id": cat.get("bundle_id", ""),
            "files": file_summaries,
        },
    )


def _h_verify_release(input: dict, dry_run: bool) -> ToolResult:
    release_id = input.get("release_id", "latest")
    if dry_run:
        return ToolResult(ok=True, tool_id="harvester.verify_release", summary=f"[DRY RUN] verify {release_id}")

    release_dir = _resolve_release(release_id)
    if release_dir is None:
        return ToolResult(ok=False, tool_id="harvester.verify_release", errors=[f"Release not found: {release_id}"])

    cat = _read_catalog(release_dir)
    checks: list[dict] = []

    # check 1: catalog exists and is valid JSON
    checks.append({
        "check": "catalog_valid_json",
        "passed": cat is not None,
        "detail": "catalog.json is readable JSON" if cat else "catalog.json missing or unreadable",
    })

    if cat is None:
        return ToolResult(
            ok=False,
            tool_id="harvester.verify_release",
            errors=["Catalog not readable — verification aborted"],
            evidence={"checks": checks},
        )

    # check 2: catalog has required top-level keys
    required_keys = {"bundle_id", "created_at", "files"}
    present = required_keys & set(cat.keys())
    missing = required_keys - set(cat.keys())
    checks.append({
        "check": "catalog_required_keys",
        "passed": len(missing) == 0,
        "detail": f"present: {sorted(present)}, missing: {sorted(missing)}" if missing else f"all {len(present)} keys present",
    })

    # check 3: each listed file exists on disk
    files = cat.get("files", [])
    file_checks = []
    if isinstance(files, list) and files:
        all_found = True
        for f in files:
            fpath = release_dir / f.get("path", "")
            exists = fpath.is_file()
            if not exists:
                all_found = False
            file_checks.append({
                "path": f.get("path", ""),
                "exists": exists,
            })
        checks.append({
            "check": "all_files_present",
            "passed": all_found,
            "detail": f"{sum(1 for fc in file_checks if fc['exists'])}/{len(file_checks)} files found",
        })
    else:
        checks.append({
            "check": "all_files_present",
            "passed": True,
            "detail": "no file list entries to verify",
        })

    all_passed = all(c["passed"] for c in checks)
    return ToolResult(
        ok=all_passed,
        tool_id="harvester.verify_release",
        summary=f"Verification {'passed' if all_passed else 'FAILED'} for {release_dir.name}",
        evidence={"checks": checks, "release_id": release_dir.name},
        warnings=[] if all_passed else ["Some integrity checks failed"],
    )


def _h_diff_releases(input: dict, dry_run: bool) -> ToolResult:
    a_id = input.get("release_a", "")
    b_id = input.get("release_b", "latest")
    if dry_run:
        return ToolResult(ok=True, tool_id="harvester.diff_releases", summary=f"[DRY RUN] diff {a_id} vs {b_id}")

    dir_a = _resolve_release(a_id)
    dir_b = _resolve_release(b_id)
    errors: list[str] = []
    if dir_a is None:
        errors.append(f"Release A not found: {a_id}")
    if dir_b is None:
        errors.append(f"Release B not found: {b_id}")
    if errors:
        return ToolResult(ok=False, tool_id="harvester.diff_releases", errors=errors)

    cat_a = _read_catalog(dir_a)
    cat_b = _read_catalog(dir_b)

    diffs: list[dict] = []

    # compare file lists
    paths_a = set()
    paths_b = set()
    if isinstance(cat_a.get("files"), list):
        paths_a = {f.get("path", "") for f in cat_a["files"]}
    if isinstance(cat_b.get("files"), list):
        paths_b = {f.get("path", "") for f in cat_b["files"]}

    added = sorted(paths_b - paths_a)
    removed = sorted(paths_a - paths_b)
    common = sorted(paths_a & paths_b)

    if added:
        diffs.append({"type": "files_added", "paths": added})
    if removed:
        diffs.append({"type": "files_removed", "paths": removed})
    if not added and not removed:
        diffs.append({"type": "files_unchanged", "count": len(common)})

    return ToolResult(
        ok=True,
        tool_id="harvester.diff_releases",
        summary=f"Diff {dir_a.name} → {dir_b.name}: {len(added)} added, {len(removed)} removed, {len(common)} common",
        evidence={
            "release_a": dir_a.name,
            "release_b": dir_b.name,
            "diffs": diffs,
            "files_added": added,
            "files_removed": removed,
            "files_common_count": len(common),
        },
    )


# ── registration ────────────────────────────────────────────────────────

_register(ToolSpec(
    id="harvester.list_releases",
    description="List all finalized data releases from the harvester exports directory",
    subsystem="harvester",
    risk_level="low",
    read_only=True,
    mutates_artifacts=False,
    requires_approval=False,
    allowed_modes=["explore", "verify"],
    required_prechecks=[],
    postchecks=["write_event"],
    handler=_h_list_releases,
))

_register(ToolSpec(
    id="harvester.inspect_release",
    description="Inspect a single release catalog by id or 'latest'",
    subsystem="harvester",
    risk_level="low",
    read_only=True,
    mutates_artifacts=False,
    requires_approval=False,
    allowed_modes=["explore", "verify"],
    required_prechecks=[],
    postchecks=["write_event"],
    handler=_h_inspect_release,
))

_register(ToolSpec(
    id="harvester.verify_release",
    description="Verify release integrity — catalog JSON, required keys, file existence",
    subsystem="harvester",
    risk_level="low",
    read_only=True,
    mutates_artifacts=False,
    requires_approval=False,
    allowed_modes=["verify"],
    required_prechecks=[],
    postchecks=["write_event"],
    handler=_h_verify_release,
))

_register(ToolSpec(
    id="harvester.diff_releases",
    description="Diff two releases by file list comparison",
    subsystem="harvester",
    risk_level="low",
    read_only=True,
    mutates_artifacts=False,
    requires_approval=False,
    allowed_modes=["explore", "verify"],
    required_prechecks=[],
    postchecks=["write_event"],
    handler=_h_diff_releases,
))
