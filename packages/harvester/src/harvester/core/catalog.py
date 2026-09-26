from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from harvester import __version__
from harvester.core.manifest import load_manifest
from system_runtime.context import RuntimeContext


SCHEMA_VERSION = "1.0"


class CatalogValidationError(ValueError):
    """Raised when catalog.json does not satisfy the frozen contract."""


def contracts_dir() -> Path:
    return RuntimeContext.current_context().workspace / "packages" / "harvester" / "contracts"


def schema_path() -> Path:
    return contracts_dir() / "catalog.schema.json"


def load_schema() -> dict[str, Any]:
    return _read_json(schema_path())


def build_catalog(
    release_dir: Path | str,
    *,
    release_id: str | None = None,
    finalized_at: str | None = None,
    harvester_version: str = __version__,
    producer: dict[str, Any] | None = None,
    supersedes: list[str] | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    root = Path(release_dir)
    resolved_release_id = release_id or root.name
    manifest_dir = root / "manifests"
    datasets: list[dict[str, Any]] = []

    if manifest_dir.exists():
        for manifest_path in sorted(manifest_dir.glob("*.manifest.json")):
            manifest = load_manifest(manifest_path)
            data_path = manifest["data_file"]["path"]
            provenance_path = manifest["lineage"]["provenance_path"]
            entry: dict[str, Any] = {
                "dataset_id": manifest["dataset_id"],
                "dataset_revision": manifest["dataset_revision"],
                "manifest_path": manifest_path.relative_to(root).as_posix(),
                "data_path": data_path,
                "provenance_path": provenance_path,
            }
            if "quality_report_path" in manifest:
                entry["quality_report_path"] = manifest["quality_report_path"]
            if "notes" in manifest:
                entry["summary"] = manifest["notes"][:500]
            datasets.append(entry)

    catalog: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "harvester_version": harvester_version,
        "release_id": resolved_release_id,
        "finalized_at": finalized_at or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "datasets": datasets,
    }
    if producer is not None:
        catalog["producer"] = producer
    if supersedes is not None:
        catalog["supersedes"] = supersedes
    if notes is not None:
        catalog["notes"] = notes

    validate_catalog(catalog)
    return catalog


def validate_catalog(catalog: dict[str, Any], schema: dict[str, Any] | None = None) -> None:
    validator = Draft202012Validator(schema or load_schema(), format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(catalog), key=lambda error: list(error.path))
    if errors:
        details = "; ".join(_format_error(error) for error in errors)
        raise CatalogValidationError(f"catalog failed validation: {details}")


def load_catalog(path_or_release_dir: Path | str) -> dict[str, Any]:
    path = Path(path_or_release_dir)
    if path.is_dir():
        path = path / "catalog.json"
    payload = _read_json(path)
    if not isinstance(payload, dict):
        raise CatalogValidationError(f"catalog must be a JSON object: {path}")
    validate_catalog(payload)
    return payload


def write_catalog(catalog: dict[str, Any], path: Path | str) -> None:
    validate_catalog(catalog)
    _write_json(Path(path), catalog)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise CatalogValidationError(f"JSON document must be an object: {path}")
    return {str(key): value for key, value in payload.items()}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _format_error(error: Any) -> str:
    location = ".".join(str(part) for part in error.absolute_path) or "<root>"
    return f"{location}: {error.message}"


__all__ = [
    "CatalogValidationError",
    "build_catalog",
    "load_catalog",
    "load_schema",
    "schema_path",
    "validate_catalog",
    "write_catalog",
]
