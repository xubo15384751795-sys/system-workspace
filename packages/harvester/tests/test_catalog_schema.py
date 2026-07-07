from __future__ import annotations

import json
from pathlib import Path

import pytest

from harvester.core.catalog import CatalogValidationError, build_catalog, load_catalog, validate_catalog
from harvester.core.exporter import sha256_file
from harvester.core.manifest import write_manifest
from tests.test_manifest_schema import sample_manifest


def test_build_catalog_scans_manifest_directory(tmp_path: Path) -> None:
    release_dir = tmp_path / "2026-04-26-r1"
    (release_dir / "manifests").mkdir(parents=True)
    (release_dir / "data").mkdir()
    data_path = release_dir / "data" / "sample_panel.csv"
    data_path.write_text("date,value\n2026-04-25,1.0\n", encoding="utf-8")
    manifest = sample_manifest(sha256_file(data_path), data_path.stat().st_size)
    write_manifest(manifest, release_dir / "manifests" / "sample_panel.manifest.json")

    catalog = build_catalog(release_dir, finalized_at="2026-04-26T00:00:00Z")

    validate_catalog(catalog)
    assert catalog["release_id"] == "2026-04-26-r1"
    assert catalog["datasets"][0]["dataset_id"] == "sample_panel"
    assert catalog["datasets"][0]["manifest_path"] == "manifests/sample_panel.manifest.json"


def test_load_catalog_rejects_schema_mismatch(tmp_path: Path) -> None:
    release_dir = tmp_path / "2026-04-26-r1"
    release_dir.mkdir()
    (release_dir / "catalog.json").write_text(json.dumps({"datasets": []}), encoding="utf-8")

    with pytest.raises(CatalogValidationError, match="catalog failed validation"):
        load_catalog(release_dir)
