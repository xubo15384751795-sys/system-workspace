from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from system_runtime.context import RuntimeContext

SCHEMA_VERSION = "1.0"


class ManifestValidationError(ValueError):
    """Raised when a dataset manifest does not satisfy the frozen contract."""


def contracts_dir() -> Path:
    return RuntimeContext.current_context().workspace / "packages" / "harvester" / "contracts"


def schema_path() -> Path:
    return contracts_dir() / "dataset_manifest.schema.json"


def load_schema() -> dict[str, Any]:
    return _read_json(schema_path())


def build_manifest(
    *,
    dataset_id: str,
    release_id: str,
    as_of_date: str,
    vintage_date: str,
    source: dict[str, Any],
    data_file: dict[str, Any],
    columns: list[dict[str, Any]],
    time_coverage: dict[str, Any],
    provenance_path: str,
    dataset_revision: int = 1,
    quality_report_path: str | None = None,
    lineage: dict[str, Any] | None = None,
    provider_outcome: dict[str, Any] | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": dataset_id,
        "dataset_revision": dataset_revision,
        "release_id": release_id,
        "as_of_date": as_of_date,
        "vintage_date": vintage_date,
        "source": source,
        "data_file": data_file,
        "columns": columns,
        "time_coverage": time_coverage,
        "lineage": lineage or {"provenance_path": provenance_path},
    }
    if quality_report_path is not None:
        manifest["quality_report_path"] = quality_report_path
    if provider_outcome is not None:
        manifest["provider_outcome"] = provider_outcome
    if notes is not None:
        manifest["notes"] = notes

    validate_manifest(manifest)
    return manifest


def validate_manifest(manifest: dict[str, Any], schema: dict[str, Any] | None = None) -> None:
    validator = Draft202012Validator(schema or load_schema(), format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(manifest), key=lambda error: list(error.path))
    if errors:
        details = "; ".join(_format_error(error) for error in errors)
        raise ManifestValidationError(f"dataset manifest failed validation: {details}")


def load_manifest(path: Path | str) -> dict[str, Any]:
    payload = _read_json(Path(path))
    if not isinstance(payload, dict):
        raise ManifestValidationError(f"dataset manifest must be a JSON object: {path}")
    validate_manifest(payload)
    return payload


def write_manifest(manifest: dict[str, Any], path: Path | str) -> None:
    validate_manifest(manifest)
    _write_json(Path(path), manifest)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ManifestValidationError(f"JSON payload must be an object: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _format_error(error: Any) -> str:
    location = ".".join(str(part) for part in error.absolute_path) or "<root>"
    return f"{location}: {error.message}"


__all__ = [
    "ManifestValidationError",
    "build_manifest",
    "load_manifest",
    "load_schema",
    "schema_path",
    "validate_manifest",
    "write_manifest",
]
