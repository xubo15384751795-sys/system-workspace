"""Judgment Layer — turn diagnostics into bounded research judgment.

This module reads framework output, CaseLab, HMM, and gate status
to produce a daily judgment card.

Usage:
    from workbench.judgment.layer import build_judgment, write_outputs

    card = build_judgment(fw, caselab, hmm, k_gate, x_gate, validation)
    paths = write_outputs(card)
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from system_runtime.paths import WorkspacePaths, output_surface
from system_runtime.canonical_ids import (
    build_claim,
    build_evidence,
    build_invalidation_spec_id,
    build_measurement,
    build_observation,
    build_chain,
    lineage_ids,
    validate_chain,
)
from workbench.judgment.synthesizer import ClaimEnvelope, JudgmentSynthesizer

logger = logging.getLogger(__name__)

ROOT = WorkspacePaths.discover().root
PRESSURE_PATH = output_surface(ROOT, "current") / "neutral_pressure_snapshot.json"
# Compatibility export for callers that have not yet renamed the constant.
FW_PATH = PRESSURE_PATH
CASELAB_DIR = ROOT / "Output" / "caselab"
HMM_PATH = ROOT / "Output" / "ml_signals" / "latest" / "regime_hmm.json"
K_GATE_PATH = ROOT / "Output" / "k_measurement" / "k_measurement_gate.json"
X_GATE_PATH = ROOT / "Output" / "x_measurement" / "x_measurement_gate.json"
VALIDATION_PATH = output_surface(ROOT, "current") / "quality_validation.json"
OUTPUT_DIR = output_surface(ROOT, "judgment")


def load_json(path: Path) -> dict[str, Any] | None:
    """Load a JSON file, returning None if missing or invalid."""
    if not path.exists():
        return None
    try:
        return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return None


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _date_from_framework(fw: dict[str, Any]) -> str:
    as_of = str(fw.get("as_of") or "")
    if len(as_of) >= 10:
        return as_of[:10]
    return datetime.now(UTC).strftime("%Y-%m-%d")


def load_caselab(date_str: str) -> dict[str, Any] | None:
    dated = CASELAB_DIR / f"{date_str}.json"
    if dated.exists():
        return load_json(dated)
    candidates = sorted(CASELAB_DIR.glob("*.json"))
    if not candidates:
        return None
    return load_json(candidates[-1])


def load_hmm() -> dict[str, Any] | None:
    return load_json(HMM_PATH)


def load_k_gate() -> dict[str, Any] | None:
    return load_json(K_GATE_PATH)


def load_x_gate() -> dict[str, Any] | None:
    return load_json(X_GATE_PATH)


def load_validation() -> dict[str, Any] | None:
    return load_json(VALIDATION_PATH)


def _hmm_stability_grade(hmm: dict[str, Any] | None) -> tuple[str, list[str]]:
    """Determine HMM stability grade using model_health + calibration split.

    Returns (grade, reasons) where grade is one of:
    - UNAVAILABLE: no HMM output
    - WEAK: model_health FAIL
    - ADEQUATE: model_health PASS, calibration CALIBRATING/INSUFFICIENT
    - HIGH: model_health PASS, calibration PASSED

    Reads model_health/calibration_status from the HMM stability audit
    if not present in the HMM output itself.
    """
    if not hmm:
        return "UNAVAILABLE", ["HMM output not found"]

    regime = hmm.get("regime", {})
    stability = hmm.get("stability", {})
    calibration = hmm.get("calibration", {})

    reasons = []

    # Check for model_health / calibration_status split (v2 audit)
    # If not in HMM output, try loading from audit file
    model_health_grade = "UNKNOWN"
    cal_status = "UNKNOWN"
    if "model_health" in hmm:
        model_health_grade = hmm["model_health"].get("grade", "UNKNOWN")
        cal_status = hmm.get("calibration_status", {}).get("status", "UNKNOWN")
    else:
        # Load from audit file
        hmm_audit_path = ROOT / "Output" / "hmm_stability" / "hmm_stability_audit.json"
        if hmm_audit_path.exists():
            try:
                audit = json.loads(hmm_audit_path.read_text(encoding="utf-8"))
                model_health_grade = audit.get("model_health", {}).get("grade", "UNKNOWN")
                cal_status = audit.get("calibration_status", {}).get("status", "UNKNOWN")
            except Exception:
                logger.warning("Unable to parse HMM stability audit: %s", hmm_audit_path, exc_info=True)

    # Model health failures are always WEAK
    if model_health_grade == "FAIL":
        reasons.append("HMM model health: FAIL")
        for issue in hmm.get("model_health", {}).get("issues", []):
            reasons.append(f"Model: {issue}")
        return "WEAK", reasons

    # Calibration status determines grade
    if cal_status == "INSUFFICIENT_HISTORY":
        reasons.append("HMM calibration: INSUFFICIENT_HISTORY — regime claims blocked, mechanism hypothesis allowed")
        return "ADEQUATE", reasons

    if cal_status == "CALIBRATING":
        reasons.append("HMM calibration: CALIBRATING — regime hint available, not fully calibrated")
        for issue in hmm.get("calibration_status", {}).get("issues", []):
            reasons.append(f"Calibration: {issue}")
        return "ADEQUATE", reasons

    if cal_status == "PASSED":
        reasons.append("HMM fully calibrated")
        return "HIGH", reasons

    # Legacy path: use calibration data if available
    if calibration:
        if not calibration.get("calibration_passed", True):
            cap = calibration.get("cap_applied", "unknown")
            reasons.append(
                f"HMM calibration not passed (cap={cap}, "
                f"calibrated={calibration.get('calibrated_confidence', '?')})"
            )
            for dr in calibration.get("degradation_reasons", []):
                reasons.append(f"Calibration: {dr}")
            return "WEAK", reasons
    else:
        prob = _as_float(regime.get("current_probability", 0))
        if prob >= 0.99:
            reasons.append(f"Raw probability {prob:.4f} >= 0.99 — overconfident")
            return "WEAK", reasons

    entropy = _as_float(stability.get("posterior_entropy", 0))
    if entropy < 0.1:
        reasons.append(f"Posterior entropy very low ({entropy:.3f}) — possibly overconfident")
        return "WEAK", reasons

    sample_days = int(stability.get("sample_days", 0))
    if sample_days < 252:
        reasons.append(f"Sample days={sample_days} < 252 — limited training data")
        return "WEAK", reasons

    if not reasons:
        reasons.append("HMM stability checks passed")

    return "ADEQUATE", reasons


def _channel_roles(fw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return fw.get("advanced", {}).get("channel_confidence", {}) or {}


def _limited_channels(fw: dict[str, Any]) -> list[str]:
    roles = _channel_roles(fw)
    limited = []
    for channel, meta in roles.items():
        if meta.get("proxy_quality") == "PROXY_REDUCED" or meta.get("confidence") == "low":
            limited.append(channel)
    return limited


def _md_values(fw: dict[str, Any]) -> tuple[float, float]:
    primary = fw.get("advanced", {}).get("primary_readout", {}) or {}
    m_val = _as_float((primary.get("M_anchor_geometry") or {}).get("value"))
    d_val = _as_float((primary.get("D_path_geometry") or {}).get("value"))
    return m_val, d_val


def _confidence(fw: dict[str, Any], caselab: dict[str, Any] | None,
                hmm: dict[str, Any] | None = None,
                k_gate: dict[str, Any] | None = None,
                x_gate: dict[str, Any] | None = None,
                validation: dict[str, Any] | None = None) -> tuple[str, list[str], dict[str, str]]:
    """Compute layered confidence: diagnostic, mechanism, trade.

    Returns (trade_confidence, reasons, layered_confidence).
    - diagnostic_confidence: can we make measurement observations?
    - mechanism_confidence: can we make mechanism hypotheses?
    - trade_confidence: can we make operational decisions?
    """
    reasons: list[str] = []
    trade_reasons: list[str] = []
    quality = fw.get("basic", {}).get("quality_status", "UNKNOWN")
    measurement_quality = fw.get("basic", {}).get("measurement_quality", "UNKNOWN")
    limited = _limited_channels(fw)
    if "PROXY_REDUCED" in str(quality) or "LOW_CONFIDENCE" in str(measurement_quality):
        reasons.append(f"Measurement ceiling is {quality}/{measurement_quality}.")
    if limited:
        reasons.append("Limited channels: " + ", ".join(limited) + ".")

    caselab_label = "unknown"
    caselab_score = 0.0
    if caselab:
        caselab_label = (caselab.get("match_quality") or {}).get("label", "unknown")
        caselab_score = _as_float((caselab.get("match_quality") or {}).get("top_score", 0))
        if caselab_label == "weak":
            reasons.append(f"CaseLab match is weak (top_score={caselab_score}).")
        recon = caselab.get("regime_reconciliation") or {}
        if recon.get("divergence"):
            reasons.append(
                f"HMM and neutral pressure gauges diverge: HMM={recon.get('hmm_regime')}, "
                f"gauges={recon.get('mdx_regime')}."
            )
    else:
        reasons.append("CaseLab context is unavailable.")

    hmm_grade, hmm_reasons = _hmm_stability_grade(hmm)
    if hmm_grade == "WEAK":
        reasons.extend([f"HMM stability: {r}" for r in hmm_reasons])

    # K/X are unresolved research candidates. Their availability or verdict
    # cannot raise or lower the operational neutral-measurement claim ceiling.

    if validation:
        val_status = validation.get("status", "UNKNOWN")
        if val_status == "FAIL":
            reasons.append(f"Quality validation: FAILED ({validation.get('error_count', 0)} errors)")

    # ── Layered Confidence ────────────────────────────────────────────
    # Diagnostic: can we observe and report measurements?
    diagnostic_confidence = "medium"  # always at least medium if we have data
    if "PROXY_REDUCED" in str(quality):
        diagnostic_confidence = "medium_low"

    # Mechanism: can we form mechanism hypotheses?
    mechanism_confidence = "medium_low"  # base level
    if caselab_label in ("weak", "usable", "strong") and caselab_score >= 0.30:
        mechanism_confidence = "medium_low"
    if caselab_label in ("usable", "strong") and caselab_score >= 0.55:
        mechanism_confidence = "medium"
    if caselab_label == "no_reliable_analogy" or caselab_score < 0.20:
        mechanism_confidence = "low"
    # HMM model health helps mechanism confidence
    if hmm and hmm_grade in ("ADEQUATE", "HIGH"):
        # Don't downgrade mechanism confidence for calibration-only issues
        pass

    # Trade: can we make operational decisions?
    trade_confidence = "low"  # default: can't trade
    if hmm_grade in ("ADEQUATE", "HIGH") and caselab_label in ("usable", "strong"):
        trade_confidence = "medium"
    if hmm_grade == "WEAK" or caselab_label == "no_reliable_analogy":
        trade_confidence = "low"
    # K/X are research-only profiles. Their gate state is reported for review
    # but cannot promote or demote the neutral measurement judgment.

    layered = {
        "diagnostic_confidence": diagnostic_confidence,
        "mechanism_confidence": mechanism_confidence,
        "trade_confidence": trade_confidence,
    }

    # Overall confidence = trade_confidence (backward compat)
    if trade_reasons:
        reasons.extend(trade_reasons)

    if reasons:
        return trade_confidence, reasons, layered
    return trade_confidence, [
        "No major measurement conflict detected, but this is still diagnostic-only."
    ], layered


def _claim_ceiling(fw: dict[str, Any], confidence: str,
                   layered_confidence: dict[str, str] | None = None,
                   claim_ladder_tier: int = 0) -> str:
    """Determine claim ceiling using layered confidence and claim ladder.

    Supports graduated ceilings:
    - diagnostic_observation: raw measurements only
    - mechanism_hypothesis: structural comparisons allowed
    - watch_condition: monitoring conditions allowed
    - structural_diagnostic_with_caveats: limited operational
    - structural_diagnostic: full operational
    """
    validity = fw.get("basic", {}).get("validity_scope")

    # Preserve the compatibility ceiling vocabulary for tiers 0-2. Tier 3
    # must use the policy label so the old structural-diagnostic meaning cannot
    # masquerade as replay-qualified operational research.
    if claim_ladder_tier >= 3:
        from workbench.judgment.claim_ladder import CLAIM_LADDER_TIERS

        label = CLAIM_LADDER_TIERS.get(claim_ladder_tier, {}).get("label")
        if isinstance(label, str) and label:
            return label
    if claim_ladder_tier == 2:
        return "watch_condition"
    if claim_ladder_tier == 1:
        return "mechanism_hypothesis"

    # Fallback to layered confidence
    if layered_confidence:
        mech_conf = layered_confidence.get("mechanism_confidence", "low")
        if mech_conf in ("medium", "medium_high", "high"):
            return "mechanism_hypothesis"

    # Legacy fallback
    if confidence == "low":
        return "diagnostic_watch_only"
    if validity:
        return str(validity)
    return "structural_diagnostic"


def _decision(confidence: str, caselab: dict[str, Any] | None) -> str:
    if confidence == "low":
        return "WATCH_ONLY"
    if caselab and (caselab.get("match_quality") or {}).get("label") == "usable":
        return "RESEARCH_REVIEW"
    return "ACTIVE_WATCH"


def _meaning(fw: dict[str, Any], confidence: str) -> list[str]:
    basic = fw.get("basic", {})
    primary = fw.get("advanced", {}).get("primary_readout", {}) or {}
    state = primary.get("state") or basic.get("primary_market_space", "PRIMARY_READOUT_UNAVAILABLE")
    m_val, d_val = _md_values(fw)
    meaning = [
        f"Primary readout is {state}, based on two neutral macro-pressure gauges.",
        f"Funding mismatch={m_val:.3f} and market constraint={d_val:.3f}; this is a measurement, not a forecast.",
    ]
    if confidence == "low":
        meaning.append("The reading is a partial pressure observation, not a complete market-state or morphology judgment.")
    return meaning


def _risks(fw: dict[str, Any], caselab: dict[str, Any] | None) -> list[str]:
    risks = []
    basic = fw.get("basic", {})
    if "PROXY_REDUCED" in str(basic.get("quality_status", "")):
        risks.append("False precision: all live channels are proxy-reduced, so numeric values can look more exact than the measurement supports.")
    risks.append("K, X, absorption capacity, and non-commutativity are excluded research candidates, not missing operational channels.")
    if caselab:
        match = caselab.get("match_quality") or {}
        if match.get("label") == "weak":
            risks.append("CaseLab has no reliable historical analogy today.")
        recon = caselab.get("regime_reconciliation") or {}
        if recon.get("divergence"):
            risks.append("Raw-data HMM and neutral pressure direction disagree; this is a conflict to monitor, not a resolved forecast.")
    return risks or ["No specific additional risk flags beyond diagnostic-only status."]


def _actionability(confidence: str) -> dict[str, list[str]]:
    allowed = [
        "Use the card to focus research attention and daily monitoring.",
        "Inspect funding-mismatch and market-constraint components before making a narrative claim.",
        "Track whether the same pressure state persists across the next daily run.",
    ]
    forbidden = [
        "Do not use this output as a trading signal.",
        "Do not claim a complete market morphology or universal pressure model.",
        "Do not cite CaseLab as prediction when match quality is weak.",
        "Do not import K, X, absorption, or non-commutativity without a new preregistered promotion decision.",
    ]
    if confidence == "low":
        allowed.insert(0, "Keep conclusions at watch-only level.")
    return {"allowed": allowed, "forbidden": forbidden}


def _invalidation(fw: dict[str, Any], caselab: dict[str, Any] | None) -> list[str]:
    m_val, d_val = _md_values(fw)
    checks = [
        "If either neutral gauge falls below abs(0.40), downgrade the combined pressure readout.",
        "If data freshness or channel coverage degrades, mark judgment unavailable rather than carrying forward today's card.",
        "If a research-only candidate is needed for the claim, open a separate preregistered review.",
    ]
    if abs(m_val) >= 0.65 and abs(d_val) >= 0.65:
        checks.append("If the gauges stop co-moving, report them separately instead of forcing a composite narrative.")
    if caselab and (caselab.get("regime_reconciliation") or {}).get("divergence"):
        checks.append("If HMM remains crisis while the gauges show relief for several runs, open a model-conflict review instead of forcing reconciliation.")
    return checks


def _watch_window(fw: dict[str, Any], caselab: dict[str, Any] | None) -> dict[str, list[str]]:
    primary = fw.get("advanced", {}).get("primary_readout", {}) or {}
    state = primary.get("state", "PRIMARY_READOUT_UNAVAILABLE")
    one_day = [
        f"Confirm whether primary readout remains {state}.",
        "Check both neutral gauge components and data freshness.",
    ]
    if caselab and (caselab.get("regime_reconciliation") or {}).get("divergence"):
        one_day.append("Recheck HMM versus neutral-gauge divergence.")
    return {
        "1d": one_day,
        "1w": [
            "Look for persistence rather than one-day level.",
            "Review whether CaseLab match quality improves above weak threshold.",
        ],
        "1m": [
            "Review neutral-gauge common-sample evidence against public baselines.",
            "Compare judgment cards against realized market path for calibration.",
        ],
    }


def _judgment_from_trace_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    """Extract judgment card from a decision_trace bundle entry."""
    payload = entry.get("data", entry)
    if not isinstance(payload, dict):
        return None
    if payload.get("meaning") or payload.get("claim_ladder"):
        return payload
    for value in payload.values():
        if isinstance(value, dict) and (
            value.get("meaning") or value.get("claim_ladder")
        ):
            return value
    return payload.get("judgment") or payload.get("card")


def _md_direction_from_judgment(j: dict[str, Any]) -> str:
    """Resolve M/D stress direction from judgment card fields."""
    explicit = j.get("md_direction")
    if explicit:
        return str(explicit)
    cl = j.get("claim_ladder") or {}
    if cl.get("md_direction"):
        return str(cl["md_direction"])
    values = j.get("md_values") or j.get("measurement_values") or {}
    if not isinstance(values, dict):
        values = {}
    m_val = _as_float(values.get("M", values.get("m")))
    d_val = _as_float(values.get("D", values.get("d")))
    stress_dir = (m_val + d_val) / 2.0
    if stress_dir > 0.3:
        return "stress_building"
    if stress_dir < -0.3:
        return "stress_relief"
    return "neutral"


def _load_run_history(max_runs: int = 5) -> list[dict[str, Any]]:
    """Load recent run summaries for claim ladder persistence checking.

    Reads from Output/runs/ bundle directories via decision_trace.json,
    which stores the actual judgment card snapshots per run.
    """
    runs_dir = ROOT / "Output" / "runs"
    if not runs_dir.exists():
        return []

    history = []
    # Sort by directory name (timestamp-based) descending
    run_dirs = sorted(runs_dir.iterdir(), reverse=True)
    for run_dir in run_dirs[:max_runs]:
        trace_path = run_dir / "decision_trace.json"
        if not trace_path.exists():
            continue
        try:
            traces = json.loads(trace_path.read_text(encoding="utf-8"))
            if not traces:
                continue
            j = None
            for trace in traces:
                j = _judgment_from_trace_entry(trace)
                if j:
                    break
            if not j:
                continue

            history.append({
                "run_id": run_dir.name,
                "md_direction": _md_direction_from_judgment(j),
                "decision": j.get("decision", "unknown"),
                "claim_ladder": j.get("claim_ladder", {}),
            })
        except Exception as exc:
            logger.warning(
                "Unable to read prior judgment history for %s: %s",
                run_dir,
                type(exc).__name__,
            )
            continue
    return history


def _adapter_timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _adapter_chain(
    *,
    as_of: str,
    run_id: str,
    source_release_id: str = "",
    source_id: str,
    series_id: str,
    value: Any,
    claim_text: str,
    predicate: str,
    measurement_definition: str,
    derivation: str,
    evidence_role: str,
    research_only: bool = False,
) -> dict[str, Any]:
    """Adapt one subsystem result into Evidence -> Claim before synthesis."""

    captured_at = _adapter_timestamp()
    provenance = {
        "captured_at": captured_at,
        "producer": "judgment_input_adapter",
        "run_id": run_id,
        "source_component": source_id,
    }
    observation = build_observation(
        canonical_series_id=series_id,
        observed_at=as_of,
        vintage_at=as_of,
        value=value,
        source_id=source_id,
        status="AVAILABLE",
        provenance=provenance,
    )
    measurement = build_measurement(
        observation_ids=[observation["observation_id"]],
        measurement_definition=measurement_definition,
        method_version="judgment_input_adapter.v1",
        value=value,
        status="AVAILABLE",
        derivation=derivation,
        provenance=provenance,
    )
    evidence = build_evidence(
        measurement_ids=[measurement["measurement_id"]],
        evidence_role=evidence_role,
        source_id=source_id,
        # ``run_id`` identifies the judgment generation.  ``release_id``
        # identifies the data release that supports the auxiliary claim.
        # Never fall back to run_id: an empty release stamp is omitted by
        # admission, but a run_id stamp is a RELEASE_ID_MISMATCH.
        release_id=source_release_id,
        status="AVAILABLE",
        provenance=provenance,
    )
    claim = build_claim(
        claim_text=claim_text,
        subject=series_id,
        predicate=predicate,
        evidence_ids=[evidence["evidence_id"]],
        status="WATCH",
        policy_version="judgment_input_adapter.v1",
        provenance={
            **provenance,
            "research_only": research_only,
            "promotion_allowed": False,
        },
    )
    return build_chain(
        observation=observation,
        measurement=measurement,
        evidence=evidence,
        claim=claim,
    )


def _framework_claim_chain(fw: dict[str, Any]) -> dict[str, Any]:
    raw_chain = fw.get("canonical_chain")
    if isinstance(raw_chain, dict):
        validate_chain(raw_chain)
        return dict(raw_chain)
    date_str = _date_from_framework(fw)
    m_val, d_val = _md_values(fw)
    provenance = fw.get("provenance") or {}
    run_id = str(provenance.get("run_id") or fw.get("run_id") or "judgment-adapter")
    source_release_id = str(
        provenance.get("source_release_id")
        or provenance.get("release_id")
        or ""
    )
    return _adapter_chain(
        as_of=date_str,
        run_id=run_id,
        source_release_id=source_release_id,
        source_id="framework:neutral_pressure",
        series_id="SYSTEM:NEUTRAL_PRESSURE_PANEL",
        value={"M": m_val, "D": d_val},
        claim_text="The neutral pressure panel reports the typed M/D readout for this as-of date.",
        predicate="reports_neutral_pressure_readout",
        measurement_definition="neutral_pressure_readout",
        derivation="OBSERVED",
        evidence_role="PRIMARY",
    )


def _claim_envelopes(
    fw: dict[str, Any],
    caselab: dict[str, Any] | None,
    hmm: dict[str, Any] | None,
    k_gate: dict[str, Any] | None,
    x_gate: dict[str, Any] | None,
) -> tuple[list[ClaimEnvelope], dict[str, Any]]:
    """Convert raw subsystem surfaces into canonical claims and typed context."""

    date_str = _date_from_framework(fw)
    fw_provenance = fw.get("provenance") or {}
    run_id = str(fw_provenance.get("run_id") or fw.get("run_id") or "judgment-adapter")
    envelopes = [ClaimEnvelope(_framework_claim_chain(fw), role="supporting")]
    primary_evidence = envelopes[0].canonical_chain.get("evidence") or {}
    source_release_id = str(
        fw_provenance.get("source_release_id")
        or fw_provenance.get("release_id")
        or (primary_evidence.get("source") or {}).get("release_id")
        or (primary_evidence.get("provenance") or {}).get("source_release_id")
        or ""
    )
    reconciliation = (caselab or {}).get("regime_reconciliation", {}) if caselab else {}
    context: dict[str, Any] = {
        "run_id": run_id,
        "data_quality_grade": (
            (fw.get("basic") or {}).get("data_quality_grade")
            or (fw.get("basic") or {}).get("quality_status")
            or "C"
        ),
        "hmm_conflict": bool(reconciliation.get("divergence", False)),
        "claim_source_count": 1,
    }

    if caselab is not None:
        match = caselab.get("match_quality") or {}
        label = str(match.get("label") or "unknown")
        score = _as_float(match.get("top_score"))
        envelopes.append(
            ClaimEnvelope(
                _adapter_chain(
                    as_of=date_str,
                    run_id=run_id,
                    source_release_id=source_release_id,
                    source_id="caselab:daily_signal",
                    series_id="CASELAB:TOP_MATCH_SCORE",
                    value={"label": label, "top_score": score},
                    claim_text=f"CaseLab reports a {label} structural match assessment.",
                    predicate="reports_structural_match_assessment",
                    measurement_definition="caselab_match_quality",
                    derivation="MODELED",
                    evidence_role="SECONDARY",
                ),
                role="conflicting" if context["hmm_conflict"] else "supporting",
            )
        )
        context["caselab_top_score"] = score
        context["active_mechanism_count"] = len(
            ((caselab.get("mechanism_context") or {}).get("mechanism_types") or [])
        )

    if hmm is not None:
        regime = hmm.get("regime") or {}
        current = str(regime.get("current") or "unknown")
        envelopes.append(
            ClaimEnvelope(
                _adapter_chain(
                    as_of=date_str,
                    run_id=run_id,
                    source_release_id=source_release_id,
                    source_id="hmm:regime_model",
                    series_id="HMM:REGIME",
                    value=regime,
                    claim_text=f"HMM reports the regime state {current} for this run.",
                    predicate="reports_regime_state",
                    measurement_definition="hmm_regime_state",
                    derivation="MODELED",
                    evidence_role="SECONDARY",
                ),
                role="conflicting" if context["hmm_conflict"] else "supporting",
            )
        )

    # K/X are explicitly research-only profiles. They can be carried for
    # review visibility, but the synthesizer excludes them from support and
    # conflict authority.
    for name, gate in (("K", k_gate), ("X", x_gate)):
        if gate is None:
            continue
        verdict = str(gate.get("gate_verdict") or "UNKNOWN")
        envelopes.append(
            ClaimEnvelope(
                _adapter_chain(
                    as_of=date_str,
                    run_id=run_id,
                    source_release_id=source_release_id,
                    source_id=f"deformation:{name.lower()}",
                    series_id=f"DEFORMATION:{name}",
                    value={"gate_verdict": verdict},
                    claim_text=f"Research-only {name} profile reports gate state {verdict}.",
                    predicate="requests_research_review",
                    measurement_definition=f"deformation_{name.lower()}_gate",
                    derivation="MODELED",
                    evidence_role="CONTEXT",
                    research_only=True,
                ),
                role="research_only",
                research_only=True,
            )
        )

    context["claim_source_count"] = len(envelopes)
    return envelopes, context


def _credibility_assessment(
    fw: dict[str, Any],
    caselab: dict[str, Any] | None,
    claims: list[ClaimEnvelope],
) -> dict[str, Any]:
    basic = fw.get("basic") or {}
    return {
        "source_quality": "available" if fw else "missing",
        "freshness": "available" if fw.get("as_of") else "unknown",
        "measurement_validity": basic.get("validity_scope", "unknown"),
        "evidence_independence": "multiple_sources" if len(claims) > 1 else "single_source",
        "contradiction": "present" if (caselab or {}).get("regime_reconciliation", {}).get("divergence") else "none",
        "coverage": basic.get("overall", basic.get("quality_status", "unknown")),
        "semantic_fit": "bounded_neutral_measurement",
        "statistical_support": (caselab or {}).get("match_quality", {}).get("label", "unavailable"),
    }


def _calibration_assessment(validation: dict[str, Any] | None) -> dict[str, Any]:
    source = validation or {}
    return {
        "historical_bucket": source.get("calibration_bucket", "insufficient"),
        "resolved_count": int(source.get("resolved_count", 0) or 0),
        "hit_rate": source.get("hit_rate"),
        "false_positive_rate": source.get("false_positive_rate"),
        "overconfidence_error": source.get("overconfidence_error"),
    }


def build_judgment(fw: dict[str, Any], caselab: dict[str, Any] | None = None,
                   hmm: dict[str, Any] | None = None,
                   k_gate: dict[str, Any] | None = None,
                   x_gate: dict[str, Any] | None = None,
                   validation: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a compatibility judgment card backed by canonical Claims."""

    date_str = _date_from_framework(fw)
    m_val, d_val = _md_values(fw)
    confidence, confidence_reasons, layered_confidence = _confidence(
        fw, caselab, hmm, k_gate, x_gate, validation
    )
    claims, evidence_context = _claim_envelopes(fw, caselab, hmm, k_gate, x_gate)

    from workbench.judgment.claim_ladder import evaluate_claim_tier

    mechanism_ctx = (caselab or {}).get("mechanism_context")
    run_history = _load_run_history()
    claim_ladder = evaluate_claim_tier(
        judgment={"md_values": {"M": m_val, "D": d_val}},
        caselab=caselab,
        hmm=hmm,
        mechanism_context=mechanism_ctx,
        run_history=run_history,
        evidence_context=evidence_context,
        claims=[{"claim_id": item.canonical_chain["claim"]["claim_id"]} for item in claims],
    )

    decision = _decision(confidence, caselab)
    claim_ceiling = _claim_ceiling(fw, confidence, layered_confidence, claim_ladder.tier)
    meaning = _meaning(fw, confidence)
    invalidation = _invalidation(fw, caselab)
    primary_claim_id = claims[0].canonical_chain["claim"]["claim_id"]
    invalidation_spec_ids = [
        build_invalidation_spec_id(claim_id=primary_claim_id, specification=item)
        for item in invalidation
    ]
    generated_at = datetime.now(UTC).isoformat()
    credibility = _credibility_assessment(fw, caselab, claims)
    calibration = _calibration_assessment(validation)
    unknowns: list[str] = []
    if caselab is None:
        unknowns.append("CaseLab context unavailable")
    if hmm is None:
        unknowns.append("HMM context unavailable")
    if not calibration.get("resolved_count"):
        unknowns.append("Historical judgment calibration is insufficient")
    if k_gate is not None or x_gate is not None:
        unknowns.append("K/X remain research-only profiles")
    judgment_status = (
        "CONFLICTED"
        if evidence_context.get("hmm_conflict")
        else ("DIAGNOSTIC_ONLY" if confidence == "low" else "WATCH")
    )
    synthesis = JudgmentSynthesizer().synthesize(
        claims=claims,
        as_of=date_str,
        decision=decision,
        claim_ceiling=claim_ceiling,
        confidence={
            "measurement": layered_confidence.get("diagnostic_confidence", "unknown"),
            "evidence": "medium" if len(claims) > 1 else "low",
            "mechanism": layered_confidence.get("mechanism_confidence", "unknown"),
            "calibration": calibration.get("historical_bucket", "insufficient"),
            "overall": confidence,
        },
        unknowns=unknowns,
        invalidation_spec_ids=invalidation_spec_ids,
        policy_version="judgment_policy.v1",
        decision_time=generated_at,
        status=judgment_status,
        provenance={"producer": "judgment_layer", "run_id": evidence_context.get("run_id", "")},
    )
    record = synthesis["judgment"]

    return {
        "schema_version": "system.judgment_card.v1",
        "generated_at": generated_at,
        "as_of": date_str,
        "judgment_id": record["judgment_id"],
        "decision": decision,
        "md_direction": claim_ladder.md_direction,
        "md_values": {"M": m_val, "D": d_val},
        "confidence": {
            "level": confidence,
            "reasons": confidence_reasons,
            "layered": layered_confidence,
        },
        "credibility_assessment": credibility,
        "calibration": calibration,
        "claim_ceiling": claim_ceiling,
        "claim_ladder": claim_ladder.to_dict(),
        "meaning": meaning,
        "risk": _risks(fw, caselab),
        "actionability": _actionability(confidence),
        "invalidation": invalidation,
        "invalidation_spec_ids": invalidation_spec_ids,
        "watch_window": _watch_window(fw, caselab),
        "gate_status": {
            "hmm_stability": _hmm_stability_grade(hmm)[0],
            "k_gate": (k_gate or {}).get("gate_verdict", "NOT_AVAILABLE"),
            "x_gate": (x_gate or {}).get("gate_verdict", "NOT_AVAILABLE"),
            "quality_validation": (validation or {}).get("status", "NOT_AVAILABLE"),
        },
        "judgment_record": record,
        "canonical_chain": synthesis["canonical_chain"],
        "canonical_claim_chains": synthesis["canonical_chains"],
        "canonical_ids": synthesis["canonical_ids"],
        "claim_ids": synthesis["claim_ids"],
        "supporting_claim_ids": synthesis["supporting_claim_ids"],
        "conflicting_claim_ids": synthesis["conflicting_claim_ids"],
        "research_only_claim_ids": synthesis["research_only_claim_ids"],
        "inputs": {
            "neutral_pressure_snapshot": str(PRESSURE_PATH),
            "caselab": str(CASELAB_DIR / f"{date_str}.json") if caselab else None,
            "hmm": str(HMM_PATH),
            "k_gate": str(K_GATE_PATH),
            "x_gate": str(X_GATE_PATH),
            "validation": str(VALIDATION_PATH),
        },
    }


def format_markdown(card: dict[str, Any]) -> str:
    lines = [
        f"# Judgment Card - {card['as_of']}",
        "",
        f"- Decision: {card['decision']}",
        f"- Confidence: {card['confidence']['level']}",
        f"- Claim ceiling: {card['claim_ceiling']}",
        "",
        "## Meaning",
        "",
    ]
    lines.extend(f"- {item}" for item in card["meaning"])
    lines += ["", "## Risk", ""]
    lines.extend(f"- {item}" for item in card["risk"])
    lines += ["", "## Actionability", "", "### Allowed", ""]
    lines.extend(f"- {item}" for item in card["actionability"]["allowed"])
    lines += ["", "### Forbidden", ""]
    lines.extend(f"- {item}" for item in card["actionability"]["forbidden"])
    lines += ["", "## Invalidation", ""]
    lines.extend(f"- {item}" for item in card["invalidation"])
    lines += ["", "## Watch Window", ""]
    for horizon, items in card["watch_window"].items():
        lines.append(f"### {horizon}")
        lines.extend(f"- {item}" for item in items)
        lines.append("")
    lines += ["## Confidence Rationale", ""]
    lines.extend(f"- {item}" for item in card["confidence"]["reasons"])
    return "\n".join(lines).rstrip() + "\n"


def write_dated_outputs(card: dict[str, Any]) -> dict[str, Path]:
    """Write only dated judgment files — does not update latest.*"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    date_str = card["as_of"]
    json_path = OUTPUT_DIR / f"{date_str}.json"
    md_path = OUTPUT_DIR / f"{date_str}.md"
    json_text = json.dumps(card, indent=2, ensure_ascii=False) + "\n"
    md_text = format_markdown(card)
    json_path.write_text(json_text, encoding="utf-8")
    md_path.write_text(md_text, encoding="utf-8")
    return {"json": json_path, "markdown": md_path}


def write_outputs(card: dict[str, Any]) -> dict[str, Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    date_str = card["as_of"]
    json_path = OUTPUT_DIR / f"{date_str}.json"
    md_path = OUTPUT_DIR / f"{date_str}.md"
    latest_json = OUTPUT_DIR / "latest.json"
    latest_md = OUTPUT_DIR / "latest.md"
    json_text = json.dumps(card, indent=2, ensure_ascii=False) + "\n"
    md_text = format_markdown(card)
    json_path.write_text(json_text, encoding="utf-8")
    latest_json.write_text(json_text, encoding="utf-8")
    md_path.write_text(md_text, encoding="utf-8")
    latest_md.write_text(md_text, encoding="utf-8")
    return {
        "json": json_path,
        "markdown": md_path,
        "latest_json": latest_json,
        "latest_markdown": latest_md,
    }
