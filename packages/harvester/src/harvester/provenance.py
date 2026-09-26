"""Provenance construction owned by the Harvester evidence boundary."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from harvester.core.provenance import build_provenance


def make_provenance(
    *,
    dataset_id: str,
    release_id: str,
    method: str,
    source_identifier: str,
    source_params: dict[str, Any] | None = None,
    final_sha256: str,
    raw_sha256: str = "",
    provider_outcome: dict[str, Any] | None = None,
    observation_start: str | None = None,
    observation_end: str | None = None,
    observation_time_column: str = "date",
    availability: dict[str, Any] | None = None,
    integrity: dict[str, Any] | None = None,
    canonical_observation_path: str | None = None,
    canonical_observation_count: int | None = None,
    canonical_chain_path: str | None = None,
    canonical_chain_count: int | None = None,
    canonical_schema_version: str | None = None,
    canonical_lineage_path: str | None = None,
    previous_release_id: str | None = None,
    canonical_observation_delta_count: int | None = None,
    canonical_chain_delta_count: int | None = None,
    canonical_observation_merkle_root: str | None = None,
    canonical_chain_merkle_root: str | None = None,
    measurement_spec_path: str | None = None,
    measurement_spec_version: str | None = None,
    notes: str = "",
    acquisition_sources: list[dict[str, Any]] | None = None,
    local_steps: list[dict[str, Any]] | None = None,
    started_at: str | None = None,
    completed_at: str | None = None,
) -> dict[str, Any]:
    """Build the standard provenance envelope for a release artifact."""
    timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    acquisition: dict[str, Any] = {
        "method": method,
        "source_identifier": source_identifier,
        "started_at": started_at or timestamp,
        "completed_at": completed_at or timestamp,
        "operator": "harvester.official",
    }
    if acquisition_sources is not None:
        acquisition["sources"] = list(acquisition_sources)
    if local_steps is not None:
        acquisition["local_steps"] = list(local_steps)
    checksums: dict[str, str] = {"final_sha256": final_sha256}
    if raw_sha256 and len(raw_sha256) == 64:
        checksums["raw_sha256"] = raw_sha256
    return cast(
        dict[str, Any],
        build_provenance(
            dataset_id=dataset_id,
            release_id=release_id,
            acquisition=acquisition,
            checksums=checksums,
            provider_outcome=provider_outcome,
            observation_start=observation_start,
            observation_end=observation_end,
            observation_time_column=observation_time_column,
            availability=availability,
            integrity=integrity,
            canonical_observation_path=canonical_observation_path,
            canonical_observation_count=canonical_observation_count,
            canonical_chain_path=canonical_chain_path,
            canonical_chain_count=canonical_chain_count,
            canonical_schema_version=canonical_schema_version,
            canonical_lineage_path=canonical_lineage_path,
            previous_release_id=previous_release_id,
            canonical_observation_delta_count=canonical_observation_delta_count,
            canonical_chain_delta_count=canonical_chain_delta_count,
            canonical_observation_merkle_root=canonical_observation_merkle_root,
            canonical_chain_merkle_root=canonical_chain_merkle_root,
            measurement_spec_path=measurement_spec_path,
            measurement_spec_version=measurement_spec_version,
            notes=notes,
        ),
    )

__all__ = ["make_provenance"]
