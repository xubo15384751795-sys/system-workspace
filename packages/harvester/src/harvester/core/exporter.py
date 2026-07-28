from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from harvester.core.catalog import build_catalog, write_catalog
from harvester.core.manifest import load_manifest
from harvester.core.provenance import load_provenance


class ExportValidationError(ValueError):
    """Raised when a release cannot be finalized under the access protocol."""


class FinalizedReleaseError(RuntimeError):
    """Raised when code attempts to mutate a finalized release."""


@dataclass(frozen=True)
class FinalizeResult:
    release_id: str
    release_dir: Path
    catalog: dict[str, Any]
    dry_run: bool
    verified_datasets: int
    latest_path: Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_exports_root() -> Path:
    """Default harvester exports root.

    Phase 4.1: prefer the canonical ``Data/harvester/exports`` via
    WorkspacePaths (system_runtime.paths) over the legacy parents[3]-relative
    ``data/exports``. Falls back to the legacy path if system_runtime is not
    importable (keeps the harvester package standalone-testable).
    """
    try:
        from system_runtime.paths import WorkspacePaths

        return WorkspacePaths.discover().harvester_exports
    except Exception:
        return repo_root() / "data" / "exports"


def finalize_release(
    release_id: str,
    *,
    exports_root: Path | str | None = None,
    dry_run: bool = True,
    finalized_at: str | None = None,
) -> FinalizeResult:
    root = Path(exports_root) if exports_root is not None else default_exports_root()
    release_dir = root / release_id
    latest_path = root / "latest"

    if not release_dir.exists() or not release_dir.is_dir():
        raise ExportValidationError(f"release directory does not exist: {release_dir}")
    if (release_dir / ".finalized").exists() and not dry_run:
        raise FinalizedReleaseError(f"release is already finalized: {release_dir}")

    checked = _validate_release_inputs(release_dir, release_id)
    catalog = build_catalog(
        release_dir,
        release_id=release_id,
        finalized_at=finalized_at or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    )

    result = FinalizeResult(
        release_id=release_id,
        release_dir=release_dir,
        catalog=catalog,
        dry_run=dry_run,
        verified_datasets=checked,
        latest_path=latest_path,
    )
    if dry_run:
        return result

    _ensure_mutable(release_dir)
    write_catalog(catalog, release_dir / "catalog.json")
    _write_release_digest(release_dir)
    (release_dir / ".finalized").write_text(
        json.dumps(
            {
                "release_id": release_id,
                "finalized_at": catalog["finalized_at"],
                "verified_datasets": checked,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    _point_latest(latest_path, release_id)
    _make_read_only(release_dir)
    return result


def list_releases(exports_root: Path | str | None = None) -> list[str]:
    root = Path(exports_root) if exports_root is not None else default_exports_root()
    if not root.exists():
        return []
    return sorted(
        path.name
        for path in root.iterdir()
        if path.is_dir() and path.name != "latest" and not path.name.startswith(".")
    )


def verify_file_sha256(path: Path | str, expected_sha256: str) -> None:
    actual = sha256_file(Path(path))
    if actual != expected_sha256:
        raise ExportValidationError(f"sha256 mismatch for {path}: expected {expected_sha256}, got {actual}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_release_inputs(release_dir: Path, release_id: str) -> int:
    manifest_dir = release_dir / "manifests"
    data_dir = release_dir / "data"
    provenance_dir = release_dir / "provenance"
    for required in (manifest_dir, data_dir, provenance_dir):
        if not required.exists() or not required.is_dir():
            raise ExportValidationError(f"required release subdirectory missing: {required}")

    manifest_paths = sorted(manifest_dir.glob("*.manifest.json"))
    declared_data_paths: set[str] = set()
    for manifest_path in manifest_paths:
        manifest = load_manifest(manifest_path)
        if manifest["release_id"] != release_id:
            raise ExportValidationError(f"{manifest_path} belongs to {manifest['release_id']}, not {release_id}")
        expected_manifest_name = f"{manifest['dataset_id']}.manifest.json"
        if manifest_path.name != expected_manifest_name:
            raise ExportValidationError(f"manifest filename must be {expected_manifest_name}: {manifest_path}")

        data_path = release_dir / manifest["data_file"]["path"]
        declared_data_paths.add(data_path.relative_to(release_dir).as_posix())
        if not data_path.exists() or not data_path.is_file():
            raise ExportValidationError(f"data file missing for {manifest['dataset_id']}: {data_path}")
        if data_path.stat().st_size != manifest["data_file"]["byte_size"]:
            raise ExportValidationError(f"byte_size mismatch for {data_path}")
        verify_file_sha256(data_path, manifest["data_file"]["sha256"])

        provenance_path = release_dir / manifest["lineage"]["provenance_path"]
        if not provenance_path.exists() or not provenance_path.is_file():
            raise ExportValidationError(f"provenance file missing for {manifest['dataset_id']}: {provenance_path}")
        provenance = load_provenance(provenance_path)
        if provenance["dataset_id"] != manifest["dataset_id"]:
            raise ExportValidationError(f"provenance dataset_id mismatch for {manifest['dataset_id']}")
        if provenance["release_id"] != release_id:
            raise ExportValidationError(f"provenance release_id mismatch for {manifest['dataset_id']}")
        if provenance["checksums"]["final_sha256"] != manifest["data_file"]["sha256"]:
            raise ExportValidationError(f"provenance final_sha256 mismatch for {manifest['dataset_id']}")

        quality_report_path = manifest.get("quality_report_path")
        if quality_report_path:
            quality_path = release_dir / quality_report_path
            if not quality_path.exists():
                raise ExportValidationError(f"quality report missing for {manifest['dataset_id']}: {quality_report_path}")
            quality_report = json.loads(quality_path.read_text(encoding="utf-8"))
            if quality_report.get("status") == "failed":
                raise ExportValidationError(f"quality report failed for {manifest['dataset_id']}: {quality_report_path}")

    actual_data_paths = {
        path.relative_to(release_dir).as_posix()
        for path in data_dir.rglob("*")
        if path.is_file()
    }
    undeclared = sorted(actual_data_paths - declared_data_paths)
    if undeclared:
        raise ExportValidationError(f"undeclared data files in release: {undeclared}")

    return len(manifest_paths)


def _ensure_mutable(release_dir: Path) -> None:
    if (release_dir / ".finalized").exists():
        raise FinalizedReleaseError(f"release is already finalized: {release_dir}")


def _write_release_digest(release_dir: Path) -> None:
    lines: list[str] = []
    for path in sorted(p for p in release_dir.rglob("*") if p.is_file() and p.name != "release_digest.txt"):
        lines.append(f"{sha256_file(path)}  {path.relative_to(release_dir).as_posix()}")
    (release_dir / "release_digest.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _point_latest(latest_path: Path, release_id: str) -> None:
    temporary = latest_path.with_name(".latest.tmp")
    _remove_latest_pointer(temporary)
    try:
        temporary.symlink_to(release_id)
    except (OSError, NotImplementedError):
        # Windows without symlink privileges: fall back to directory junction
        # (mklink /J) which does not require elevated privileges for directories.
        _remove_latest_pointer(temporary)
        import subprocess
        target = latest_path.parent / release_id
        try:
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(temporary), str(target.resolve())],
                check=True, capture_output=True,
            )
        except (subprocess.CalledProcessError, OSError):
            # Last resort: marker file with release_id
            _remove_latest_pointer(temporary)
            latest_path.with_suffix(".latest.txt").write_text(release_id, encoding="utf-8")
            _remove_latest_pointer(latest_path)
            return
    # os.replace on Windows cannot atomically replace an existing directory or
    # junction; the target must be non-existent or a file. Remove first, then
    # rename. This is not atomic but is the standard workaround on Windows.
    _remove_latest_pointer(latest_path)
    os.replace(temporary, latest_path)


def _remove_latest_pointer(path: Path) -> None:
    """Remove a symlink, junction, directory-marker, or file at ``path``.

    On Windows, ``latest`` may be a directory junction (created by ``mklink /J``)
    which requires ``os.rmdir``/``Path.rmdir`` to remove, while POSIX symlinks
    use ``os.unlink``. This helper handles both without leaking permission
    errors for common cases.
    """
    if not (path.exists() or path.is_symlink()):
        return
    try:
        # Symlinks (POSIX and Windows symlinks) unlink cleanly.
        if path.is_symlink():
            path.unlink()
            return
        # On Windows, directory junctions look like directories but rmdir works.
        if path.is_dir():
            path.rmdir()
            return
        path.unlink()
    except OSError:
        # Read-only bit on Windows can block unlink/rmdir. Clear and retry once.
        try:
            path.chmod(0o777)
        except OSError:
            pass
        if path.is_symlink() or not path.is_dir():
            path.unlink(missing_ok=True)
        else:
            path.rmdir()


def _make_read_only(release_dir: Path) -> None:
    for path in sorted(release_dir.rglob("*"), reverse=True):
        if path.is_file():
            path.chmod(0o444)
        elif path.is_dir():
            path.chmod(0o555)
    release_dir.chmod(0o555)


__all__ = [
    "ExportValidationError",
    "FinalizeResult",
    "FinalizedReleaseError",
    "default_exports_root",
    "finalize_release",
    "list_releases",
    "repo_root",
    "sha256_file",
    "verify_file_sha256",
]
