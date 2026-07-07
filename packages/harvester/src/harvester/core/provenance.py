from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


SCHEMA_VERSION = "1.0"


class ProvenanceValidationError(ValueError):
    """Raised when provenance does not satisfy the frozen contract."""


class ProvenanceAppendError(RuntimeError):
    """Raised when an append-only provenance write would overwrite content."""


def contracts_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "contracts"


def schema_path() -> Path:
    return contracts_dir() / "provenance.schema.json"


def load_schema() -> dict[str, Any]:
    return _read_json(schema_path())


def record_provenance(
    path: Path | str,
    provenance: dict[str, Any],
    *,
    append: bool = True,
) -> dict[str, Any]:
    target = Path(path)
    validate_provenance(provenance)
    if target.exists():
        existing = load_provenance(target)
        if not append:
            raise ProvenanceAppendError(f"provenance already exists: {target}")
        merged = dict(existing)
        merged["transformations"] = [
            *existing.get("transformations", []),
            *provenance.get("transformations", []),
        ]
        merged["checksums"] = provenance["checksums"]
        if "environment" in provenance:
            merged["environment"] = provenance["environment"]
        if "notes" in provenance:
            timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            previous = existing.get("notes", "")
            merged["notes"] = f"{previous}\n[{timestamp}] {provenance['notes']}".strip()
        validate_provenance(merged)
        _write_json(target, merged)
        return merged

    _write_json(target, provenance)
    return provenance


def build_provenance(
    *,
    dataset_id: str,
    release_id: str,
    acquisition: dict[str, Any],
    checksums: dict[str, Any],
    transformations: list[dict[str, Any]] | None = None,
    dataset_revision: int = 1,
    environment: dict[str, Any] | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    provenance: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": dataset_id,
        "dataset_revision": dataset_revision,
        "release_id": release_id,
        "acquisition": acquisition,
        "transformations": transformations or [],
        "checksums": checksums,
    }
    if environment is not None:
        provenance["environment"] = environment
    if notes is not None:
        provenance["notes"] = notes
    validate_provenance(provenance)
    return provenance


def validate_provenance(provenance: dict[str, Any], schema: dict[str, Any] | None = None) -> None:
    validator = Draft202012Validator(schema or load_schema(), format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(provenance), key=lambda error: list(error.path))
    if errors:
        details = "; ".join(_format_error(error) for error in errors)
        raise ProvenanceValidationError(f"provenance failed validation: {details}")


def load_provenance(path: Path | str) -> dict[str, Any]:
    payload = _read_json(Path(path))
    if not isinstance(payload, dict):
        raise ProvenanceValidationError(f"provenance must be a JSON object: {path}")
    validate_provenance(payload)
    return payload


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _format_error(error: Any) -> str:
    location = ".".join(str(part) for part in error.absolute_path) or "<root>"
    return f"{location}: {error.message}"


__all__ = [
    "ProvenanceAppendError",
    "ProvenanceValidationError",
    "build_provenance",
    "load_provenance",
    "load_schema",
    "record_provenance",
    "schema_path",
    "validate_provenance",
]
