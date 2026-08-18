from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from harvester.core.manifest import ManifestValidationError, build_manifest, load_manifest, validate_manifest
from harvester.core.provenance import build_provenance, validate_provenance


def sample_manifest(data_sha256: str, byte_size: int) -> dict[str, Any]:
    return cast(dict[str, Any], build_manifest(
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
    ))


def test_build_manifest_matches_schema() -> None:
    manifest = sample_manifest("0" * 64, 12)
    validate_manifest(manifest)


def test_provider_chain_outcome_matches_manifest_and_provenance_contracts() -> None:
    """Provider-chain metadata must remain accepted by both release contracts."""
    outcome = {
        "status": "partial_provider_success",
        "provider": "etf_provider_chain",
        "requested_count": 3,
        "succeeded_count": 2,
        "failed_count": 1,
        "failed_series": ["BAD"],
        "retrieved_at": "2026-04-26T00:00:00Z",
        "providers_used": ["tiingo", "yfinance"],
        "series_providers": {"GOOD": "tiingo", "FALLBACK": "yfinance"},
        "series_attempts": {
            "FALLBACK": [
                {
                    "provider_attempt_id": "att_" + "1" * 32,
                    "attempt_number": 1,
                    "provider": "tiingo",
                    "source_tier": 1,
                    "reason": "rate_limited",
                    "error": "429",
                    "outcome": "failed",
                    "retryable": True,
                },
                {
                    "provider_attempt_id": "att_" + "2" * 32,
                    "attempt_number": 2,
                    "provider": "yfinance",
                    "source_tier": 3,
                    "reason": "success",
                    "error": "",
                    "outcome": "success",
                    "retryable": False,
                },
            ]
        },
        "prefetched_series": ["HYG"],
        "prefetch_owner": "harvester.registry_acquisition",
        "provider_chain": ["tiingo", "massive", "yfinance"],
        "fallback_used": True,
    }

    manifest = sample_manifest("0" * 64, 12)
    manifest["provider_outcome"] = outcome
    validate_manifest(manifest)

    provenance = build_provenance(
        dataset_id="sample_panel",
        release_id="2026-04-26-r1",
        acquisition={
            "method": "api_client",
            "source_identifier": "tests",
            "started_at": "2026-04-26T00:00:00Z",
            "completed_at": "2026-04-26T00:00:00Z",
            "operator": "unit-test",
        },
        checksums={"final_sha256": "0" * 64},
        provider_outcome=outcome,
        canonical_chain_path="provenance/sample_panel.canonical_chains.jsonl",
        canonical_chain_count=0,
    )
    validate_provenance(provenance)
    assert provenance["canonical_chain_count"] == 0


def test_load_manifest_rejects_malformed_payload(tmp_path: Path) -> None:
    path = tmp_path / "bad.manifest.json"
    path.write_text(json.dumps({"schema_version": "1.0"}), encoding="utf-8")

    with pytest.raises(ManifestValidationError, match="dataset manifest failed validation"):
        load_manifest(path)
