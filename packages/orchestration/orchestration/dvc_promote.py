"""DVC-backed promote helpers for Harvester releases and snapshots.

Keeps the existing symlink/atomic-replace semantics as the runtime pointer,
and records a DVC-tracked sidecar so durable Data/ artifacts are versioned.
"""
from __future__ import annotations

import json
import logging
import os
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
    """Ensure a local DVC remote under Data/.dvc_cache exists."""
    cache = root / "Data" / ".dvc_cache"
    cache.mkdir(parents=True, exist_ok=True)
    dvc_dir = root / ".dvc"
    if not dvc_dir.exists():
        init = _run_dvc(["init", "--no-scm", "-q"], cwd=root)
        if init.returncode != 0:
            logger.warning("dvc init failed: %s", init.stderr.strip())
            return cache
    remote = _run_dvc(
        ["remote", "add", "-d", "localcache", str(cache), "-f"],
        cwd=root,
    )
    if remote.returncode != 0:
        logger.debug("dvc remote add: %s", remote.stderr.strip())
    return cache


def record_release_pointer(
    *,
    exports_root: Path,
    release_id: str,
    root: Path = ROOT,
) -> dict[str, Any]:
    """After symlink latest -> release_id, write/track a DVC pointer artifact."""
    payload = {
        "schema_version": "dvc_release_pointer.v1",
        "release_id": release_id,
        "exports_root": str(exports_root),
        "latest": str(exports_root / "latest"),
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "engine": "dvc",
    }
    meta_dir = exports_root / ".dvc_meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    pointer_path = meta_dir / "latest_pointer.json"
    pointer_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    if not dvc_enabled():
        payload["dvc_tracked"] = False
        return payload

    try:
        ensure_local_remote(root=root)
        add = _run_dvc(["add", str(pointer_path), "-q"], cwd=root)
        payload["dvc_tracked"] = add.returncode == 0
        if add.returncode != 0:
            payload["dvc_error"] = (add.stderr or add.stdout or "").strip()[:500]
            logger.warning("dvc add failed for release pointer: %s", payload["dvc_error"])
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
    payload = {
        "schema_version": "dvc_snapshot_pointer.v1",
        "snapshot_id": snapshot_id,
        "snapshot_path": str(snapshot_path),
        "index_path": str(index_path),
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "engine": "dvc",
    }
    meta_path = index_path.parent / ".dvc_meta" / "latest_snapshot_pointer.json"
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if not dvc_enabled():
        payload["dvc_tracked"] = False
        return payload
    try:
        ensure_local_remote(root=root)
        add = _run_dvc(["add", str(meta_path), "-q"], cwd=root)
        payload["dvc_tracked"] = add.returncode == 0
        if add.returncode != 0:
            payload["dvc_error"] = (add.stderr or add.stdout or "").strip()[:500]
    except FileNotFoundError:
        payload["dvc_tracked"] = False
        payload["dvc_error"] = "dvc_not_installed"
    return payload
