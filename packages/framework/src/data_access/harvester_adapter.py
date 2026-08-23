from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from jsonschema import Draft202012Validator, FormatChecker


class HarvesterAccessError(RuntimeError):
    """Base error for Harvester protocol failures."""


class HarvesterCatalogMissingError(FileNotFoundError, HarvesterAccessError):
    def __init__(self, catalog_path: Path) -> None:
        self.catalog_path = catalog_path
        super().__init__(f"Harvester catalog is missing: {catalog_path}")


class HarvesterSchemaError(HarvesterAccessError):
    """Raised when a catalog or manifest violates the Harvester contracts."""


class HarvesterIntegrityError(HarvesterAccessError):
    """Raised when declared artifact integrity does not match bytes on disk."""


class HarvesterDatasetNotFoundError(KeyError, HarvesterAccessError):
    """Raised when a requested dataset is absent from the active catalog."""


@dataclass(frozen=True)
class HarvesterBundle:
    bundle_id: str
    catalog: dict[str, Any]
    manifest: list[dict[str, Any]]
    provenance: list[dict[str, Any]]
    source_registry: dict[str, Any]
    benchmark_panel: pd.DataFrame
    proxy_candidate_panel: pd.DataFrame
    corpus_index: pd.DataFrame
    validation_report: dict[str, Any]

    @property
    def release_id(self) -> str:
        """Alias for bundle_id — satisfies the ReleaseBundleLike protocol."""
        return self.bundle_id

    @property
    def manifests(self) -> dict[str, Any] | None:
        """Dict form of the manifest list, keyed by role.

        Satisfies the ReleaseBundleLike protocol optional field.
        """
        return {entry.get("role", ""): entry for entry in self.manifest} if self.manifest else None


class HarvesterAdapter:
    """Consume immutable Harvester artifact bundles through the access protocol."""

    backend = "harvester"

    def __init__(
        self,
        harvester_root: Path | str | None = None,
        *,
        exports_root: Path | str | None = None,
        release: str = "latest",
        catalog_file: str = "catalog.json",
        require_finalized: bool = True,
        validate_hashes: bool = True,
        validate_schema: bool = True,
        contract_root: Path | str | None = None,
    ) -> None:
        self.harvester_root = Path(harvester_root).expanduser() if harvester_root is not None else None
        self.release = release
        self.catalog_file = catalog_file
        self.require_finalized = require_finalized
        self.validate_hashes = validate_hashes
        self.validate_schema = validate_schema
        if contract_root:
            self.contract_root = Path(contract_root).expanduser()
        elif self.harvester_root is not None:
            self.contract_root = self.harvester_root / "contracts"
        else:
            raise ValueError("HarvesterAdapter requires contract_root when harvester_root is not provided")
        self.exports_root = self._resolve_exports_root(exports_root).expanduser().resolve()
        self.release_dir = self._resolve_release_dir()
        self.catalog_path = self._resolve_declared_path(
            self._safe_catalog_file(catalog_file), "catalog_file"
        )
        self.catalog = self._load_catalog()
        self.catalog_mode = "bundle" if "files" in self.catalog else "datasets"
        if self.catalog_mode == "bundle":
            self._validate_bundle_catalog()

    @property
    def current_release_id(self) -> str | None:
        """The adapter's notion of the current release identifier.

        Exposed for DataHubLite cache invalidation.  Returns the bundle_id
        directly from the resolved catalog, falling back to the release
        directory name for non-bundle catalogs.
        """
        try:
            if self.catalog_mode == "bundle":
                return str(self.catalog.get("bundle_id", self.release_dir.name))
            return str(self.catalog.get("release_id", self.release_dir.name))
        except Exception:
            return None

    def list_datasets(self) -> list[str]:
        if self.catalog_mode == "bundle":
            return sorted(
                str(entry["role"])
                for entry in self.catalog.get("files", [])
                if str(entry.get("path", "")).startswith("data/")
            )
        return sorted(entry["dataset_id"] for entry in self.catalog.get("datasets", []))

    def get_manifest(self, name: str) -> dict[str, Any]:
        if self.catalog_mode == "bundle":
            matches = [record for record in self._read_bundle_manifest() if record.get("role") == name]
            if not matches:
                raise HarvesterDatasetNotFoundError(f"unknown Harvester bundle role: {name}")
            if len(matches) > 1:
                raise HarvesterSchemaError(f"manifest contains duplicate role: {name}")
            return matches[0]
        entry = self._catalog_entry(name)
        self._validate_dataset_declared_paths(entry)
        manifest_path = self._resolve_declared_path(entry["manifest_path"], "manifest_path")
        if not manifest_path.is_file():
            raise HarvesterIntegrityError(f"manifest missing for {name}: {manifest_path}")
        manifest = _read_json_object(manifest_path)
        if self.validate_schema:
            _validate_json(manifest, self._schema_path("dataset_manifest.schema.json"), "manifest")
        if manifest["dataset_id"] != name:
            raise HarvesterSchemaError(f"manifest dataset_id mismatch for {name}: {manifest['dataset_id']}")
        if manifest["release_id"] != self.catalog["release_id"]:
            raise HarvesterSchemaError(f"manifest release_id mismatch for {name}: {manifest['release_id']}")
        if manifest["dataset_revision"] != entry["dataset_revision"]:
            raise HarvesterSchemaError(f"catalog dataset_revision disagrees with manifest for {name}")
        if manifest["data_file"]["path"] != entry["data_path"]:
            raise HarvesterSchemaError(f"catalog data_path disagrees with manifest for {name}")
        if manifest["lineage"]["provenance_path"] != entry["provenance_path"]:
            raise HarvesterSchemaError(f"catalog provenance_path disagrees with manifest for {name}")
        provenance_path = self._resolve_declared_path(entry["provenance_path"], "provenance_path")
        if not provenance_path.is_file():
            raise HarvesterIntegrityError(f"provenance missing for {name}: {provenance_path}")
        provenance = _read_json_object(provenance_path)
        if self.validate_schema:
            _validate_json(provenance, self._schema_path("provenance.schema.json"), "provenance")
        if provenance["checksums"]["final_sha256"] != manifest["data_file"]["sha256"]:
            raise HarvesterIntegrityError(f"provenance final_sha256 mismatch for {name}")
        return manifest

    def load_dataset(self, name: str, as_of: str | None = None, vintage: str | None = None) -> pd.DataFrame:
        if self.catalog_mode == "bundle":
            _ = as_of, vintage
            return self._load_bundle_dataset(name)
        manifest = self.get_manifest(name)
        if as_of is not None and manifest["as_of_date"] != as_of:
            raise HarvesterDatasetNotFoundError(f"{name!r} not available for as_of_date={as_of}")
        if vintage is not None and manifest["vintage_date"] != vintage:
            raise HarvesterDatasetNotFoundError(f"{name!r} not available for vintage_date={vintage}")

        data_info = manifest["data_file"]
        data_path = self._resolve_declared_path(data_info["path"], "data_file.path")
        if not data_path.exists():
            raise HarvesterIntegrityError(f"data file missing for {name}: {data_path}")
        if self.validate_hashes:
            if data_path.stat().st_size != data_info["byte_size"]:
                raise HarvesterIntegrityError(f"byte_size mismatch for {name}: {data_path}")
            actual = _sha256(data_path)
            if actual != data_info["sha256"]:
                raise HarvesterIntegrityError(
                    f"sha256 mismatch for {name}: expected {data_info['sha256']}, got {actual}"
                )
        return _read_dataset(data_path, data_info["format"])

    def load_bundle(self) -> HarvesterBundle:
        if self.catalog_mode != "bundle":
            return self._load_dataset_catalog_bundle()

        manifest = self._read_bundle_manifest()
        provenance = self._read_bundle_provenance()
        source_registry = self._read_bundle_source_registry()
        validation_report = self._validate_bundle_files()

        return HarvesterBundle(
            bundle_id=str(self.catalog["bundle_id"]),
            catalog=self.catalog,
            manifest=manifest,
            provenance=provenance,
            source_registry=source_registry,
            benchmark_panel=self._load_bundle_dataset("benchmark_panel"),
            proxy_candidate_panel=self._load_bundle_dataset("proxy_candidate_panel"),
            corpus_index=self._load_bundle_dataset("corpus_index"),
            validation_report=validation_report,
        )

    def _load_dataset_catalog_bundle(self) -> HarvesterBundle:
        """Expose the dataset-style release through the bundle consumer API.

        Older finalized releases use the protocol's ``datasets`` catalog
        shape, while newer consumers ask the adapter for a bundle.  The
        datasets are already immutable and individually validated, so this is
        a read-only compatibility view rather than a second storage format.
        """
        frames: dict[str, pd.DataFrame] = {}
        manifests: list[dict[str, Any]] = []
        provenance: list[dict[str, Any]] = []
        checked: list[dict[str, Any]] = []
        available = set(self.list_datasets())

        for role in ("benchmark_panel", "proxy_candidate_panel", "corpus_index"):
            if role not in available:
                frames[role] = pd.DataFrame()
                continue
            manifest = self.get_manifest(role)
            frames[role] = self.load_dataset(role)
            manifests.append(manifest)
            entry = self._catalog_entry(role)
            provenance_path = self._resolve_declared_path(
                entry["provenance_path"], "provenance_path"
            )
            provenance.append(_read_json_object(provenance_path))
            checked.append({"dataset_id": role, "status": "ok"})

        release_id = str(self.catalog.get("release_id", self.release_dir.name))
        return HarvesterBundle(
            bundle_id=release_id,
            catalog=self.catalog,
            manifest=manifests,
            provenance=provenance,
            source_registry={
                "status": "finalized",
                "release_id": release_id,
                "catalog_mode": "datasets",
            },
            benchmark_panel=frames["benchmark_panel"],
            proxy_candidate_panel=frames["proxy_candidate_panel"],
            corpus_index=frames["corpus_index"],
            validation_report={
                "release_id": release_id,
                "catalog_mode": "datasets",
                "checked_datasets": checked,
            },
        )

    def _load_catalog(self) -> dict[str, Any]:
        if not self.catalog_path.exists():
            raise HarvesterCatalogMissingError(self.catalog_path)
        catalog = _read_json_object(self.catalog_path)
        if self.require_finalized:
            self._validate_finalized_release(catalog)
        if self.validate_schema and "datasets" in catalog:
            _validate_json(catalog, self._schema_path("catalog.schema.json"), "catalog")
        if "datasets" in catalog and catalog["release_id"] != self.release_dir.name:
            raise HarvesterSchemaError(
                f"catalog release_id {catalog['release_id']} does not match release directory {self.release_dir.name}"
            )
        for entry in catalog.get("datasets", []):
            self._validate_dataset_declared_paths(entry)
        return catalog

    def _catalog_entry(self, name: str) -> dict[str, Any]:
        matches: list[dict[str, Any]] = [
            entry for entry in self.catalog["datasets"] if entry["dataset_id"] == name
        ]
        if not matches:
            raise HarvesterDatasetNotFoundError(f"unknown Harvester dataset: {name}")
        if len(matches) > 1:
            raise HarvesterSchemaError(f"catalog contains duplicate dataset_id: {name}")
        return matches[0]

    def _schema_path(self, filename: str) -> Path:
        path = self.contract_root / filename
        if not path.exists():
            raise HarvesterSchemaError(f"Harvester schema file is missing: {path}")
        return path

    def _resolve_exports_root(self, exports_root: Path | str | None) -> Path:
        if exports_root is not None:
            return Path(exports_root).expanduser()
        if self.harvester_root is None:
            raise ValueError("HarvesterAdapter requires exports_root when harvester_root is not provided")
        direct = self.harvester_root / "exports"
        via_data = self.harvester_root / "data" / "exports"
        if direct.exists() or not via_data.exists():
            return direct
        return via_data

    def _resolve_release_dir(self) -> Path:
        if not isinstance(self.release, str) or not self.release:
            raise HarvesterSchemaError("release must be a non-empty directory name")
        _reject_unsafe_relative_path(self.release, "release")
        if Path(self.release).name != self.release or self.release == ".":
            raise HarvesterSchemaError(f"release must be a directory name: {self.release}")
        release_dir = self.exports_root / self.release
        try:
            resolved = release_dir.resolve()
            resolved.relative_to(self.exports_root)
        except (OSError, ValueError) as exc:
            raise HarvesterIntegrityError(
                f"release resolves outside the exports root: {self.release}"
            ) from exc
        if resolved == self.exports_root:
            raise HarvesterSchemaError(f"release must not be the exports root: {self.release}")
        return resolved

    def _validate_finalized_release(self, catalog: dict[str, Any]) -> None:
        if "files" in catalog:
            if catalog.get("status") != "finalized":
                raise HarvesterIntegrityError(f"Harvester bundle is not finalized: {self.release_dir}")
            return
        finalized_path = self._resolve_declared_path(".finalized", ".finalized")
        if not finalized_path.exists():
            raise HarvesterIntegrityError(f"Harvester release is not finalized: {self.release_dir}")
        digest_path = self._resolve_declared_path("release_digest.txt", "release_digest.txt")
        if digest_path.exists():
            self._validate_release_digest(digest_path)

    def _validate_release_digest(self, digest_path: Path) -> None:
        catalog_rel = self.catalog_path.relative_to(self.release_dir).as_posix()
        catalog_sha = _sha256(self.catalog_path)
        for line in digest_path.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1] == catalog_rel:
                if parts[0] != catalog_sha:
                    raise HarvesterIntegrityError(
                        f"release digest mismatch for {catalog_rel}: expected {parts[0]}, got {catalog_sha}"
                    )
                return
        raise HarvesterIntegrityError(f"release digest does not include {catalog_rel}: {digest_path}")

    def _validate_dataset_declared_paths(self, entry: dict[str, Any]) -> None:
        for key in ("manifest_path", "data_path", "provenance_path"):
            _reject_unsafe_relative_path(entry[key], key)
        if "quality_report_path" in entry:
            _reject_unsafe_relative_path(entry["quality_report_path"], "quality_report_path")

    def _validate_bundle_catalog(self) -> None:
        required = {"bundle_id", "status", "files"}
        missing = sorted(required - set(self.catalog))
        if missing:
            raise HarvesterSchemaError(f"bundle catalog missing required keys: {missing}")
        if not isinstance(self.catalog["files"], list):
            raise HarvesterSchemaError("bundle catalog files must be a list")
        for entry in self.catalog["files"]:
            if not isinstance(entry, dict):
                raise HarvesterSchemaError("bundle catalog file entries must be objects")
            for key in ("path", "role", "format", "sha256"):
                if key not in entry:
                    raise HarvesterSchemaError(f"bundle catalog file entry missing {key}")
            _reject_unsafe_relative_path(str(entry["path"]), "path")
        if self.validate_hashes:
            self._validate_bundle_files()

    def _bundle_entry(self, role: str) -> dict[str, Any]:
        matches: list[dict[str, Any]] = [
            entry for entry in self.catalog["files"] if entry.get("role") == role
        ]
        if not matches:
            raise HarvesterDatasetNotFoundError(f"unknown Harvester bundle role: {role}")
        if len(matches) > 1:
            raise HarvesterSchemaError(f"bundle catalog contains duplicate role: {role}")
        return matches[0]

    def _validate_bundle_files(self) -> dict[str, Any]:
        checked: list[dict[str, Any]] = []
        for entry in self.catalog["files"]:
            path = self._resolve_declared_path(entry["path"], "path")
            if not path.is_file():
                raise HarvesterIntegrityError(f"catalog-declared file missing for {entry['role']}: {path}")
            if self.validate_hashes:
                if "byte_size" in entry and path.stat().st_size != int(entry["byte_size"]):
                    raise HarvesterIntegrityError(f"byte_size mismatch for {entry['role']}: {path}")
                actual = _sha256(path)
                if actual != entry["sha256"]:
                    raise HarvesterIntegrityError(
                        f"sha256 mismatch for {entry['role']}: expected {entry['sha256']}, got {actual}"
                    )
            if self.validate_schema and str(entry.get("format")) == "parquet":
                declared = [
                    str(column["name"])
                    for column in (entry.get("schema") or {}).get("columns", [])
                    if isinstance(column, dict) and column.get("name")
                ]
                if declared:
                    frame_columns = list(pd.read_parquet(path).columns)
                    missing = [name for name in declared if name not in frame_columns]
                    if missing:
                        raise HarvesterSchemaError(f"parquet schema missing columns for {entry['role']}: {missing}")
            checked.append({"role": entry["role"], "path": entry["path"], "status": "ok"})
        return {"bundle_id": self.catalog["bundle_id"], "checked_files": checked}

    def _read_bundle_manifest(self) -> list[dict[str, Any]]:
        entry = self._bundle_entry("manifest")
        return _read_jsonl_objects(self._resolve_declared_path(entry["path"], "path"))

    def _read_bundle_provenance(self) -> list[dict[str, Any]]:
        entry = self._bundle_entry("provenance")
        return _read_jsonl_objects(self._resolve_declared_path(entry["path"], "path"))

    def _read_bundle_source_registry(self) -> dict[str, Any]:
        entry = self._bundle_entry("source_registry")
        return _read_json_object(self._resolve_declared_path(entry["path"], "path"))

    def _load_bundle_dataset(self, role: str) -> pd.DataFrame:
        entry = self._bundle_entry(role)
        path = self._resolve_declared_path(entry["path"], "path")
        if not path.is_file():
            raise HarvesterIntegrityError(f"catalog-declared file missing for {role}: {path}")
        return _read_dataset(path, str(entry["format"]))

    def _safe_catalog_file(self, value: str) -> str:
        path = Path(value)
        if path.name != value or path.is_absolute() or ".." in path.parts:
            raise HarvesterSchemaError(f"catalog_file must be a filename relative to the release root: {value}")
        return value

    def _resolve_declared_path(self, value: str, field: str) -> Path:
        """Resolve a catalog-declared path without leaving the release root.

        Textual ``..`` checks are not enough: a catalog entry or ``latest``
        release may point through a symlink.  Resolve the complete path and
        enforce containment before any reader follows it.
        """
        _reject_unsafe_relative_path(value, field)
        candidate = (self.release_dir / value).resolve()
        try:
            candidate.relative_to(self.release_dir)
        except ValueError as exc:
            raise HarvesterIntegrityError(
                f"{field} resolves outside the release directory: {value}"
            ) from exc
        return candidate


def _read_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise HarvesterSchemaError(f"expected JSON object at {path}")
    return payload


def _read_jsonl_objects(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise HarvesterSchemaError(f"expected JSON object at {path}:{line_number}")
        rows.append(payload)
    return rows


def _validate_json(payload: dict[str, Any], schema_path: Path, label: str) -> None:
    schema = _read_json_object(schema_path)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        details = "; ".join(_format_error(error) for error in errors)
        raise HarvesterSchemaError(f"Harvester {label} schema validation failed: {details}")


def _read_dataset(path: Path, data_format: str) -> pd.DataFrame:
    if data_format == "parquet":
        return pd.read_parquet(path)
    if data_format == "csv":
        return pd.read_csv(path)
    if data_format == "tsv":
        return pd.read_csv(path, sep="\t")
    if data_format == "jsonl":
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return pd.DataFrame(rows)
    if data_format == "json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return pd.DataFrame(payload)
        if isinstance(payload, dict):
            return pd.DataFrame([payload])
    raise HarvesterSchemaError(f"unsupported Harvester data format: {data_format}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reject_unsafe_relative_path(value: str, field: str) -> None:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise HarvesterSchemaError(f"{field} must be a safe relative path: {value}")


def _format_error(error: Any) -> str:
    location = ".".join(str(part) for part in error.absolute_path) or "<root>"
    return f"{location}: {error.message}"


HarvesterReleaseAdapter = HarvesterAdapter


__all__ = [
    "HarvesterAccessError",
    "HarvesterAdapter",
    "HarvesterReleaseAdapter",
    "HarvesterBundle",
    "HarvesterCatalogMissingError",
    "HarvesterDatasetNotFoundError",
    "HarvesterIntegrityError",
    "HarvesterSchemaError",
]
