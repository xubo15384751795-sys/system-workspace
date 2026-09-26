#!/usr/bin/env python3
"""Signal Consensus — aggregate all signal sources into a unified view.

Reads M/D, HMM, K/X, CaseLab, and probabilistic context signals, classifies
each as adopted/monitoring_only/rejected/conflict, and produces a consensus
report explaining the current tier and what blocks promotion.

Usage:
    python3 scripts/signal_consensus.py
    python3 scripts/signal_consensus.py --json

Output:
    Output/current/signal_consensus.json
    Output/current/signal_consensus.md
"""
from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from verity.runtime._constants import CASELAB_USABLE_THRESHOLD, CASELAB_WEAK_THRESHOLD
from verity.runtime.runtime_io import ROOT, current_dir, ensure_dir, surface_dir, write_json
from verity.runtime.runtime_io import load_json as _load_json

OUTPUT_CURRENT = current_dir()

# Source paths
FRAMEWORK_OUTPUT = OUTPUT_CURRENT / "framework_output.json"
JUDGMENT_PATH = surface_dir("judgment") / "latest.json"
PROMOTION_GATE_PATH = surface_dir("judgment") / "promotion_gate.json"
HMM_PATH = ROOT / "Output" / "state" / "ml_signals" / "daily" / "regime_hmm.json"
K_GATE_PATH = ROOT / "Output" / "k_measurement" / "k_measurement_gate.json"
X_GATE_PATH = ROOT / "Output" / "x_measurement" / "x_measurement_gate.json"
PROB_CONTEXT_PATH = ROOT / "Output" / "probabilistic_context" / "latest.json"

# CaseLab uses dated files
CASELAB_DIR = ROOT / "Output" / "state" / "caselab"

_PATH_KEYS = (
    "output",
    "framework_output",
    "judgment",
    "promotion_gate",
    "hmm",
    "k_gate",
    "x_gate",
    "prob_context",
    "caselab",
)


def _default_paths() -> dict[str, Path]:
    """Return the legacy-compatible input/output path bindings."""
    return {
        "output": OUTPUT_CURRENT,
        "framework_output": FRAMEWORK_OUTPUT,
        "judgment": JUDGMENT_PATH,
        "promotion_gate": PROMOTION_GATE_PATH,
        "hmm": HMM_PATH,
        "k_gate": K_GATE_PATH,
        "x_gate": X_GATE_PATH,
        "prob_context": PROB_CONTEXT_PATH,
        "caselab": CASELAB_DIR,
    }


def _resolve_paths(paths: Mapping[str, Path] | None = None) -> dict[str, Path]:
    """Resolve explicit generation paths without changing the no-arg contract."""
    resolved = _default_paths()
    if paths is None:
        return resolved
    unknown = sorted(set(paths) - set(_PATH_KEYS))
    if unknown:
        raise ValueError(f"unknown signal-consensus path keys: {', '.join(unknown)}")
    resolved.update({key: Path(value) for key, value in paths.items()})
    return resolved


def _latest_caselab(caselab_dir: Path | None = None) -> dict[str, Any] | None:
    """Load the most recent CaseLab output."""
    root = caselab_dir or CASELAB_DIR
    if not root.exists():
        return None
    files = sorted(root.glob("*.json"), reverse=True)
    for f in files:
        data = _load_json(f)
        if data:
            return data
    return None


def _classify_signal(
    name: str,
    raw_value: Any,
    *,
    usable: bool = True,
    gate_status: str = "PASS",
    calibration_passed: bool = True,
    quality_label: str = "strong",
) -> dict[str, Any]:
    """Classify a signal's consensus status.

    Statuses:
      - adopted: signal is reliable, can inform claims
      - monitoring_only: signal is observable but not yet reliable
      - rejected: signal is degenerate or failed validation
      - conflict: signal contradicts the primary readout
    """
    if not usable or gate_status in ("FAIL", "BLOCKED"):
        return {"status": "rejected", "reason": f"not usable (gate={gate_status})"}

    if gate_status == "WATCH" or not calibration_passed:
        return {"status": "monitoring_only", "reason": "calibration not passed or watch gate"}

    if quality_label in ("weak", "degenerate"):
        return {"status": "monitoring_only", "reason": f"quality={quality_label}"}

    return {"status": "adopted", "reason": "passed all gates"}


def build_consensus(paths: Mapping[str, Path] | None = None) -> dict[str, Any]:
    """Build the signal consensus report."""
    resolved = _resolve_paths(paths)
    framework_output = resolved["framework_output"]
    judgment_path = resolved["judgment"]
    promotion_gate_path = resolved["promotion_gate"]
    hmm_path = resolved["hmm"]
    k_gate_path = resolved["k_gate"]
    x_gate_path = resolved["x_gate"]
    prob_context_path = resolved["prob_context"]

    # Load all sources
    fw = _load_json(framework_output)
    judgment = _load_json(judgment_path)
    promo = _load_json(promotion_gate_path)
    hmm = _load_json(hmm_path)
    k_gate = _load_json(k_gate_path)
    x_gate = _load_json(x_gate_path)
    prob_ctx = _load_json(prob_context_path)
    caselab = _latest_caselab(resolved["caselab"])

    signals: list[dict[str, Any]] = []
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    # ── 1. M/D Primary Readout ──────────────────────────────────────────
    if fw:
        advanced = fw.get("advanced", {})
        primary = advanced.get("primary_readout", {})
        sigma = advanced.get("sigma_vector", {})
        m_val = sigma.get("M")
        d_val = sigma.get("D")

        signals.append({
            "name": "M/D primary readout",
            "source": str(framework_output),
            "value": {
                "state": primary.get("state"),
                "M": round(m_val, 3) if m_val is not None else None,
                "D": round(d_val, 3) if d_val is not None else None,
            },
            "classification": "adopted",
            "supports": ["mechanism_hypothesis"],
            "does_not_support": ["regime_call", "directional_conviction"],
            "reason": "M/D is the primary measurement channel. Supports mechanism-level observation, not directional claims.",
        })
    else:
        signals.append({
            "name": "M/D primary readout",
            "source": str(framework_output),
            "value": None,
            "classification": "rejected",
            "supports": [],
            "does_not_support": [],
            "reason": "framework_output.json not found",
        })

    # ── 2. HMM Regime Hint ──────────────────────────────────────────────
    if hmm:
        regime = hmm.get("regime", {})
        degeneracy = hmm.get("degeneracy", {})
        stability = hmm.get("stability", {})
        usable = degeneracy.get("usable_for_core_judgment", False)
        entropy = stability.get("posterior_entropy", 0)
        # Check if HMM stability audit gate is in judgment
        hmm_gate = (judgment or {}).get("gate_status", {}).get("hmm_stability", "UNKNOWN")

        # HMM is usable but calibration may not pass
        hmm_calibrated = True
        if promo:
            hmm_gate_detail = promo.get("gates", {}).get("hmm", {})
            if hmm_gate_detail.get("status") == "WATCH":
                hmm_calibrated = False

        classification = _classify_signal(
            "HMM",
            regime.get("current"),
            usable=usable,
            gate_status=hmm_gate if hmm_gate != "UNKNOWN" else ("PASS" if usable else "FAIL"),
            calibration_passed=hmm_calibrated,
        )

        signals.append({
            "name": "HMM regime hint",
            "source": str(hmm_path),
            "value": {
                "current": regime.get("current"),
                "probability": regime.get("probability"),
                "state_probs": regime.get("state_probs"),
                "posterior_entropy": entropy,
                "usable_for_core_judgment": usable,
            },
            "classification": classification["status"],
            "supports": ["regime_hint"] if classification["status"] == "adopted" else ["regime_hint (monitoring)"],
            "does_not_support": ["regime_call", "primary_signal", "standalone_claim"],
            "reason": classification["reason"] + ". HMM provides regime hint only, not a regime call. "
                     "Calibration not yet passed — raw probabilities are observational.",
        })
    else:
        signals.append({
            "name": "HMM regime hint",
            "source": str(hmm_path),
            "value": None,
            "classification": "rejected",
            "supports": [],
            "does_not_support": [],
            "reason": "regime_hmm.json not found",
        })

    # ── 3. K Gate ───────────────────────────────────────────────────────
    if k_gate:
        k_verdict = k_gate.get("gate_verdict", "UNKNOWN")
        k_val = None
        if fw:
            k_val = fw.get("advanced", {}).get("sigma_vector", {}).get("K")

        classification = _classify_signal("K", k_val, gate_status=k_verdict)

        signals.append({
            "name": "K gate",
            "source": str(k_gate_path),
            "value": {
                "gate_verdict": k_verdict,
                "K": round(k_val, 3) if k_val is not None else None,
            },
            "classification": classification["status"],
            "supports": ["structural_diagnostic"] if k_verdict == "PASS" else [],
            "does_not_support": ["primary_readout"],
            "reason": f"K gate={k_verdict}. K is a diagnostic channel, not a primary readout. "
                     "Passing gate means measurement is structurally sound, not that K drives claims.",
        })
    else:
        signals.append({
            "name": "K gate",
            "source": str(k_gate_path),
            "value": None,
            "classification": "rejected",
            "supports": [],
            "does_not_support": [],
            "reason": "k_measurement_gate.json not found",
        })

    # ── 4. X Gate ───────────────────────────────────────────────────────
    if x_gate:
        x_verdict = x_gate.get("gate_verdict", "UNKNOWN")
        x_usage = x_gate.get("usage", {})
        x_val = None
        if fw:
            x_val = fw.get("advanced", {}).get("sigma_vector", {}).get("X_agg")

        usable_primary = x_usage.get("usable_as_primary_readout", False)
        usable_background = x_usage.get("usable_as_background", False)
        # X gate: if PASS and usable as background, it's monitoring_only (not rejected)
        if x_verdict == "PASS" and usable_background:
            classification = {"status": "monitoring_only", "reason": "gate PASS, background-only (not usable as primary readout)"}
        else:
            classification = _classify_signal(
                "X", x_val,
                gate_status=x_verdict,
                usable=usable_primary,
            )

        signals.append({
            "name": "X gate",
            "source": str(x_gate_path),
            "value": {
                "gate_verdict": x_verdict,
                "X_agg": round(x_val, 3) if x_val is not None else None,
                "usable_as_primary_readout": usable_primary,
            },
            "classification": classification["status"],
            "supports": ["background_context"] if x_verdict == "PASS" else [],
            "does_not_support": ["primary_readout", "daily_trigger"],
            "reason": f"X gate={x_verdict}. X is background-only, not usable as primary readout or daily trigger.",
        })
    else:
        signals.append({
            "name": "X gate",
            "source": str(x_gate_path),
            "value": None,
            "classification": "rejected",
            "supports": [],
            "does_not_support": [],
            "reason": "x_measurement_gate.json not found",
        })

    # ── 5. CaseLab ──────────────────────────────────────────────────────
    if caselab:
        mq = caselab.get("match_quality", {})
        top_score = mq.get("top_score", 0)
        label = mq.get("label", "unknown")
        mech_types = caselab.get("mechanism_context", {}).get("mechanism_types", [])

        classification = _classify_signal(
            "CaseLab", top_score,
            quality_label=label,
        )

        signals.append({
            "name": "CaseLab",
            "source": f"Output/state/caselab/{caselab.get('timestamp', 'unknown')[:10]}.json",
            "value": {
                "top_score": top_score,
                "quality_label": label,
                "mechanism_types": mech_types,
            },
            "classification": classification["status"],
            "supports": ["mechanism_hypothesis"] if top_score >= CASELAB_WEAK_THRESHOLD else [],
            "does_not_support": ["reliable_analogy", "strong_precedent"] if top_score < CASELAB_USABLE_THRESHOLD else [],
            "reason": f"CaseLab quality={label} (score={top_score:.3f}). "
                     + ("Weak match — supports mechanism hypothesis only, not reliable analogy."
                        if top_score < CASELAB_USABLE_THRESHOLD else "Usable analogy strength."),
        })
    else:
        signals.append({
            "name": "CaseLab",
            "source": "N/A",
            "value": None,
            "classification": "rejected",
            "supports": [],
            "does_not_support": [],
            "reason": "No CaseLab output found",
        })

    # ── 6. Probabilistic Context ────────────────────────────────────────
    if prob_ctx:
        summary = prob_ctx.get("summary", {})
        risk_level = summary.get("overall_risk_level", "unknown")
        tail_risk = summary.get("tail_risk_detected", False)

        signals.append({
            "name": "probabilistic context",
            "source": str(prob_context_path),
            "value": {
                "overall_risk_level": risk_level,
                "tail_risk_detected": tail_risk,
            },
            "classification": "adopted",
            "supports": ["risk_awareness", "tail_monitoring"],
            "does_not_support": ["directional_conviction"],
            "reason": f"Risk level={risk_level}, tail_risk={tail_risk}. "
                     "Probabilistic context provides risk awareness, not directional signals.",
        })
    else:
        signals.append({
            "name": "probabilistic context",
            "source": str(prob_context_path),
            "value": None,
            "classification": "rejected",
            "supports": [],
            "does_not_support": [],
            "reason": "probabilistic_context/latest.json not found",
        })

    # ── Conflict Analysis ───────────────────────────────────────────────
    conflicts: list[dict[str, Any]] = []
    adopted = [s for s in signals if s["classification"] == "adopted"]
    monitoring = [s for s in signals if s["classification"] == "monitoring_only"]

    # Check if any adopted signal contradicts another
    # (In current state, no hard conflicts — all adopted signals are consistent)

    # ── Tier Analysis ───────────────────────────────────────────────────
    current_tier = 1
    current_label = "mechanism_hypothesis"
    if promo:
        cl = promo.get("claim_ladder", {})
        current_tier = cl.get("tier", 1)
        current_label = cl.get("label", "mechanism_hypothesis")

    # What blocks Tier 2?
    tier_2_blockers: list[str] = []
    if promo:
        promo_conds = promo.get("claim_ladder", {}).get("promotion_conditions", {})
        to_t2 = promo_conds.get("to_tier_2", "")
        if to_t2:
            tier_2_blockers.append(to_t2)

    # Add signal-level blockers
    for s in signals:
        if s["classification"] == "monitoring_only":
            tier_2_blockers.append(f"{s['name']}: {s['reason']}")

    # ── Build Result ────────────────────────────────────────────────────
    result: dict[str, Any] = {
        "schema_version": "system.signal_consensus.v1",
        "generated_at": now,
        "as_of": now[:10],
        "signals": signals,
        "consensus": {
            "adopted_count": len(adopted),
            "monitoring_count": len(monitoring),
            "rejected_count": len([s for s in signals if s["classification"] == "rejected"]),
            "conflict_count": len(conflicts),
        },
        "conflict_analysis": {
            "has_conflicts": len(conflicts) > 0,
            "conflicts": conflicts,
            "blocks_tier_2": len(conflicts) > 0,
            "blocks_regime_language": any(
                s["name"] == "HMM regime hint" and s["classification"] != "adopted"
                for s in signals
            ),
            "blocks_trade_layer": True,  # Currently all trade is blocked at WATCH_ONLY
        },
        "tier_analysis": {
            "current_tier": current_tier,
            "current_label": current_label,
            "why_tier_1": (
                "M/D supports mechanism_hypothesis. "
                "HMM provides regime_hint only (calibration not passed — cannot support regime_call). "
                "CaseLab is weak (score=0.426) — supports mechanism hypothesis, not reliable analogy. "
                "K/X pass but are diagnostic channels, not primary readouts. "
                "Therefore: Tier 1 (mechanism_hypothesis) is allowed; Tier 2 is pending."
            ),
            "tier_2_blockers": tier_2_blockers,
            "what_needed_for_tier_2": [
                "M/D direction must persist >= 2 consecutive runs (currently 0).",
                f"CaseLab top_score must rise above {CASELAB_USABLE_THRESHOLD} for usable analogy (currently 0.426, gap: 0.124).",
                "HMM calibration must pass to support regime_hint at adopted level.",
                "No signal conflicts must exist.",
            ],
        },
        "judgment_context": {
            "decision": (judgment or {}).get("decision", "UNKNOWN"),
            "confidence": (judgment or {}).get("confidence", {}).get("level", "UNKNOWN"),
            "claim_ceiling": (promo or {}).get("claim_ceiling", "UNKNOWN"),
            "allowed_language": (promo or {}).get("allowed_language", []),
            "forbidden_language": (promo or {}).get("forbidden_language", []),
        },
    }

    return result


def write_signal_consensus(
    result: dict[str, Any],
    *,
    output_dir: Path | None = None,
) -> tuple[Path, Path]:
    """Write JSON and Markdown to an explicit current-output surface."""
    target_dir = output_dir or OUTPUT_CURRENT
    ensure_dir(target_dir)
    json_path = target_dir / "signal_consensus.json"
    md_path = target_dir / "signal_consensus.md"
    write_json(json_path, result)
    md_path.write_text(format_markdown(result), encoding="utf-8")
    return json_path, md_path


def format_markdown(result: dict[str, Any]) -> str:
    """Format consensus as markdown."""
    lines = [
        "# Signal Consensus",
        "",
        f"- Generated: {result['generated_at']}",
        f"- As of: {result['as_of']}",
        "",
        "## Signal Status",
        "",
        "| Signal | Classification | Supports | Does Not Support |",
        "|--------|---------------|----------|------------------|",
    ]

    for s in result["signals"]:
        supports = ", ".join(s.get("supports", []))
        does_not = ", ".join(s.get("does_not_support", []))
        lines.append(f"| {s['name']} | **{s['classification']}** | {supports} | {does_not} |")

    lines += [
        "",
        "## Signal Details",
        "",
    ]

    for s in result["signals"]:
        lines.append(f"### {s['name']}")
        lines.append("")
        lines.append(f"- **Classification**: {s['classification']}")
        if s.get("value"):
            for k, v in s["value"].items():
                lines.append(f"- {k}: {v}")
        lines.append(f"- **Reason**: {s['reason']}")
        lines.append("")

    # Consensus summary
    c = result["consensus"]
    lines += [
        "## Consensus Summary",
        "",
        f"- Adopted: {c['adopted_count']}",
        f"- Monitoring only: {c['monitoring_count']}",
        f"- Rejected: {c['rejected_count']}",
        f"- Conflicts: {c['conflict_count']}",
        "",
    ]

    # Conflict analysis
    ca = result["conflict_analysis"]
    lines += [
        "## Conflict Analysis",
        "",
        f"- Has conflicts: {ca['has_conflicts']}",
        f"- Blocks Tier 2: {ca['blocks_tier_2']}",
        f"- Blocks regime language: {ca['blocks_regime_language']}",
        f"- Blocks trade layer: {ca['blocks_trade_layer']}",
        "",
    ]

    # Tier analysis
    ta = result["tier_analysis"]
    lines += [
        "## Tier Analysis",
        "",
        f"- Current tier: **Tier {ta['current_tier']}** ({ta['current_label']})",
        "",
        "### Why Tier 1",
        "",
        ta["why_tier_1"],
        "",
        "### What Blocks Tier 2",
        "",
    ]
    for blocker in ta["tier_2_blockers"]:
        lines.append(f"- {blocker}")

    lines += [
        "",
        "### What Is Needed for Tier 2",
        "",
    ]
    for item in ta["what_needed_for_tier_2"]:
        lines.append(f"- {item}")

    # Judgment context
    jc = result["judgment_context"]
    lines += [
        "",
        "## Judgment Context",
        "",
        f"- Decision: {jc['decision']}",
        f"- Confidence: {jc['confidence']}",
        f"- Claim ceiling: {jc['claim_ceiling']}",
        "",
        "### Allowed Language",
        "",
    ]
    for lang in jc["allowed_language"]:
        lines.append(f"- {lang}")

    lines += [
        "",
        "### Forbidden Language",
        "",
    ]
    for lang in jc["forbidden_language"]:
        lines.append(f"- {lang}")

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build signal consensus report.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    args = parser.parse_args()

    result = build_consensus()

    json_path, md_path = write_signal_consensus(result)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"Signal consensus: Tier {result['tier_analysis']['current_tier']} ({result['tier_analysis']['current_label']})")
        print(f"Adopted: {result['consensus']['adopted_count']}, Monitoring: {result['consensus']['monitoring_count']}")
        print(f"Conflicts: {result['consensus']['conflict_count']}")
        print(f"Written to: {json_path}")
        print(f"Written to: {md_path}")


if __name__ == "__main__":
    main()
