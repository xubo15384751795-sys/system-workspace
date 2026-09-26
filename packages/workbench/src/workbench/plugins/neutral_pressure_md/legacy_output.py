"""Compatibility projection for the existing neutral-pressure file contract.

This module is an application/output adapter.  It is deliberately outside
the model implementation and is the only place in the plugin that knows the
legacy ``framework_output`` shape and canonical lineage helpers.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from system_runtime.canonical_ids import (
    build_chain,
    build_claim,
    build_evidence,
    build_measurement,
    build_observation,
    lineage_ids,
)
from verity.runtime._artifact_provenance import build_provenance

from workbench.model_protocol import ModelEvaluation


MECHANISM_CARDS = Path("docs/measurements/macro_pressure_mechanism_cards.md")


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 4) if np.isfinite(number) else None


def _file_sha256(path: Path) -> str | None:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError:
        return None
    return digest.hexdigest()


def build_legacy_snapshot(
    evaluation: ModelEvaluation,
    *,
    panel_path: Path,
    history_path: Path,
    mechanism_cards: Path | None = None,
) -> tuple[dict[str, Any], pd.DataFrame]:
    """Project a generic model evaluation into the frozen file surfaces."""
    result = evaluation.result
    payload = dict(result.model_payload)
    gauge_values = payload.get("gauge_values") or {}
    m_value = _finite(gauge_values.get("M"))
    d_value = _finite(gauge_values.get("D"))
    state = str(result.state or "PRESSURE_READOUT_UNAVAILABLE")
    both_live = m_value is not None and d_value is not None
    history = result.runtime_artifacts.get("pressure_history")
    if not isinstance(history, pd.DataFrame):
        raise TypeError("neutral_pressure_md did not return pressure_history")

    cards_path = mechanism_cards or MECHANISM_CARDS
    release_id = str(result.provenance.get("source_release_id") or "unknown")
    run_id = str(result.provenance.get("run_id") or "neutral_pressure")
    as_of = str(result.as_of or "")
    panel_digest = _file_sha256(panel_path)
    provenance = build_provenance(
        producer_step="neutral_pressure_measurement",
        source_release_id=release_id,
        as_of_date=as_of[:10],
        input_paths=[panel_path, cards_path],
        validation_verdict="pass" if both_live else "degraded",
        claim_ceiling="bounded_neutral_measurement",
        degraded_reasons=[] if both_live else ["one_or_more_neutral_gauges_unavailable"],
    )
    provenance["run_id"] = run_id
    provenance["model_id"] = result.model_id
    provenance["model_protocol_version"] = result.protocol_version
    provenance["model_implementation_digest"] = result.implementation_digest

    canonical_observation = build_observation(
        canonical_series_id="SYSTEM:NEUTRAL_PRESSURE_PANEL",
        observed_at=as_of,
        value={"M": m_value, "D": d_value},
        source_id="harvester:benchmark_panel",
        unit="bounded_pressure_gauge",
        source_snapshot_sha256=panel_digest,
        provenance={
            **provenance,
            "captured_at": provenance.get("generated_at", as_of),
            "producer": "neutral_pressure_measurement",
        },
    )
    canonical_measurement = build_measurement(
        observation_ids=[canonical_observation["observation_id"]],
        measurement_definition="macro_pressure_measurement",
        value={"M": m_value, "D": d_value},
        unit="bounded_pressure_gauge",
        status="AVAILABLE" if both_live else "MISSING",
        derivation="PROXY_DERIVED",
        confidence=result.confidence or 0.35,
        provenance={
            **provenance,
            "captured_at": provenance.get("generated_at", as_of),
            "producer": "neutral_pressure_measurement",
            "method": "causal_zscore_and_component_mean",
        },
    )
    canonical_evidence = build_evidence(
        measurement_ids=[canonical_measurement["measurement_id"]],
        evidence_role="PRIMARY",
        source_id="harvester:benchmark_panel",
        release_id=release_id or None,
        source_snapshot_sha256=panel_digest,
        status="AVAILABLE" if panel_digest else "UNKNOWN",
        provenance={
            **provenance,
            "captured_at": provenance.get("generated_at", as_of),
            "producer": "neutral_pressure_measurement",
            "source_url": str(panel_path),
        },
    )
    canonical_claim = build_claim(
        claim_text=f"Neutral macro-pressure state is {state}.",
        subject="neutral_macro_pressure",
        predicate="has_state",
        evidence_ids=[canonical_evidence["evidence_id"]],
        status="WATCH",
        confidence=result.confidence or 0.35,
        provenance={
            **provenance,
            "captured_at": provenance.get("generated_at", as_of),
            "producer": "neutral_pressure_measurement",
            "statement_kind": "bounded_neutral_measurement",
            "claim_ceiling": "bounded_neutral_measurement",
            "promotion_allowed": False,
        },
    )
    canonical_chain = build_chain(
        observation=canonical_observation,
        measurement=canonical_measurement,
        evidence=canonical_evidence,
        claim=canonical_claim,
    )

    velocity = payload.get("velocity_20d") or {}
    velocity_20d = {"M": velocity.get("score_0"), "D": velocity.get("score_1")}
    n_deteriorating = int(payload.get("n_deteriorating") or 0)
    metadata = payload.get("component_metadata") or {}
    channels_live = [key for key, value in (("M", m_value), ("D", d_value)) if value is not None]
    snapshot: dict[str, Any] = {
        "schema_version": "neutral_pressure.snapshot.v1",
        "measurement_id": "macro_pressure_measurement",
        "framework_id": "macro_pressure_measurement",
        "producer": "neutral_pressure_measurement",
        "run_id": run_id,
        "as_of": as_of,
        "available_at": result.available_at,
        "provenance": provenance,
        "canonical_chain": canonical_chain,
        "canonical_ids": lineage_ids(canonical_chain),
        "decision_evidence": evaluation.evidence.to_dict(),
        "model_result": result.to_dict(),
        "status": "active_partial" if both_live else "degraded_partial",
        "basic": {
            "overall": "ACTIVE_PARTIAL" if both_live else "DEGRADED_PARTIAL",
            "quality_status": "FULL_WITH_WARNINGS" if both_live else "PARTIAL",
            "main_pressure": state,
            "confidence": "bounded measurement only; no universal prediction authority",
            "summary": (
                f"Neutral macro-pressure state is {state}. Funding mismatch pressure={m_value}; "
                f"market constraint pressure={d_value}. This is a measurement dashboard, not a market theory."
            ),
            "primary_market_space": state,
            "daily_readout_policy": "Use neutral M/D compatibility gauges for bounded monitoring only.",
        },
        "advanced": {
            "primary_readout": {
                "state": state,
                "M_anchor_geometry": {
                    "value": m_value,
                    "compatibility_key": "M",
                    "product_name": "funding_mismatch_pressure",
                },
                "D_path_geometry": {
                    "value": d_value,
                    "compatibility_key": "D",
                    "product_name": "market_constraint_pressure",
                },
                "theory_authority": "none",
            },
            "sigma_vector": {
                "M": m_value,
                "D": d_value,
                "K": None,
                "X_agg": None,
                "channels_live": channels_live,
                "channels_not_implemented": ["K", "X_agg"],
                "complete": False,
                "dominant_channel": "NONE",
                "cofire_count": 0,
                "velocity_20d": velocity_20d,
                "n_deteriorating": n_deteriorating,
                "semantic_warning": [
                    "M and D are compatibility keys for neutral gauges, not Deformation dimensions.",
                    "K and X are excluded from the operational product and remain research-only candidates.",
                ],
            },
            "channel_coverage": {
                "channels_live": channels_live,
                "channels_not_implemented": ["K", "X_agg"],
                "total_canonical": 2,
                "coverage_ratio": f"{len(channels_live)}/2",
                "complete": both_live,
            },
            "channel_confidence": {
                key: {
                    "status": "live" if value is not None else "unavailable",
                    "confidence": "medium",
                    "proxy_quality": "LITERATURE_GROUNDED_REQUALIFICATION",
                    "readout_role": "neutral_measurement",
                    "product_name": product,
                }
                for key, value, product in (
                    ("M", m_value, "funding_mismatch_pressure"),
                    ("D", d_value, "market_constraint_pressure"),
                )
            },
            "measurement_eligibility": {
                "M": {"readout_role": "neutral_measurement", "theory_authority": "none"},
                "D": {"readout_role": "neutral_measurement", "theory_authority": "none"},
                "K": {"readout_role": "research_only", "operational_wiring": "denied"},
                "X_agg": {"readout_role": "research_only", "operational_wiring": "denied"},
            },
            "quality_status": "FULL_WITH_WARNINGS" if both_live else "PARTIAL",
            "measurement_blind_spot": not both_live,
            "coverage_ratio": f"{len(channels_live)}/2",
            "harvester_release": release_id,
            "semantic_warnings": ["Archived Deformation v1 claims have no authority over this output."],
            "component_metadata": metadata,
            "model_protocol": {
                "protocol_version": result.protocol_version,
                "model_id": result.model_id,
                "model_version": result.model_version,
                "adapter_id": evaluation.evidence.adapter_id,
                "adapter_version": evaluation.evidence.adapter_version,
            },
        },
        "artifacts": {
            "pressure_history": str(history_path),
            "mechanism_cards": str(cards_path),
        },
        "evidence_links": [str(panel_path), str(cards_path)],
        "next_actions": [
            "Continue common-sample validation of the neutral gauges against public baselines.",
            "Keep velocity-gate requalification in Strategy Lab until input-independence tests pass.",
        ],
        "legacy_compatibility": {
            "framework_output_filename": True,
            "deformation_v1_theory_authority": False,
            "falsified_claim_set": "deformation_v1_four_channel_universal_predictor",
        },
    }
    return snapshot, history


__all__ = ["build_legacy_snapshot"]
