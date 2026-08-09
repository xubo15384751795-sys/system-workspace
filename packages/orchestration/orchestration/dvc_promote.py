"""DVC-backed promote helpers for Harvester releases and snapshots.

Keeps symlink/atomic-replace semantics as the runtime pointer, and tracks
durable Data/ artifacts (catalog, digest, finalized marker, snapshot JSON,
index) in a local DVC remote under ``Data/.dvc_cache``.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]


def dvc_enabled() -> bool:
    return os.environ.get("SYSTEM_DISABLE_DVC", "").strip() not in {"1", "true", "TRUE"}


def _run_dvc(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["dvc", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


def ensure_local_remote(*, root: Path = ROOT) -> Path:
    """Ensure a local DVC remote under Data/.dvc_cache exists.

    Seeds a no-scm ``.dvc/config`` from ``configs/dvc/config`` so promote works
    even when ``dvc init`` cannot touch the parent git repository.
    """
    cache = root / "Data" / ".dvc_cache"
    cache.mkdir(parents=True, exist_ok=True)
    template = root / "configs" / "dvc" / "config"
    dvc_dir = root / ".dvc"
    dvc_dir.mkdir(parents=True, exist_ok=True)
    (dvc_dir / "tmp").mkdir(parents=True, exist_ok=True)
    gitignore = dvc_dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("/config.local\n/tmp\n/cache\n", encoding="utf-8")
    target = dvc_dir / "config"
    if template.exists() and (not target.exists() or "core" not in target.read_text(encoding="utf-8")):
        shutil.copy2(template, target)
    # Prefer relative remote URL so the workspace stays portable.
    rel_cache = os.path.relpath(cache, start=dvc_dir)
    remote = _run_dvc(
        ["remote", "add", "-d", "localcache", rel_cache, "-f"],
        cwd=root,
    )
    if remote.returncode != 0:
        # Fall back to writing remote into config without CLI.
        config_text = target.read_text(encoding="utf-8") if target.exists() else ""
        if 'remote "localcache"' not in config_text:
            with target.open("a", encoding="utf-8") as handle:
                handle.write(f'\n[\'remote "localcache"\']\n    url = {rel_cache}\n')
        logger.debug("dvc remote add: %s", (remote.stderr or remote.stdout or "").strip())
    return cache


def _dvc_add_paths(paths: list[Path], *, root: Path) -> dict[str, Any]:
    tracked: list[str] = []
    errors: list[str] = []
    root_resolved = root.resolve()
    for path in paths:
        if not path.exists():
            errors.append(f"missing:{path}")
            continue
        try:
            rel = str(path.resolve().relative_to(root_resolved))
        except ValueError:
            errors.append(f"outside_workspace:{path}")
            continue
        add = _run_dvc(["add", rel, "-q", "--no-commit"], cwd=root)
        if add.returncode != 0:
            # Older DVC builds may not support --no-commit; retry plain add.
            add = _run_dvc(["add", rel, "-q"], cwd=root)
        if add.returncode == 0:
            tracked.append(rel)
        else:
            errors.append((add.stderr or add.stdout or rel).strip()[:300])
    return {"tracked": tracked, "errors": errors}


def record_release_pointer(
    *,
    exports_root: Path,
    release_id: str,
    root: Path = ROOT,
) -> dict[str, Any]:
    """Track latest pointer + release manifest artifacts in DVC."""
    release_dir = exports_root / release_id
    payload: dict[str, Any] = {
        "schema_version": "dvc_release_pointer.v2",
        "release_id": release_id,
        "exports_root": str(exports_root),
        "latest": str(exports_root / "latest"),
        "release_dir": str(release_dir),
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "engine": "dvc",
    }
    meta_dir = exports_root / ".dvc_meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    pointer_path = meta_dir / "latest_pointer.json"
    pointer_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    # Staging dir of small durable files (avoid adding huge parquet panels).
    stage_dir = meta_dir / "releases" / release_id
    stage_dir.mkdir(parents=True, exist_ok=True)
    for name in ("catalog.json", "release_digest.txt", ".finalized"):
        src = release_dir / name
        if src.exists():
            shutil.copy2(src, stage_dir / name)

    if not dvc_enabled():
        payload["dvc_tracked"] = False
        return payload

    try:
        ensure_local_remote(root=root)
        result = _dvc_add_paths([pointer_path, stage_dir], root=root)
        payload["dvc_tracked"] = bool(result["tracked"]) and not result["errors"]
        payload["dvc_paths"] = result["tracked"]
        if result["errors"]:
            payload["dvc_error"] = "; ".join(result["errors"])[:500]
            logger.warning("dvc add incomplete for release %s: %s", release_id, payload["dvc_error"])
        # Best-effort push to local remote
        _run_dvc(["push", "-q"], cwd=root)
    except FileNotFoundError:
        payload["dvc_tracked"] = False
        payload["dvc_error"] = "dvc_not_installed"
    return payload


def record_snapshot_pointer(
    *,
    snapshot_id: str,
    snapshot_path: Path,
    index_path: Path,
    root: Path = ROOT,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "dvc_snapshot_pointer.v2",
        "snapshot_id": snapshot_id,
        "snapshot_path": str(snapshot_path),
        "index_path": str(index_path),
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "engine": "dvc",
    }
    meta_dir = index_path.parent / ".dvc_meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    meta_path = meta_dir / "latest_snapshot_pointer.json"
    meta_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    if not dvc_enabled():
        payload["dvc_tracked"] = False
        return payload
    try:
        ensure_local_remote(root=root)
        paths = [meta_path, index_path]
        if snapshot_path.exists():
            paths.append(snapshot_path)
        result = _dvc_add_paths(paths, root=root)
        payload["dvc_tracked"] = bool(result["tracked"])
        payload["dvc_paths"] = result["tracked"]
        if result["errors"]:
            payload["dvc_error"] = "; ".join(result["errors"])[:500]
        _run_dvc(["push", "-q"], cwd=root)
    except FileNotFoundError:
        payload["dvc_tracked"] = False
        payload["dvc_error"] = "dvc_not_installed"
    return payload
