from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class AssetDefinition:
    asset_name: str
    layer: str
    description: str
    upstream_assets: tuple[str, ...] = ()
    version: str = "v1"
    checks: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AssetMaterialization:
    asset_name: str
    run_date: str
    version: str
    creation_mode: str
    quality_status: str
    upstream_assets: tuple[str, ...]
    provenance: Mapping[str, str] = field(default_factory=dict)


def default_asset_catalog() -> tuple[AssetDefinition, ...]:
    return (
        AssetDefinition(
            asset_name="raw_time_series",
            layer="raw",
            description="Fetched source series prior to normalization.",
            checks=("source_availability",),
        ),
        AssetDefinition(
            asset_name="raw_event_stream",
            layer="raw",
            description="Event stream before validation and operator mapping.",
            checks=("event_schema",),
        ),
        AssetDefinition(
            asset_name="raw_text_stream",
            layer="raw",
            description="Raw narrative/text evidence before scoring.",
        ),
        AssetDefinition(
            asset_name="normalized_series",
            layer="normalized",
            description="Series normalized into structural input scale.",
            upstream_assets=("raw_time_series",),
            checks=("numeric_integrity",),
        ),
        AssetDefinition(
            asset_name="validated_events",
            layer="normalized",
            description="Validated event records eligible for operator mapping.",
            upstream_assets=("raw_event_stream",),
        ),
        AssetDefinition(
            asset_name="normalized_text_evidence",
            layer="normalized",
            description="Normalized narrative evidence for detector consumption.",
            upstream_assets=("raw_text_stream",),
        ),
        AssetDefinition(
            asset_name="candidate_pool",
            layer="evidence",
            description="Proxy/candidate state pool prepared for Core judgment.",
            upstream_assets=("normalized_series", "validated_events"),
        ),
        AssetDefinition(
            asset_name="evidence_features",
            layer="evidence",
            description="Evidence families derived from state, history, and graph views.",
            upstream_assets=("candidate_pool", "normalized_text_evidence"),
        ),
        AssetDefinition(
            asset_name="graph_state_features",
            layer="evidence",
            description="Graph-derived structural evidence from current candidate state.",
            upstream_assets=("candidate_pool",),
        ),
        AssetDefinition(
            asset_name="verified_candidates",
            layer="decision",
            description="Core-screened candidate states ready for adjudication.",
            upstream_assets=("candidate_pool", "evidence_features"),
        ),
        AssetDefinition(
            asset_name="adjudicated_signals",
            layer="decision",
            description="State-level Core judgments produced by the pipeline.",
            upstream_assets=("verified_candidates",),
        ),
        AssetDefinition(
            asset_name="escalation_decisions",
            layer="decision",
            description="Escalation decisions emitted alongside adjudicated signals.",
            upstream_assets=("adjudicated_signals",),
        ),
        AssetDefinition(
            asset_name="snapshot",
            layer="output",
            description="Persisted structural snapshot for a run date.",
            upstream_assets=("adjudicated_signals", "escalation_decisions"),
            checks=("snapshot_persisted",),
        ),
        AssetDefinition(
            asset_name="snapshot_export",
            layer="output",
            description="Rendered JSON/HTML/image exports for a snapshot.",
            upstream_assets=("snapshot",),
        ),
        AssetDefinition(
            asset_name="observation_pool",
            layer="output",
            description="Queryable historical observation window for replay and inspection.",
            upstream_assets=("snapshot",),
        ),
    )


def asset_lineage(catalog: Sequence[AssetDefinition], asset_name: str) -> dict[str, Any] | None:
    target = next((item for item in catalog if item.asset_name == asset_name), None)
    if target is None:
        return None
    return {
        "asset_name": target.asset_name,
        "layer": target.layer,
        "description": target.description,
        "upstream_assets": list(target.upstream_assets),
        "version": target.version,
        "checks": list(target.checks),
        "metadata": dict(target.metadata),
    }


def materialize_snapshot_flow(
    catalog: Sequence[AssetDefinition],
    run_date: str,
    creation_mode: str,
    provenance: Mapping[str, str],
    include_export: bool = False,
) -> list[AssetMaterialization]:
    names = [
        "raw_time_series",
        "raw_event_stream",
        "raw_text_stream",
        "normalized_series",
        "validated_events",
        "normalized_text_evidence",
        "candidate_pool",
        "evidence_features",
        "graph_state_features",
        "verified_candidates",
        "adjudicated_signals",
        "escalation_decisions",
        "snapshot",
    ]
    if include_export:
        names.append("snapshot_export")
    materials: list[AssetMaterialization] = []
    for definition in catalog:
        if definition.asset_name not in names:
            continue
        materials.append(
            AssetMaterialization(
                asset_name=definition.asset_name,
                run_date=run_date,
                version=definition.version,
                creation_mode=creation_mode,
                quality_status="materialized",
                upstream_assets=definition.upstream_assets,
                provenance=dict(provenance),
            )
        )
    return materials
