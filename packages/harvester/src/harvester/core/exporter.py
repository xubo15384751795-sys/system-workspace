from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from harvester.core.catalog import build_catalog, write_catalog
from harvester.core.manifest import load_manifest
from harvester.core.observation import ObservationCoverageError, read_observation_coverage
from harvester.core.provenance import load_provenance

logger = logging.getLogger(__name__)


class ExportValidationError(ValueError):
    """Raised when a release cannot be finalized under the access protocol."""


class FinalizedReleaseError(RuntimeError):
    """Raised when code attempts to mutate a finalized release."""


_SAFE_RELEASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def validate_release_id(release_id: str) -> str:
    """Validate a release identifier before it participates in a filesystem path."""
    if not isinstance(release_id, str) or not _SAFE_RELEASE_ID.fullmatch(release_id):
        raise ExportValidationError(
            "release_id must be a single safe path component containing only "
            "letters, digits, '.', '_' or '-'"
        )
    return release_id


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

        return cast(Path, WorkspacePaths.discover().harvester_exports)
    except Exception:
        return repo_root() / "data" / "exports"


def resolve_release_dir(root: Path, release_id: str) -> Path:
    """Resolve a release directory while keeping it below the exports root."""
    root = root.expanduser().resolve()
    candidate = (root / validate_release_id(release_id)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ExportValidationError(
            f"release directory resolves outside exports root: {release_id}"
        ) from exc
    if candidate == root:
        raise ExportValidationError("release directory must not be the exports root")
    return candidate


def _resolve_release_path(release_dir: Path, relative: str, field: str) -> Path:
    """Resolve a release-relative path and reject symlink escapes."""
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts:
        raise ExportValidationError(f"{field} must be a safe relative path: {relative}")
    base = release_dir.resolve()
    candidate = (base / rel).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise ExportValidationError(
            f"{field} resolves outside release directory: {relative}"
        ) from exc
    return candidate


def finalize_release(
    release_id: str,
    *,
    exports_root: Path | str | None = None,
    dry_run: bool = True,
    finalized_at: str | None = None,
) -> FinalizeResult:
    validate_release_id(release_id)
    root = (Path(exports_root) if exports_root is not None else default_exports_root()).expanduser().resolve()
    release_dir = resolve_release_dir(root, release_id)
    latest_path = root / "latest"

    if not release_dir.exists() or not release_dir.is_dir():
        raise ExportValidationError(f"release directory does not exist: {release_dir}")
    finalized_path = _resolve_release_path(release_dir, ".finalized", ".finalized")
    if finalized_path.exists() and not dry_run:
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
    write_catalog(catalog, _resolve_release_path(release_dir, "catalog.json", "catalog.json"))
    _write_release_digest(release_dir)
    _resolve_release_path(release_dir, ".finalized", ".finalized").write_text(
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
    try:
        from orchestration.dvc_promote import record_release_pointer

        dvc_result = record_release_pointer(exports_root=root, release_id=release_id)
        if dvc_result.get("dvc_commit_status") != "PASS":
            logger.warning(
                "DVC pointer not committed for release %s: %s",
                release_id,
                dvc_result.get("dvc_error", "DVC_COMMIT_BLOCKED"),
            )
    except Exception as exc:
        # DVC recovery evidence is separate from the finalized local release,
        # but the failure must remain visible and typed.
        logger.warning(
            "DVC pointer recording failed for release %s: %s",
            release_id,
            type(exc).__name__,
            exc_info=True,
        )
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
    manifest_dir = _resolve_release_path(release_dir, "manifests", "manifests")
    data_dir = _resolve_release_path(release_dir, "data", "data")
    provenance_dir = _resolve_release_path(release_dir, "provenance", "provenance")
    for required in (manifest_dir, data_dir, provenance_dir):
        if not required.exists() or not required.is_dir():
            raise ExportValidationError(f"required release subdirectory missing: {required}")

    manifest_paths = sorted(manifest_dir.glob("*.manifest.json"))
    declared_data_paths: set[str] = set()
    for manifest_path in manifest_paths:
        manifest_path = _resolve_release_path(
            release_dir,
            manifest_path.relative_to(release_dir).as_posix(),
            "manifest path",
        )
        manifest = load_manifest(manifest_path)
        if manifest["release_id"] != release_id:
            raise ExportValidationError(f"{manifest_path} belongs to {manifest['release_id']}, not {release_id}")
        expected_manifest_name = f"{manifest['dataset_id']}.manifest.json"
        if manifest_path.name != expected_manifest_name:
            raise ExportValidationError(f"manifest filename must be {expected_manifest_name}: {manifest_path}")

        data_path = _resolve_release_path(
            release_dir,
            manifest["data_file"]["path"],
            f"data path for {manifest['dataset_id']}",
        )
        declared_data_paths.add(data_path.relative_to(release_dir).as_posix())
        if not data_path.exists() or not data_path.is_file():
            raise ExportValidationError(f"data file missing for {manifest['dataset_id']}: {data_path}")
        if data_path.stat().st_size != manifest["data_file"]["byte_size"]:
            raise ExportValidationError(f"byte_size mismatch for {data_path}")
        verify_file_sha256(data_path, manifest["data_file"]["sha256"])

        actual_coverage = _actual_observation_coverage(data_path, manifest)
        if actual_coverage is not None:
            _compare_coverage(
                actual_coverage,
                manifest.get("time_coverage", {}),
                label="manifest",
                dataset_id=manifest["dataset_id"],
            )

        provenance_path = _resolve_release_path(
            release_dir,
            manifest["lineage"]["provenance_path"],
            f"provenance path for {manifest['dataset_id']}",
        )
        if not provenance_path.exists() or not provenance_path.is_file():
            raise ExportValidationError(f"provenance file missing for {manifest['dataset_id']}: {provenance_path}")
        provenance = load_provenance(provenance_path)
        if provenance["dataset_id"] != manifest["dataset_id"]:
            raise ExportValidationError(f"provenance dataset_id mismatch for {manifest['dataset_id']}")
        if provenance["release_id"] != release_id:
            raise ExportValidationError(f"provenance release_id mismatch for {manifest['dataset_id']}")
        if provenance["checksums"]["final_sha256"] != manifest["data_file"]["sha256"]:
            raise ExportValidationError(f"provenance final_sha256 mismatch for {manifest['dataset_id']}")
        if actual_coverage is not None:
            provenance_coverage = provenance.get("observation_coverage")
            if not isinstance(provenance_coverage, dict):
                raise ExportValidationError(
                    f"provenance observation coverage missing for {manifest['dataset_id']}"
                )
            _compare_coverage(
                actual_coverage,
                provenance_coverage,
                label="provenance",
                dataset_id=manifest["dataset_id"],
            )
        canonical_relpath = provenance.get("canonical_observation_path")
        if canonical_relpath:
            canonical_path = _resolve_release_path(
                release_dir,
                str(canonical_relpath),
                f"canonical observation path for {manifest['dataset_id']}",
            )
            if not canonical_path.is_file():
                raise ExportValidationError(
                    f"canonical observation sidecar missing for {manifest['dataset_id']}: {canonical_path}"
                )
            expected_count = provenance.get("canonical_observation_count")
            actual_count = 0
            try:
                from system_runtime.canonical_ids import validate_observation
            except ImportError:
                validate_observation = None
            try:
                for line in canonical_path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        record = json.loads(line)
                        if validate_observation is not None:
                            validate_observation(record)
                        actual_count += 1
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                raise ExportValidationError(
                    f"canonical observation sidecar invalid for {manifest['dataset_id']}: {canonical_path}"
                ) from exc
            if expected_count is not None and int(expected_count) != actual_count:
                raise ExportValidationError(
                    f"canonical observation count mismatch for {manifest['dataset_id']}: "
                    f"declared={expected_count}, actual={actual_count}"
                )

        canonical_chain_relpath = provenance.get("canonical_chain_path")
        if canonical_chain_relpath:
            canonical_chain_path = _resolve_release_path(
                release_dir,
                str(canonical_chain_relpath),
                f"canonical chain path for {manifest['dataset_id']}",
            )
            if not canonical_chain_path.is_file():
                raise ExportValidationError(
                    f"canonical chain sidecar missing for {manifest['dataset_id']}: {canonical_chain_path}"
                )
            expected_chain_count = provenance.get("canonical_chain_count")
            actual_chain_count = 0
            try:
                from system_runtime.canonical_ids import validate_chain
            except ImportError:
                validate_chain = None
            try:
                for line in canonical_chain_path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        record = json.loads(line)
                        if validate_chain is not None:
                            validate_chain(record)
                        actual_chain_count += 1
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                raise ExportValidationError(
                    f"canonical chain sidecar invalid for {manifest['dataset_id']}: {canonical_chain_path}"
                ) from exc
            if expected_chain_count is not None and int(expected_chain_count) != actual_chain_count:
                raise ExportValidationError(
                    f"canonical chain count mismatch for {manifest['dataset_id']}: "
                    f"declared={expected_chain_count}, actual={actual_chain_count}"
                )

        measurement_spec_relpath = provenance.get("measurement_spec_path")
        if measurement_spec_relpath:
            measurement_spec_path = _resolve_release_path(
                release_dir,
                str(measurement_spec_relpath),
                f"measurement spec path for {manifest['dataset_id']}",
            )
            if not measurement_spec_path.is_file():
                raise ExportValidationError(
                    f"measurement spec missing for {manifest['dataset_id']}: {measurement_spec_path}"
                )
            try:
                from harvester.core.proxy_measurement import load_measurement_spec

                measurement_spec = load_measurement_spec(measurement_spec_path)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                raise ExportValidationError(
                    f"measurement spec invalid for {manifest['dataset_id']}: {measurement_spec_path}"
                ) from exc
            if measurement_spec.get("dataset_id") != manifest["dataset_id"]:
                raise ExportValidationError(
                    f"measurement spec dataset_id mismatch for {manifest['dataset_id']}"
                )
            if measurement_spec.get("release_id") != release_id:
                raise ExportValidationError(
                    f"measurement spec release_id mismatch for {manifest['dataset_id']}"
                )
            declared_spec_version = provenance.get("measurement_spec_version")
            if not declared_spec_version:
                raise ExportValidationError(
                    f"measurement spec version missing for {manifest['dataset_id']}"
                )
            if declared_spec_version and measurement_spec.get("schema_version") != declared_spec_version:
                raise ExportValidationError(
                    f"measurement spec version mismatch for {manifest['dataset_id']}"
                )

        quality_report_path = manifest.get("quality_report_path")
        if quality_report_path:
            quality_path = _resolve_release_path(
                release_dir,
                quality_report_path,
                f"quality report path for {manifest['dataset_id']}",
            )
            if not quality_path.exists():
                raise ExportValidationError(f"quality report missing for {manifest['dataset_id']}: {quality_report_path}")
            quality_report = json.loads(quality_path.read_text(encoding="utf-8"))
            if quality_report.get("status") == "failed":
                raise ExportValidationError(f"quality report failed for {manifest['dataset_id']}: {quality_report_path}")
            if actual_coverage is not None:
                quality_coverage = quality_report.get("observation_coverage")
                if not isinstance(quality_coverage, dict):
                    raise ExportValidationError(
                        f"quality observation coverage missing for {manifest['dataset_id']}"
                    )
                _compare_coverage(
                    actual_coverage,
                    quality_coverage,
                    label="quality",
                    dataset_id=manifest["dataset_id"],
                )

    actual_data_paths = {
        path.relative_to(release_dir).as_posix()
        for path in data_dir.rglob("*")
        if path.is_file()
    }
    undeclared = sorted(actual_data_paths - declared_data_paths)
    if undeclared:
        raise ExportValidationError(f"undeclared data files in release: {undeclared}")

    return len(manifest_paths)


def _actual_observation_coverage(data_path: Path, manifest: dict[str, Any]) -> dict[str, Any] | None:
    time_coverage = manifest.get("time_coverage", {})
    time_column = time_coverage.get("time_column")
    if not time_column:
        return None
    try:
        return cast(dict[str, Any], read_observation_coverage(
            data_path,
            file_format=str(manifest["data_file"]["format"]),
            time_column=str(time_column),
        ))
    except ObservationCoverageError as exc:
        raise ExportValidationError(
            f"observation coverage unreadable for {manifest['dataset_id']}: {exc}"
        ) from exc


def _compare_coverage(
    actual: dict[str, Any],
    declared: dict[str, Any],
    *,
    label: str,
    dataset_id: str,
) -> None:
    for field in ("start", "end", "time_column"):
        expected = declared.get(field)
        observed = actual.get(field)
        if expected != observed:
            raise ExportValidationError(
                f"{label} observation coverage mismatch for {dataset_id}: "
                f"{field} expected={expected!r}, actual={observed!r}"
            )


def _ensure_mutable(release_dir: Path) -> None:
    if _resolve_release_path(release_dir, ".finalized", ".finalized").exists():
        raise FinalizedReleaseError(f"release is already finalized: {release_dir}")


def _write_release_digest(release_dir: Path) -> None:
    lines: list[str] = []
    for path in sorted(p for p in release_dir.rglob("*") if p.is_file() and p.name != "release_digest.txt"):
        relative = path.relative_to(release_dir).as_posix()
        resolved = _resolve_release_path(release_dir, relative, "release artifact")
        lines.append(f"{sha256_file(resolved)}  {relative}")
    _resolve_release_path(release_dir, "release_digest.txt", "release_digest.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def _point_latest(latest_path: Path, release_id: str) -> None:
    temporary = latest_path.with_name(".latest.tmp")
    if temporary.exists() or temporary.is_symlink():
        temporary.unlink()
    temporary.symlink_to(release_id)
    os.replace(temporary, latest_path)


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
    "resolve_release_dir",
    "sha256_file",
    "validate_release_id",
    "verify_file_sha256",
]
