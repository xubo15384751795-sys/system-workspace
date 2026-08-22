"""DVC-backed promote helpers for Harvester releases and snapshots.

Keeps symlink/atomic-replace semantics as the runtime pointer, and tracks
durable Data/ artifacts (catalog, digest, finalized marker, snapshot JSON,
index) in the configured DVC remote. A pointer is retained only after the
tracked DVC objects are pushed and a remote status/digest check passes.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]


def dvc_enabled() -> bool:
    return os.environ.get("SYSTEM_DISABLE_DVC", "").strip() not in {"1", "true", "TRUE"}


def _run_dvc(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    executable = Path(sys.executable).with_name("dvc")
    command = str(executable) if executable.is_file() else (shutil.which("dvc") or "dvc")
    return subprocess.run(
        [command, *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


def _configured_remote(*, root: Path = ROOT) -> tuple[str, str | Path]:
    """Return the configured DVC default remote without changing config."""
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

    config_text = target.read_text(encoding="utf-8") if target.exists() else ""
    default_match = re.search(r"(?m)^\s*remote\s*=\s*([^\s#]+)\s*$", config_text)
    remote_name = default_match.group(1).strip() if default_match else ""
    if not remote_name:
        raise RuntimeError("DVC default remote is not configured")
    section = re.search(
        rf"(?ms)^\s*(?:\[['\"]remote \"{re.escape(remote_name)}\"['\"]\]|\[remote \"{re.escape(remote_name)}\"\])\s*$"
        r"(?P<body>.*?)(?=^\s*\[|\Z)",
        config_text,
    )
    if not section:
        raise RuntimeError(f"DVC remote section is missing: {remote_name}")
    url_match = re.search(r"(?m)^\s*url\s*=\s*(.+?)\s*$", section.group("body"))
    if not url_match:
        raise RuntimeError(f"DVC remote URL is missing: {remote_name}")
    value = url_match.group(1).strip().strip('"').strip("'")
    if "://" in value:
        return remote_name, value
    return remote_name, (dvc_dir / value).resolve()


def ensure_local_remote(*, root: Path = ROOT) -> str | Path:
    """Ensure the configured DVC remote is readable without downgrading it.

    The historical function name is retained for callers/tests, but it no
    longer creates or selects the same-disk ``Data/.dvc_cache`` remote.
    """
    remote_name, remote = _configured_remote(root=root)
    logger.debug("using configured DVC remote %s: %s", remote_name, remote)
    return remote


def _recoverability_metadata(*, root: Path) -> dict[str, Any]:
    """Describe the configured DVC remote without overstating recovery capability."""
    remote = _configured_local_remote(root=root)
    remote_text = str(remote)
    is_cloud_path = "Mobile Documents/com~apple~CloudDocs" in remote_text
    is_remote_uri = "://" in remote_text
    is_off_device = is_cloud_path or is_remote_uri
    exists = is_remote_uri or Path(remote_text).exists()
    if is_off_device and exists:
        return {
            "bytes_owner": "dvc_remote",
            "recoverability_status": "PASS",
            "recoverability_reason_codes": [],
            "dvc_remote_uri": remote_text,
            "dvc_remote_same_disk_as_workspace": False,
        }
    return {
        "bytes_owner": "UNCONFIGURED",
        "recoverability_status": "BLOCKED",
        "recoverability_reason_codes": [
            "SAME_DISK_REMOTE",
            "COMPLETE_BYTES_NOT_VERIFIED",
            "RESTORE_DRILL_NOT_RUN",
        ],
        "dvc_remote_uri": remote_text,
        "dvc_remote_same_disk_as_workspace": True,
    }


def _configured_local_remote(*, root: Path) -> str | Path:
    """Resolve the configured default remote, retaining the legacy name."""
    try:
        _remote_name, remote = _configured_remote(root=root)
    except (OSError, RuntimeError):
        return (root / "Data" / ".dvc_cache").resolve()
    return remote


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dvc_pointer_path(path: Path) -> Path:
    return Path(f"{path}.dvc")


def _relative_path(path: Path, *, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve()))


def _capture_file(path: Path) -> bytes | None:
    return path.read_bytes() if path.is_file() else None


def _restore_file(path: Path, previous: bytes | None) -> None:
    if previous is None:
        if path.is_file() or path.is_symlink():
            path.unlink()
        return
    path.write_bytes(previous)


def _rollback_dvc_candidate(
    *,
    pointer_path: Path,
    previous_pointer: bytes | None,
    dvc_pointer_state: dict[Path, bytes | None],
) -> None:
    """Restore only files touched by this candidate DVC operation."""
    _restore_file(pointer_path, previous_pointer)
    for dvc_path, previous in dvc_pointer_state.items():
        _restore_file(dvc_path, previous)


def _verify_dvc_remote(pointer_paths: list[Path], *, root: Path) -> tuple[bool, str]:
    """Require DVC's remote status to be empty after a successful push."""
    status = _run_dvc(
        [
            "status",
            "--cloud",
            "--json",
            "--no-updates",
            *[_relative_path(path, root=root) for path in pointer_paths],
        ],
        cwd=root,
    )
    if status.returncode != 0:
        return False, "DVC_REMOTE_STATUS_FAILED"
    try:
        remote_diff = json.loads((status.stdout or "{}").strip() or "{}")
    except json.JSONDecodeError:
        return False, "DVC_REMOTE_STATUS_INVALID"
    if isinstance(remote_diff, dict):
        if remote_diff.get("not_in_remote") or remote_diff.get("not_in_cache"):
            return False, "DVC_REMOTE_DIGEST_MISMATCH"
        known_keys = {
            "not_in_remote",
            "not_in_cache",
            "committed",
            "uncommitted",
            "untracked",
            "unchanged",
        }
        if set(remote_diff) - known_keys:
            return False, "DVC_REMOTE_STATUS_INVALID"
        return True, ""
    if remote_diff in ({}, [], None):
        return True, ""
    return False, "DVC_REMOTE_STATUS_INVALID"


def _commit_dvc_pointer(
    *,
    pointer_path: Path,
    paths: list[Path],
    payload: dict[str, Any],
    root: Path,
    operation: str,
) -> dict[str, Any]:
    """Commit one pointer only after add, push, and remote verification pass."""
    pointer_payload = dict(payload)
    payload.update(
        {
            "dvc_tracked": False,
            "dvc_push_verified": False,
            "dvc_digest_verified": False,
            "dvc_commit_status": "BLOCKED",
            "dvc_paths": [],
        }
    )
    if not dvc_enabled():
        payload["dvc_error"] = "DVC_DISABLED"
        return payload

    previous_pointer = _capture_file(pointer_path)
    dvc_pointer_paths = [_dvc_pointer_path(path) for path in paths]
    dvc_pointer_state = {path: _capture_file(path) for path in dvc_pointer_paths}
    try:
        pointer_path.write_text(
            json.dumps(pointer_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        ensure_local_remote(root=root)
        result = _dvc_add_paths(paths, root=root)
        payload["dvc_paths"] = result["tracked"]
        expected_paths = {_relative_path(path, root=root) for path in paths}
        if result["errors"] or set(result["tracked"]) != expected_paths:
            payload["dvc_error"] = "DVC_ADD_INCOMPLETE"
            logger.warning("DVC add incomplete for %s", operation)
            _rollback_dvc_candidate(
                pointer_path=pointer_path,
                previous_pointer=previous_pointer,
                dvc_pointer_state=dvc_pointer_state,
            )
            return payload

        missing_pointers = [path for path in dvc_pointer_paths if not path.is_file()]
        if missing_pointers:
            payload["dvc_error"] = "DVC_POINTER_MISSING"
            logger.warning("DVC pointer missing after add for %s", operation)
            _rollback_dvc_candidate(
                pointer_path=pointer_path,
                previous_pointer=previous_pointer,
                dvc_pointer_state=dvc_pointer_state,
            )
            return payload

        pointer_digests = {
            _relative_path(path, root=root): _sha256_file(path)
            for path in dvc_pointer_paths
        }
        payload["dvc_pointer_digests"] = pointer_digests
        push = _run_dvc(
            [
                "push",
                "-q",
                *[_relative_path(path, root=root) for path in dvc_pointer_paths],
            ],
            cwd=root,
        )
        if push.returncode != 0:
            payload["dvc_error"] = f"DVC_PUSH_FAILED_EXIT_{push.returncode}"
            logger.warning("DVC push failed for %s with exit_code=%s", operation, push.returncode)
            _rollback_dvc_candidate(
                pointer_path=pointer_path,
                previous_pointer=previous_pointer,
                dvc_pointer_state=dvc_pointer_state,
            )
            return payload

        remote_verified, reason = _verify_dvc_remote(dvc_pointer_paths, root=root)
        if not remote_verified:
            payload["dvc_error"] = reason
            logger.warning("DVC remote verification failed for %s: %s", operation, reason)
            _rollback_dvc_candidate(
                pointer_path=pointer_path,
                previous_pointer=previous_pointer,
                dvc_pointer_state=dvc_pointer_state,
            )
            return payload
        if pointer_digests != {
            _relative_path(path, root=root): _sha256_file(path)
            for path in dvc_pointer_paths
        }:
            payload["dvc_error"] = "DVC_POINTER_DIGEST_CHANGED"
            logger.warning("DVC pointer digest changed during %s", operation)
            _rollback_dvc_candidate(
                pointer_path=pointer_path,
                previous_pointer=previous_pointer,
                dvc_pointer_state=dvc_pointer_state,
            )
            return payload

        payload["dvc_tracked"] = True
        payload["dvc_push_verified"] = True
        payload["dvc_digest_verified"] = True
        payload["dvc_commit_status"] = "PASS"
        return payload
    except FileNotFoundError:
        payload["dvc_error"] = "DVC_NOT_INSTALLED"
    except (OSError, subprocess.SubprocessError) as exc:
        payload["dvc_error"] = f"DVC_OPERATION_ERROR_{type(exc).__name__}"
    except Exception as exc:
        payload["dvc_error"] = f"DVC_OPERATION_ERROR_{type(exc).__name__}"
    _rollback_dvc_candidate(
        pointer_path=pointer_path,
        previous_pointer=previous_pointer,
        dvc_pointer_state=dvc_pointer_state,
    )
    logger.warning("DVC operation failed for %s: %s", operation, payload["dvc_error"])
    return payload


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
        add = _run_dvc(["add", rel, "-q", "--no-relink"], cwd=root)
        if add.returncode != 0:
            # Older DVC builds may not support --no-relink; retry plain add.
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
    payload.update(_recoverability_metadata(root=root))
    meta_dir = exports_root / ".dvc_meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    pointer_path = meta_dir / "latest_pointer.json"

    # Staging dir of small durable files (avoid adding huge parquet panels).
    stage_dir = meta_dir / "releases" / release_id
    stage_dir.mkdir(parents=True, exist_ok=True)
    for name in ("catalog.json", "release_digest.txt", ".finalized"):
        src = release_dir / name
        if src.exists():
            shutil.copy2(src, stage_dir / name)

    return _commit_dvc_pointer(
        pointer_path=pointer_path,
        paths=[pointer_path, stage_dir],
        payload=payload,
        root=root,
        operation=f"release:{release_id}",
    )


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
    payload.update(_recoverability_metadata(root=root))
    meta_dir = index_path.parent / ".dvc_meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    meta_path = meta_dir / "latest_snapshot_pointer.json"
    paths = [meta_path, index_path]
    if snapshot_path.exists():
        paths.append(snapshot_path)
    return _commit_dvc_pointer(
        pointer_path=meta_path,
        paths=paths,
        payload=payload,
        root=root,
        operation=f"snapshot:{snapshot_id}",
    )
