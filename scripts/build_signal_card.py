"""Build signal card — structured judgment explanation.

Reads current artifacts and produces a signal_card.md and signal_card.json
that explain WHY the system made its current judgment, not just WHAT it is.

This is the system's "explain your reasoning" capability — reverse-differentiation
style: which components contributed, which would change the judgment if altered.

Usage:
    python3 scripts/build_signal_card.py
    python3 scripts/build_signal_card.py --json
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CURRENT = ROOT / "Output" / "current"
JUDGMENT = ROOT / "Output" / "judgment"
TRADE_DECISION = ROOT / "Output" / "trade_decision"
CASELAB = ROOT / "Output" / "caselab"
HMM = ROOT / "Output" / "ml_signals" / "latest"


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_caselab_today() -> dict[str, Any] | None:
    """Load today's CaseLab artifact."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    return _load_json(CASELAB / f"{today}.json")


def _decompose_channels(fw: dict) -> list[dict[str, Any]]:
    """Decompose M/D/K/X into direction, size, confidence, primary-readout eligibility."""
    channels = []
    adv = fw.get("advanced", {}) if fw else {}
    sv = adv.get("sigma_vector", {})
    eligibility = sv.get("measurement_eligibility", {})

    # Read per-channel contributors from channel_confidence
    channel_conf = adv.get("channel_confidence", {})

    for ch in ["M", "D", "K", "X_agg"]:
        raw = sv.get(ch)
        elig = eligibility.get(ch, {})
        role = elig.get("readout_role", "unknown")
        status = elig.get("current_status", "UNKNOWN")
        reason = elig.get("reason", "")
        is_primary = role == "primary_readout"
        contributors = channel_conf.get(ch, {}).get("contributors", [])

        # Direction
        if raw is None:
            direction = "N/A"
        elif isinstance(raw, (int, float)):
            if raw > 0.4:
                direction = "bullish"
            elif raw < -0.4:
                direction = "bearish"
            else:
                direction = "neutral"
        else:
            direction = "N/A"

        # Size
        if raw is None or not isinstance(raw, (int, float)):
            size = "N/A"
        else:
            abs_val = abs(raw)
            if abs_val > 1.5:
                size = "large"
            elif abs_val > 0.7:
                size = "moderate"
            elif abs_val > 0.3:
                size = "small"
            else:
                size = "negligible"

        # Confidence in this channel's reading
        if status in ("PRIMARY_CORE",):
            confidence = "high"
        elif status in ("THEORY_RETAINED_MEASUREMENT_INCOMPLETE",):
            confidence = "low"
        elif status in ("BACKGROUND_ONLY_REBUILD_REQUIRED",):
            confidence = "very_low"
        else:
            confidence = "medium"

        # Readout classification
        if is_primary:
            readout_class = "primary_readout"
        elif role == "diagnostic_rebuild":
            readout_class = "diagnostic_only"
        elif role == "background_only":
            readout_class = "background_only"
        else:
            readout_class = "unknown"

        channels.append({
            "channel": ch,
            "value": round(raw, 3) if isinstance(raw, (int, float)) else raw,
            "direction": direction,
            "size": size,
            "confidence": confidence,
            "primary_readout_eligible": is_primary,
            "readout_class": readout_class,
            "framework_role": elig.get("framework_role", ""),
            "status_detail": status,
            "reason": reason,
            "contributors": contributors,
        })

    return channels


def _classify_gates(judgment: dict, fw: dict, hmm_data: dict | None,
                     caselab_data: dict | None) -> list[dict[str, str]]:
    """Classify HMM, CaseLab, K/X gates as adopted / rejected / monitoring-only."""
    gates = []
    gate_status = judgment.get("gate_status", {})
    adv = fw.get("advanced", {}) if fw else {}
    eligibility = adv.get("sigma_vector", {}).get("measurement_eligibility", {})

    # HMM stability
    hmm_val = gate_status.get("hmm_stability", "UNKNOWN")
    if hmm_val == "PASS":
        hmm_class = "adopted"
    elif hmm_val in ("WEAK", "ADEQUATE"):
        hmm_class = "monitoring_only"
    elif hmm_val == "BLOCKED":
        hmm_class = "rejected"
    else:
        hmm_class = "unknown"

    hmm_detail = ""
    hmm_degeneracy = {}
    if hmm_data:
        regime = hmm_data.get("regime", {})
        degeneracy = hmm_data.get("degeneracy", {})
        stability = hmm_data.get("stability", {})
        hmm_degeneracy = degeneracy
        usable = degeneracy.get("usable_for_core_judgment", False)
        flags = degeneracy.get("flags", [])
        warnings = degeneracy.get("warnings", [])
        hmm_detail = (
            f"regime={regime.get('current', '?')}, prob={regime.get('probability', '?')}, "
            f"usable={usable}, flags={flags}, features={stability.get('feature_count', '?')}"
        )
        if warnings:
            hmm_detail += f", warnings={warnings}"

    gates.append({
        "gate": "HMM_stability",
        "verdict": hmm_val,
        "classification": hmm_class,
        "detail": hmm_detail or f"HMM stability = {hmm_val}",
        "effect_on_judgment": "contributes" if hmm_class == "adopted"
            else "blocked_from_primary" if hmm_class == "rejected"
            else "excluded_from_readout",
        "degeneracy": hmm_degeneracy,
    })

    # K gate
    k_val = gate_status.get("k_gate", "UNKNOWN")
    k_elig = eligibility.get("K", {})
    k_role = k_elig.get("readout_role", "unknown")
    k_class = "adopted" if k_val == "PASS" and k_role == "primary_readout" \
        else "monitoring_only" if k_val == "PASS" and k_role != "primary_readout" \
        else "rejected"
    gates.append({
        "gate": "K_measurement",
        "verdict": k_val,
        "classification": k_class,
        "detail": f"K gate={k_val}, role={k_role}",
        "effect_on_judgment": "contributes" if k_class == "adopted"
            else "diagnostic_only" if k_class == "monitoring_only"
            else "blocked_from_primary",
    })

    # X gate
    x_val = gate_status.get("x_gate", "UNKNOWN")
    x_elig = eligibility.get("X_agg", {})
    x_role = x_elig.get("readout_role", "unknown")
    x_class = "adopted" if x_val == "PASS" and x_role == "primary_readout" \
        else "monitoring_only" if x_val == "PASS" and x_role != "primary_readout" \
        else "rejected"
    gates.append({
        "gate": "X_measurement",
        "verdict": x_val,
        "classification": x_class,
        "detail": f"X gate={x_val}, role={x_role}",
        "effect_on_judgment": "contributes" if x_class == "adopted"
            else "diagnostic_only" if x_class == "monitoring_only"
            else "blocked_from_primary",
    })

    # CaseLab
    mq = caselab_data.get("match_quality", {}) if caselab_data else {}
    top_score = mq.get("top_score", 0)
    mq_label = mq.get("label", "unknown")
    thresholds = mq.get("thresholds", {})
    strong_th = thresholds.get("strong", 0.7)
    usable_th = thresholds.get("usable", 0.55)
    weak_th = thresholds.get("weak", 0.4)

    if top_score >= strong_th:
        cl_class = "adopted"
        cl_verdict = "STRONG"
    elif top_score >= usable_th:
        cl_class = "monitoring_only"
        cl_verdict = "USABLE"
    elif top_score >= weak_th:
        cl_class = "rejected"
        cl_verdict = "WEAK"
    else:
        cl_class = "rejected"
        cl_verdict = "NO_RELIABLE_ANALOGY"

    gates.append({
        "gate": "CaseLab_match",
        "verdict": cl_verdict,
        "classification": cl_class,
        "detail": f"top_score={top_score:.3f} (strong≥{strong_th}, usable≥{usable_th}, weak≥{weak_th})",
        "effect_on_judgment": "contributes" if cl_class == "adopted"
            else "background_context_only" if cl_class == "monitoring_only"
            else "excluded_from_judgment",
    })

    # Quality validation
    qv_val = gate_status.get("quality_validation", "UNKNOWN")
    gates.append({
        "gate": "quality_validation",
        "verdict": qv_val,
        "classification": "adopted" if qv_val == "PASS" else "rejected",
        "detail": f"quality_validation = {qv_val}",
        "effect_on_judgment": "contributes" if qv_val == "PASS" else "blocks_execution",
    })

    return gates


def _rank_contributing_factors(judgment: dict, fw: dict, hmm_data: dict | None = None) -> list[dict[str, str]]:
    """Rank factors contributing to the current judgment."""
    factors = []

    # HMM degeneracy — if signal is not usable, it's a limiting factor
    if hmm_data:
        degeneracy = hmm_data.get("degeneracy", {})
        if not degeneracy.get("usable_for_core_judgment", False):
            flags = degeneracy.get("flags", [])
            warnings = degeneracy.get("warnings", [])
            factors.append({
                "factor": "hmm_degeneracy",
                "impact": "limiting",
                "detail": f"HMM signal not usable: {', '.join(flags)}",
                "weight": "high",
            })
            for w in warnings[:2]:
                factors.append({
                    "factor": "hmm_degeneracy_detail",
                    "impact": "limiting",
                    "detail": w[:120],
                    "weight": "medium",
                })

    # Gate status — highest weight
    gate_status = judgment.get("gate_status", {})
    for gate, value in gate_status.items():
        if value not in ("PASS",):
            if value == "ADEQUATE":
                detail = f"{gate} = {value} (model health passed; calibration still limited)"
            else:
                detail = f"{gate} = {value}"
            factors.append({
                "factor": f"gate_{gate}",
                "impact": "blocking" if value == "BLOCKED" else "limiting",
                "detail": detail,
                "weight": "high" if value in ("BLOCKED", "WEAK") else "medium",
            })

    # Confidence reasons
    conf = judgment.get("confidence", {})
    if isinstance(conf, dict):
        for reason in conf.get("reasons", [])[:3]:
            factors.append({
                "factor": "confidence",
                "impact": "limiting",
                "detail": reason[:120],
                "weight": "high" if "ceiling" in reason.lower() else "medium",
            })

    # Claim ceiling
    claim = judgment.get("claim_ceiling", "")
    if "diagnostic" in claim.lower() or "watch" in claim.lower():
        factors.append({
            "factor": "claim_ceiling",
            "impact": "capping",
            "detail": f"Claim ceiling: {claim}",
            "weight": "high",
        })

    # Channel coverage from framework
    if fw:
        adv = fw.get("advanced", {})
        if adv.get("measurement_blind_spot"):
            factors.append({
                "factor": "measurement_blind_spot",
                "impact": "limiting",
                "detail": f"Coverage ratio: {adv.get('coverage_ratio', 'unknown')}",
                "weight": "high",
            })

    # Sort by weight
    weight_order = {"high": 0, "medium": 1, "low": 2}
    factors.sort(key=lambda f: weight_order.get(f.get("weight", "low"), 9))

    return factors


def _analyze_counterfactuals(judgment: dict, fw: dict, hmm_data: dict | None,
                              caselab_data: dict | None) -> list[dict[str, str]]:
    """What would need to change for a different decision? Specific with real numbers."""
    counterfactuals = []
    gate_status = judgment.get("gate_status", {})
    conf = (judgment.get("confidence") or {}).get("level", "low")
    claim = judgment.get("claim_ceiling", "")
    adv = fw.get("advanced", {}) if fw else {}
    eligibility = adv.get("sigma_vector", {}).get("measurement_eligibility", {})
    sv = adv.get("sigma_vector", {})

    # HMM counterfactual — specific: removing one blocker doesn't lift ceiling
    if gate_status.get("hmm_stability") in ("WEAK", "BLOCKED"):
        hmm_regime = "?"
        if hmm_data:
            hmm_regime = hmm_data.get("regime", {}).get("current", "?")
        counterfactuals.append({
            "change": "HMM stability → ADEQUATE",
            "likely_effect": (
                f"Would remove one blocker (HMM={gate_status.get('hmm_stability', '?')}), "
                f"but claim ceiling remains {claim} because M/D proxy quality is still "
                f"PROXY_REDUCED. HMM regime={hmm_regime} would gain interpretive weight "
                f"but cannot alone lift the ceiling."
            ),
            "what_needed": "Sample days ≥ 252, rolling refit agreement ≥ 0.7, label stability ≥ 0.6",
            "current_state": f"HMM = {gate_status.get('hmm_stability', '?')}; regime={hmm_regime}",
            "removes_blocker": True,
            "lifts_ceiling": False,
        })

    # M/D counterfactual — specific with values
    m_val = sv.get("M")
    d_val = sv.get("D")
    if m_val is not None and d_val is not None:
        m_elig = eligibility.get("M", {})
        d_elig = eligibility.get("D", {})
        m_status = m_elig.get("current_status", "?")
        d_status = d_elig.get("current_status", "?")
        if m_status == "PRIMARY_CORE" and d_status == "PRIMARY_CORE":
            counterfactuals.append({
                "change": "M/D proxy quality → FULL_PROXY (not PROXY_REDUCED)",
                "likely_effect": (
                    f"M={m_val:.3f}, D={d_val:.3f} are already primary-eligible. "
                    f"Improving proxy quality would increase confidence from {conf} to medium. "
                    f"Claim ceiling could lift from {claim} to operational."
                ),
                "what_needed": "Reduce semantic distance from 3 to ≤ 2 for M and D proxies",
                "current_state": f"M={m_val:.3f} ({m_status}), D={d_val:.3f} ({d_status})",
                "removes_blocker": True,
                "lifts_ceiling": True,
            })

    # K channel counterfactual — diagnostic only, not primary
    k_elig = eligibility.get("K", {})
    k_status = k_elig.get("current_status", "?")
    k_val = sv.get("K")
    if k_status == "THEORY_RETAINED_MEASUREMENT_INCOMPLETE" and k_val is not None:
        counterfactuals.append({
            "change": "K channel → measurement-complete",
            "likely_effect": (
                f"K={k_val:.3f} if measured reliably would add curvature dimension to "
                f"primary readout. Currently K is diagnostic-only; even if measured, it "
                f"would not change the primary state from MIXED_ANCHOR_PATH_STRESS "
                f"unless it crosses ±0.4."
            ),
            "what_needed": "Vol surface + realized vol/jump + cross-asset curvature pass measurement gate",
            "current_state": f"K={k_val:.3f}, status={k_status}",
            "removes_blocker": False,
            "lifts_ceiling": False,
        })

    # X_agg counterfactual — background only
    x_elig = eligibility.get("X_agg", {})
    x_status = x_elig.get("current_status", "?")
    x_val = sv.get("X_agg")
    if x_status == "BACKGROUND_ONLY_REBUILD_REQUIRED" and x_val is not None:
        counterfactuals.append({
            "change": "X_agg → measurement-eligible",
            "likely_effect": (
                f"X_agg={x_val:.3f} if discrimination-retested would add shadow-leverage "
                f"dimension. Currently background-only; even if activated, it would be a "
                f"fourth input, not a replacement for M/D primary readout."
            ),
            "what_needed": "Daily/weekly shadow leverage data pass discrimination retest",
            "current_state": f"X_agg={x_val:.3f}, status={x_status}",
            "removes_blocker": False,
            "lifts_ceiling": False,
        })

    # CaseLab counterfactual — specific with gap numbers
    mq = caselab_data.get("match_quality", {}) if caselab_data else {}
    top_score = mq.get("top_score", 0)
    thresholds = mq.get("thresholds", {})
    usable_th = thresholds.get("usable", 0.55)
    strong_th = thresholds.get("strong", 0.7)

    if top_score < usable_th:
        gap_to_usable = usable_th - top_score
        gap_to_strong = strong_th - top_score
        counterfactuals.append({
            "change": f"CaseLab match score → usable (≥{usable_th})",
            "likely_effect": (
                f"Top score is {top_score:.3f}, gap to usable threshold is {gap_to_usable:.3f}. "
                f"At usable, CaseLab could contribute historical analogy as background context. "
                f"At strong (gap={gap_to_strong:.3f}), it could support claim ceiling upgrade."
            ),
            "what_needed": "CaseLab match score > 0.55 with approved source",
            "current_state": f"top_score={top_score:.3f}, label={mq.get('label', '?')}",
            "removes_blocker": False,
            "lifts_ceiling": False,
        })

    # Claim ceiling counterfactual — requires all three conditions
    if "diagnostic" in claim.lower():
        counterfactuals.append({
            "change": "Claim ceiling → operational",
            "likely_effect": (
                "System could make active trade decisions. "
                "Requires: (1) all primary channels at FULL_PROXY, "
                "(2) CaseLab ≥ usable, (3) HMM stability ≥ ADEQUATE. "
                "Current blockers: proxy quality, CaseLab, HMM."
            ),
            "what_needed": "All three conditions above simultaneously",
            "current_state": f"Claim ceiling = {claim}",
            "removes_blocker": True,
            "lifts_ceiling": True,
        })

    return counterfactuals


def _identify_evidence_list(judgment: dict, fw: dict) -> list[dict[str, str]]:
    """List all evidence that supports the current judgment."""
    evidence = []

    # HMM signal with degeneracy status
    hmm_path = HMM / "regime_hmm.json"
    hmm_sig = _load_json(hmm_path) if HMM.exists() else None
    if hmm_sig:
        regime = hmm_sig.get("regime", {})
        degeneracy = hmm_sig.get("degeneracy", {})
        usable = degeneracy.get("usable_for_core_judgment", False)
        flags = degeneracy.get("flags", [])
        reliability = "diagnostic" if not usable else "adopted"
        evidence.append({
            "source": "hmm_regime_signal",
            "type": "ml_signal",
            "value": (
                f"regime={regime.get('current', '?')}, "
                f"usable={usable}, flags={flags}"
            ),
            "reliability": reliability,
        })

    # From judgment
    evidence.append({
        "source": "judgment_layer",
        "type": "decision",
        "value": judgment.get("decision", "UNKNOWN"),
        "reliability": "primary",
    })

    # Gate statuses
    for gate, value in judgment.get("gate_status", {}).items():
        if value == "ADEQUATE":
            reliability = "model health passed; calibration still limited"
        elif value == "PASS":
            reliability = "high"
        else:
            reliability = "limiting"
        evidence.append({
            "source": f"gate_{gate}",
            "type": "gate_verdict",
            "value": str(value),
            "reliability": reliability,
        })

    # Framework status
    if fw:
        evidence.append({
            "source": "framework_output",
            "type": "framework_status",
            "value": fw.get("status", "UNKNOWN"),
            "reliability": "primary",
        })
        adv = fw.get("advanced", {})
        if adv.get("sigma_vector"):
            sv = adv["sigma_vector"]
            for ch in ["M", "D", "K", "X_agg"]:
                if ch in sv:
                    evidence.append({
                        "source": f"sigma_vector_{ch}",
                        "type": "channel_value",
                        "value": f"{sv[ch]:.3f}" if isinstance(sv[ch], (int, float)) else str(sv[ch]),
                        "reliability": "measurement",
                    })

    return evidence


def build_signal_card() -> dict[str, Any]:
    """Build the complete signal card with channel decomposition and gate classification."""
    judgment = _load_json(JUDGMENT / "latest.json")
    fw = _load_json(CURRENT / "framework_output.json")
    trade = _load_json(TRADE_DECISION / "latest.json")
    hmm_data = _load_json(HMM / "regime_hmm.json")
    caselab_data = _load_caselab_today()

    if not judgment:
        return {
            "schema_version": "signal_card.v2",
            "generated_at": datetime.now(UTC).isoformat(),
            "error": "No judgment artifact found",
        }

    now = datetime.now(UTC)

    # Claim ladder from judgment card
    claim_ladder = judgment.get("claim_ladder", {})

    card = {
        "schema_version": "signal_card.v2",
        "generated_at": now.isoformat(),
        "current_reaction": {
            "decision": judgment.get("decision", "UNKNOWN"),
            "confidence": (judgment.get("confidence") or {}).get("level", "UNKNOWN"),
            "claim_ceiling": judgment.get("claim_ceiling", "UNKNOWN"),
            "claim_ladder": claim_ladder,
            "trade_decision": trade.get("decision", "NO_ARTIFACT") if trade else "NO_ARTIFACT",
            "framework_status": fw.get("status", "UNKNOWN") if fw else "UNKNOWN",
        },
        "channel_decomposition": _decompose_channels(fw),
        "gate_classification": _classify_gates(judgment, fw, hmm_data, caselab_data),
        "evidence": _identify_evidence_list(judgment, fw),
        "contributing_factors": _rank_contributing_factors(judgment, fw, hmm_data),
        "blockers": [
            b for b in (judgment.get("confidence") or {}).get("reasons", [])
            if any(kw in b.lower() for kw in ["ceiling", "limited", "diverge", "weak"])
        ][:5],
        "counterfactuals": _analyze_counterfactuals(judgment, fw, hmm_data, caselab_data),
        "confidence_explanation": {
            "level": (judgment.get("confidence") or {}).get("level", "UNKNOWN"),
            "reasons": (judgment.get("confidence") or {}).get("reasons", []),
            "claim_ceiling": judgment.get("claim_ceiling", ""),
            "what_would_improve": [
                "All gates PASS (HMM, K, X, quality)",
                "Measurement quality → FULL_PROXY or better",
                "CaseLab match → strong",
                "HMM stability → ADEQUATE or HIGH",
            ],
        },
    }

    return card


def generate_markdown(card: dict[str, Any]) -> str:
    """Generate markdown signal card with channel decomposition and gate classification."""
    if card.get("error"):
        return f"# Signal Card\n\n**Error:** {card['error']}\n"

    r = card["current_reaction"]
    lines = [
        f"# Signal Card — {card['generated_at'][:10]}",
        "",
        f"**Generated:** {card['generated_at']}",
        f"**Schema:** {card['schema_version']}",
        "",
        "---",
        "",
        "## Current Reaction",
        "",
        f"- **Decision:** {r['decision']}",
        f"- **Confidence:** {r['confidence']}",
        f"- **Claim Ceiling:** {r['claim_ceiling']}",
        f"- **Trade Decision:** {r['trade_decision']}",
        f"- **Framework Status:** {r['framework_status']}",
        "",
    ]

    # Claim ladder section
    ladder = r.get("claim_ladder", {})
    if ladder:
        lines += [
            "### Claim Ladder",
            "",
            f"- **Tier:** {ladder.get('tier', 0)} ({ladder.get('label', 'diagnostic_claim')})",
            f"- **Claim:** {ladder.get('claim_statement', 'N/A')}",
            "",
        ]
        if ladder.get("watch_conditions"):
            lines.append("**Watch conditions:**")
            for wc in ladder["watch_conditions"]:
                lines.append(f"- {wc}")
            lines.append("")
        if ladder.get("invalidation_conditions"):
            lines.append("**Invalidation conditions:**")
            for ic in ladder["invalidation_conditions"][:3]:
                lines.append(f"- {ic}")
            lines.append("")
        if ladder.get("promotion_conditions"):
            lines.append("**Promotion path:**")
            for tier_key, cond in ladder["promotion_conditions"].items():
                lines.append(f"- {tier_key}: {cond}")
            lines.append("")
        if ladder.get("demotion_risk"):
            lines.append(f"**Demotion risk:** {ladder['demotion_risk']}")
            lines.append("")

    # Channel decomposition — new section
    lines += [
        "## Channel Decomposition (M/D/K/X)",
        "",
        "| Channel | Value | Direction | Size | Confidence | Readout Class |",
        "|---------|-------|-----------|------|------------|---------------|",
    ]
    for ch in card.get("channel_decomposition", []):
        eligible = "✅" if ch["primary_readout_eligible"] else "—"
        lines.append(
            f"| {ch['channel']} | {ch['value']} | {ch['direction']} | "
            f"{ch['size']} | {ch['confidence']} | {ch['readout_class']} {eligible} |"
        )
    lines.append("")

    # Channel contributors — per-proxy breakdown
    has_contributors = any(ch.get("contributors") for ch in card.get("channel_decomposition", []))
    if has_contributors:
        lines += ["### Channel Contributors — top drivers", ""]
        for ch in card.get("channel_decomposition", []):
            ch_name = ch["channel"]
            ch_val = ch["value"]
            contributors = ch.get("contributors", [])
            readout = ch["readout_class"]
            proxy_quality = ch.get("status_detail", "")

            if not contributors:
                lines.append(f"**{ch_name}={ch_val}** — no contributor data")
                lines.append("")
                continue

            # Top voting contributors (canonical_voting only)
            voting = [c for c in contributors if c.get("canonical_status") == "canonical_voting"]
            non_voting = [c for c in contributors if c.get("canonical_status") != "canonical_voting"]

            if voting:
                top_names = [f"{c['proxy_name']} ({', '.join(c['raw_series'])})" for c in voting[:3]]
                lines.append(f"**{ch_name}={ch_val}** — 主要由 {', '.join(top_names)} 推动; 当前 {proxy_quality}")
                lines.append("")
                for c in voting[:3]:
                    z = c.get("z_score", "N/A")
                    lines.append(f"- `{c['proxy_name']}` ({', '.join(c['raw_series'])}): z={z} [{c['tier']}, {c['canonical_status']}]")
            elif non_voting:
                lines.append(f"**{ch_name}={ch_val}** — 无 canonical_voting proxy ({readout})")
                lines.append("")
                lines.append(f"- 当前 {ch_name} 代理均为 quarantined_drift，不满足 canonical 门控")
                for c in non_voting[:3]:
                    z = c.get("z_score", "N/A")
                    lines.append(f"- `{c['proxy_name']}` ({', '.join(c['raw_series'])}): z={z} [{c['canonical_status']}]")
            lines.append("")

    # Gate classification — new section
    lines += [
        "## Gate Classification (adopted / rejected / monitoring-only)",
        "",
    ]
    for g in card.get("gate_classification", []):
        icon = "✅" if g["classification"] == "adopted" \
            else "❌" if g["classification"] == "rejected" \
            else "👁️"
        lines.append(f"- {icon} **{g['gate']}** → {g['classification'].upper()}")
        lines.append(f"  - Verdict: {g['verdict']}, Effect: {g['effect_on_judgment']}")
        lines.append(f"  - Detail: {g['detail']}")
    lines.append("")

    # Evidence
    lines += [
        "## Evidence",
        "",
    ]
    for ev in card["evidence"][:12]:
        icon = "✅" if ev["reliability"] in ("primary", "high") else "⚠️" if "limiting" in ev["reliability"] else "📊"
        lines.append(f"- {icon} **{ev['source']}**: {ev['value']} ({ev['reliability']})")
    lines.append("")

    # Contributing factors
    lines += [
        "## Contributing Factors (ranked)",
        "",
    ]
    for f in card["contributing_factors"][:5]:
        icon = "🔴" if f["weight"] == "high" else "🟡" if f["weight"] == "medium" else "⚪"
        lines.append(f"- {icon} **{f['factor']}** ({f['impact']}): {f['detail']}")
    lines.append("")

    # Blockers
    lines += [
        "## Blockers",
        "",
    ]
    for b in card["blockers"]:
        lines.append(f"- {b}")
    lines.append("")

    # Counterfactuals — enhanced with specificity
    lines += [
        "## Counterfactuals (what would change the judgment)",
        "",
        "Each counterfactual shows: what changes, what effect it has, whether it removes ",
        "a blocker, and whether it lifts the claim ceiling.",
        "",
    ]
    for cf in card["counterfactuals"]:
        blocker_tag = "🔧 removes blocker" if cf.get("removes_blocker") else "— no blocker removed"
        ceiling_tag = "⬆️ lifts ceiling" if cf.get("lifts_ceiling") else "— ceiling unchanged"
        lines.append(f"### If {cf['change']}")
        lines.append(f"- **Effect:** {cf['likely_effect']}")
        lines.append(f"- **Needed:** {cf['what_needed']}")
        lines.append(f"- **Current:** {cf['current_state']}")
        lines.append(f"- **Blocker:** {blocker_tag} | **Ceiling:** {ceiling_tag}")
        lines.append("")

    # Confidence explanation
    lines += [
        "## Why Confidence Is Low",
        "",
    ]
    ce = card["confidence_explanation"]
    for reason in ce["reasons"][:3]:
        lines.append(f"- {reason}")
    lines.append("")
    lines.append("**What would improve confidence:**")
    for improvement in ce["what_would_improve"]:
        lines.append(f"- {improvement}")
    lines.append("")

    lines += [
        "---",
        "",
        "*Generated by scripts/build_signal_card.py*",
        "*Authority: judgment_layer + framework_output + quality_validation + caselab + hmm*",
    ]

    return "\n".join(lines) + "\n"


def _check_closure_chain() -> None:
    """Warn if running standalone and upstream artifacts are newer than current outputs.

    This helps detect partial refreshes where the signal card is rebuilt
    but the judgment/trade_decision haven't been updated.
    """
    judgment_path = ROOT / "Output" / "judgment" / "latest.json"
    current_card = CURRENT / "signal_card.json"

    if not judgment_path.exists():
        print("WARNING: No judgment card found. Run the full pipeline first.")
        return

    judgment_mtime = judgment_path.stat().st_mtime
    if current_card.exists():
        card_mtime = current_card.stat().st_mtime
        if judgment_mtime > card_mtime:
            print(
                "WARNING: Closure chain broken — judgment card is newer than signal card. "
                "This signal card may be stale. Re-run the full pipeline to close the chain."
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build signal card")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    # Check closure chain when running standalone
    _check_closure_chain()

    card = build_signal_card()

    CURRENT.mkdir(parents=True, exist_ok=True)

    json_path = CURRENT / "signal_card.json"
    json_path.write_text(json.dumps(card, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    md_path = CURRENT / "signal_card.md"
    md_path.write_text(generate_markdown(card), encoding="utf-8")

    if args.json:
        print(json.dumps(card, indent=2, ensure_ascii=False))
    else:
        print(generate_markdown(card))


if __name__ == "__main__":
    main()
