"""Governance → ML signal pipeline.

Reads governance data (semantic registry, authority registry) and produces
validated ML signal JSON files through ml_signal_writer.

Bridges the gap between governance/semantic analysis and the ML signal layer
so that governance insights are visible in Output/state/ml_signals/ alongside
regime and factor signals.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from workbench.governance.semantic import SemanticRegistry

_SEVERITY_RANK = {"OK": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _concept_score(meta: dict[str, Any]) -> float:
    """Derive a numeric score from a semantic registry entry.

    NOT_IMPLEMENTED concepts score 0.0.
    Implemented concepts score inversely proportional to semantic_distance:
      distance 0 → 1.0
      distance 1 → 0.75
      distance 2 → 0.5
      distance 3 → 0.25
      distance >=4 → 0.1
    """
    if meta.get("implemented_status") == "NOT_IMPLEMENTED":
        return 0.0
    distance = meta.get("semantic_distance")
    if distance is None:
        return 0.5
    distance_value = float(distance)
    if distance_value >= 4:
        return 0.1
    return max(0.0, 1.0 - distance_value * 0.25)


def _severity_to_regime(severity: str) -> str:
    """Map a severity level to a 3-state regime label."""
    rank = _SEVERITY_RANK.get(severity, 0)
    if rank >= 4:  # CRITICAL
        return "crisis"
    if rank >= 3:  # HIGH
        return "volatile"
    return "compression"


# ---------------------------------------------------------------------------
# Semantic signal (type: factor)
# ---------------------------------------------------------------------------

def build_semantic_signal(
    semantic_registry_path: str | Path,
    source_release: str = "governance_internal",
    *,
    output_root: Path | None = None,
    write: bool = True,
) -> dict[str, Any]:
    """Read a SemanticRegistry, compute concept risk factors, emit as ML signal.

    The signal has signal_type "factor". Each concept becomes a factor entry
    with id, label, score (inverse distance), and loading (normalised risk).

    Parameters
    ----------
    semantic_registry_path : str | Path
        Path to the semantic registry JSON file.
    source_release : str
        Release identifier for the signal.
    output_root : Path | None
        Override Output/state/ml_signals/ root.
    write : bool
        If True, write through ml_signal_writer.write_signal().

    Returns
    -------
    dict
        The ML signal payload.
    """
    registry = SemanticRegistry(semantic_registry_path)
    return _build_semantic_from_registry(
        registry, source_release=source_release, output_root=output_root, write=write,
    )


def _build_semantic_from_registry(
    registry: SemanticRegistry,
    source_release: str = "governance_internal",
    *,
    output_root: Path | None = None,
    write: bool = True,
) -> dict[str, Any]:
    """Internal: build signal from an already-loaded SemanticRegistry."""
    concepts = sorted(registry.data.keys())
    factors: list[dict[str, Any]] = []
    total_score = 0.0

    for concept in concepts:
        meta = registry.data[concept]
        score = _concept_score(meta)
        total_score += score

        factors.append({
            "id": concept,
            "label": meta.get("operational_proxy", concept),
            "score": score,
            "loading": 0.0,  # placeholder — will normalise below
        })

    # Normalise loadings
    if total_score > 0:
        for f in factors:
            f["loading"] = round(f["score"] / total_score, 6)

    generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    payload: dict[str, Any] = {
        "schema_version": "workbench.ml_signal.v1",
        "signal_type": "factor",
        "generated_at": generated_at,
        "source_release": source_release,
        "method": "governance_semantic_v1",
        "factors": factors,
        "freshness_gate": {
            "source_created_at": generated_at,
            "signal_valid": True,
            "stale_if_release_changes": True,
        },
        "provenance": {
            "input_path": str(registry.path),
            "concept_count": len(concepts),
            "governance_layer": "semantic",
        },
    }

    if write:
        from ml.ml_signal_writer import write_signal, write_manifest

        write_signal(payload, output_root=output_root, artifact_basename="governance_semantic")
        write_manifest([payload], source_release, output_root=output_root)

    return payload


# ---------------------------------------------------------------------------
# Authority signal (type: regime)
# ---------------------------------------------------------------------------

def build_authority_signal(
    authority_registry_path: str | Path,
    source_release: str = "governance_internal",
    *,
    output_root: Path | None = None,
    write: bool = True,
) -> dict[str, Any]:
    """Read authority violations and emit as a "regime" type ML signal.

    The regime state is determined by the highest severity violation:
    - any CRITICAL violation → regime = "crisis"
    - any HIGH violation → regime = "volatile"
    - else → regime = "compression"

    State probabilities reflect the proportion of violations by severity.

    Parameters
    ----------
    authority_registry_path : str | Path
        Path to the authority registry JSON (expects top-level "violations" key,
        each with "severity").
    source_release : str
        Release identifier.
    output_root : Path | None
        Override output root.
    write : bool
        If True, write via ml_signal_writer.

    Returns
    -------
    dict
        The ML signal payload (signal_type "regime").
    """
    raw = json.loads(Path(authority_registry_path).read_text(encoding="utf-8"))
    violations: list[dict[str, Any]] = raw.get("violations", [])

    # Count by severity
    sev_counts: dict[str, int] = {"OK": 0, "LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
    for v in violations:
        s = v.get("severity", "LOW")
        if s in sev_counts:
            sev_counts[s] += 1

    total_violations = sum(sev_counts.values())

    # Determine regime from highest severity
    if sev_counts.get("CRITICAL", 0) > 0:
        current = "crisis"
    elif sev_counts.get("HIGH", 0) > 0:
        current = "volatile"
    else:
        current = "compression"

    # State probabilities proportional to severity-weighted violation count
    severity_weights = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "OK": 0}
    weighted: dict[str, float] = {}
    for sev, w in severity_weights.items():
        count = sev_counts.get(sev, 0)
        if count > 0:
            weighted[sev] = float(count * w)

    weight_total = sum(weighted.values()) or 1.0

    # Map to regime states
    state_probs: dict[str, float] = {
        "compression": 0.0,
        "volatile": 0.0,
        "crisis": 0.0,
    }
    for sev, w_score in weighted.items():
        regime = _severity_to_regime(sev)
        state_probs[regime] = state_probs.get(regime, 0.0) + w_score / weight_total

    # Normalise to ~1.0
    sp_total = sum(state_probs.values())
    if sp_total > 0:
        state_probs = {k: round(v / sp_total, 6) for k, v in state_probs.items()}

    generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    payload: dict[str, Any] = {
        "schema_version": "workbench.ml_signal.v1",
        "signal_type": "regime",
        "generated_at": generated_at,
        "source_release": source_release,
        "method": "governance_authority_v1",
        "regime": {
            "current": current,
            "probability": state_probs.get(current, 0.0),
            "state_probs": state_probs,
        },
        "freshness_gate": {
            "source_created_at": generated_at,
            "signal_valid": True,
            "stale_if_release_changes": True,
        },
        "provenance": {
            "input_path": str(authority_registry_path),
            "violation_count": total_violations,
            "governance_layer": "authority",
        },
    }

    if write:
        from ml.ml_signal_writer import write_signal, write_manifest

        write_signal(payload, output_root=output_root, artifact_basename="governance_authority")
        write_manifest([payload], source_release, output_root=output_root)

    return payload
