"""Shared producer helper for bounded canonical observation chains."""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any


def build_recorded_observation_chains(
    observations: Sequence[Mapping[str, Any]],
    *,
    release_id: str,
    producer: str,
    measurement_definition: str,
    policy_version: str,
    predicate: str = "observation_recorded_on",
    label_factory: Callable[[Mapping[str, Any]], str] | None = None,
) -> list[dict[str, Any]]:
    """Build complete chains without turning measurements into judgments.

    The resulting Claim states only that the producer recorded an observation
    on a date. It is linked to real Evidence but remains diagnostic-only and
    therefore cannot satisfy a research promotion gate by itself.
    """
    try:
        from system_runtime.canonical_ids import (
            build_chain,
            build_claim,
            build_evidence,
            build_measurement,
        )
    except ImportError:
        return []

    chains: list[dict[str, Any]] = []
    for observation in observations:
        source = observation.get("source")
        provenance = observation.get("provenance")
        if not isinstance(source, Mapping) or not isinstance(provenance, Mapping):
            raise ValueError("canonical observation must include source and provenance")
        status = str(observation.get("status") or "UNKNOWN")
        observed_at = str(observation.get("observed_at") or "").strip()
        label = (
            label_factory(observation)
            if label_factory is not None
            else str(
                (observation.get("scope") or {}).get("symbol")
                or observation.get("canonical_series_id")
                or "observation"
            )
        )
        claim_status = {"AVAILABLE": "WATCH", "STALE": "STALE"}.get(
            status, "INSUFFICIENT_DATA"
        )
        captured_at = str(provenance.get("captured_at") or "")
        common_provenance = {
            "captured_at": captured_at,
            "producer": producer,
            "run_id": release_id,
            "statement_kind": "recorded_observation",
        }
        derivation = str(provenance.get("derivation") or "OBSERVED")
        measurement = build_measurement(
            observation_ids=[str(observation["observation_id"])],
            measurement_definition=measurement_definition,
            value=observation.get("value"),
            unit=observation.get("unit"),
            status=status,
            derivation=derivation,
            method_version=policy_version,
            provenance=common_provenance,
        )
        evidence = build_evidence(
            measurement_ids=[measurement["measurement_id"]],
            evidence_role="PRIMARY",
            source_id=str(source["source_id"]),
            release_id=release_id,
            source_snapshot_sha256=source.get("snapshot_sha256"),
            status=status,
            provenance=common_provenance,
        )
        claim = build_claim(
            claim_text=f"{label} was recorded on {observed_at}",
            subject=label,
            predicate=predicate,
            policy_version=policy_version,
            evidence_ids=[evidence["evidence_id"]],
            status=claim_status,
            confidence=None,
            provenance={
                **common_provenance,
                "claim_ceiling": "diagnostic_observation_only",
                "promotion_allowed": False,
            },
        )
        chains.append(
            build_chain(
                observation=dict(observation),
                measurement=measurement,
                evidence=evidence,
                claim=claim,
            )
        )
    return chains
