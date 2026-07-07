from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from src.data_access.errors import InvalidEvidenceError, MissingReleaseError
from src.data_access.harvester_adapter import (
    HarvesterAdapter,
    HarvesterBundle,
    HarvesterCatalogMissingError,
    HarvesterIntegrityError,
    HarvesterSchemaError,
)


@dataclass(frozen=True)
class EvidenceSourceRef:
    provider: str
    dataset: str
    source_path: str | None = None
    release_id: str | None = None
    provenance_id: str | None = None


@dataclass(frozen=True)
class EvidencePanel:
    name: str
    frame: pd.DataFrame
    schema_version: str
    source: EvidenceSourceRef
    quality: dict[str, Any]


@dataclass(frozen=True)
class AdmittedEvidenceBundle:
    release_id: str
    as_of: str
    catalog_path: Path
    manifest_path: Path
    provenance_path: Path | None
    panels: dict[str, EvidencePanel]
    quality: dict[str, Any]
    metadata: dict[str, Any]

    def get_panel(self, name: str) -> EvidencePanel:
        try:
            return self.panels[name]
        except KeyError as exc:
            raise KeyError(f"Evidence panel not found: {name}") from exc

    def list_panels(self) -> list[str]:
        return sorted(self.panels)


class AdmittedEvidenceHub:
    """
    Deformation-side evidence hub.
    This hub consumes Harvester-published releases only.
    It must not construct provider clients, read API keys, or call external HTTP.
    """

    def __init__(
        self,
        release_root: Path | str,
        *,
        contract_root: Path | str | None = None,
        require_finalized: bool = True,
        validate_hashes: bool = True,
        validate_schema: bool = True,
    ) -> None:
        # No provider clients.
        # No API keys.
        # No external HTTP.
        self.release_root = Path(release_root).expanduser()
        self.contract_root = Path(contract_root).expanduser() if contract_root else _default_contract_root()
        self.require_finalized = require_finalized
        self.validate_hashes = validate_hashes
        self.validate_schema = validate_schema

    def load_latest(self) -> AdmittedEvidenceBundle:
        return self.load_release("latest")

    def load_release(self, release_id: str) -> AdmittedEvidenceBundle:
        try:
            adapter = HarvesterAdapter(
                exports_root=self.release_root,
                release=release_id,
                contract_root=self.contract_root,
                require_finalized=self.require_finalized,
                validate_hashes=self.validate_hashes,
                validate_schema=self.validate_schema,
            )
            bundle = adapter.load_bundle()
        except HarvesterCatalogMissingError as exc:
            raise MissingReleaseError(str(exc)) from exc
        except (HarvesterIntegrityError, HarvesterSchemaError) as exc:
            raise InvalidEvidenceError(str(exc)) from exc
        return _bundle_from_harvester(adapter, bundle)

    def validate_release(self, release_id: str) -> None:
        self.load_release(release_id)


def _bundle_from_harvester(adapter: HarvesterAdapter, bundle: HarvesterBundle) -> AdmittedEvidenceBundle:
    manifest_path = adapter.release_dir / "manifest.jsonl"
    provenance_path = adapter.release_dir / "provenance.jsonl"
    if not manifest_path.exists():
        raise InvalidEvidenceError(f"missing Harvester manifest: {manifest_path}")
    if not provenance_path.exists():
        provenance_path = None

    panels = {
        "benchmark_panel": _panel(
            "benchmark_panel",
            bundle.benchmark_panel,
            bundle,
            adapter.release_dir / "data" / "benchmark_panel.parquet",
        ),
        "proxy_candidate_panel": _panel(
            "proxy_candidate_panel",
            bundle.proxy_candidate_panel,
            bundle,
            adapter.release_dir / "data" / "proxy_candidate_panel.parquet",
        ),
        "corpus_index": _panel(
            "corpus_index",
            bundle.corpus_index,
            bundle,
            adapter.release_dir / "data" / "corpus_index.parquet",
        ),
    }
    return AdmittedEvidenceBundle(
        release_id=bundle.bundle_id,
        as_of=str(bundle.catalog.get("created_at", "")),
        catalog_path=adapter.catalog_path,
        manifest_path=manifest_path,
        provenance_path=provenance_path,
        panels=panels,
        quality=bundle.validation_report,
        metadata={
            "catalog": bundle.catalog,
            "source_registry": bundle.source_registry,
            "catalog_mode": "bundle",
        },
    )


def _panel(name: str, frame: pd.DataFrame, bundle: HarvesterBundle, source_path: Path) -> EvidencePanel:
    source_ids = sorted(str(value) for value in frame.get("source_id", pd.Series(dtype=str)).dropna().unique())
    provider = ",".join(source_ids) if source_ids else "harvester"
    catalog_entry = next((entry for entry in bundle.catalog.get("files", []) if entry.get("role") == name), {})
    schema_version = str(catalog_entry.get("schema", {}).get("version", "harvester.bundle.v1"))
    return EvidencePanel(
        name=name,
        frame=frame,
        schema_version=schema_version,
        source=EvidenceSourceRef(
            provider=provider,
            dataset=name,
            source_path=source_path.as_posix(),
            release_id=bundle.bundle_id,
            provenance_id=name,
        ),
        quality={
            "row_count": int(len(frame)),
            "declared_row_count": catalog_entry.get("row_count"),
            "format": catalog_entry.get("format"),
        },
    )


def _default_contract_root() -> Path:
    from src.core.runtime_context import RuntimePaths
    project_root = RuntimePaths.discover().project_root
    workspace_root = project_root.parent
    candidates = [
        workspace_root / "Workbench" / "data_providers" / "structural-risk-harvester" / "contracts",
        workspace_root / "Structural Risk Harvester" / "contracts",
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]
