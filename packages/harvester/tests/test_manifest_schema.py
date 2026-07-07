from __future__ import annotations

import json
from pathlib import Path

import pytest

from harvester.core.manifest import ManifestValidationError, build_manifest, load_manifest, validate_manifest


def sample_manifest(data_sha256: str, byte_size: int) -> dict:
    return build_manifest(
        dataset_id="sample_panel",
        dataset_revision=1,
        release_id="2026-04-26-r1",
        as_of_date="2026-04-25",
        vintage_date="2026-04-26",
        source={
            "provider": "unit-test",
            "kind": "manual_curation",
            "url_or_reference": "tests",
            "retrieved_at": "2026-04-26T00:00:00Z",
        },
        data_file={
            "path": "data/sample_panel.csv",
            "format": "csv",
            "sha256": data_sha256,
            "byte_size": byte_size,
            "row_count": 1,
        },
        columns=[
            {
                "name": "date",
                "dtype": "date",
                "nullable": False,
                "description": "Observation date.",
                "semantic_role": "time_index",
            },
            {
                "name": "value",
                "dtype": "float64",
                "nullable": False,
                "description": "Observed value.",
                "semantic_role": "measure",
            },
        ],
        time_coverage={"start": "2026-04-25", "end": "2026-04-25", "frequency": "daily", "time_column": "date"},
        provenance_path="provenance/sample_panel.provenance.json",
        quality_report_path="quality_reports/sample_panel.quality.json",
        notes="Sample panel for contract tests.",
    )


def test_build_manifest_matches_schema() -> None:
    manifest = sample_manifest("0" * 64, 12)
    validate_manifest(manifest)


def test_load_manifest_rejects_malformed_payload(tmp_path: Path) -> None:
    path = tmp_path / "bad.manifest.json"
    path.write_text(json.dumps({"schema_version": "1.0"}), encoding="utf-8")

    with pytest.raises(ManifestValidationError, match="dataset manifest failed validation"):
        load_manifest(path)
