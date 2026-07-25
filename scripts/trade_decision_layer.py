#!/usr/bin/env python3
"""Trade Decision Layer — generate structured trade decisions.

This script synthesizes:
- System judgment card
- Paper world model
- K/X/HMM gates
- CaseLab signals

Into a structured trade decision with evidence grading.

Usage:
    python3 scripts/trade_decision_layer.py
    python3 scripts/trade_decision_layer.py --json

Output:
    Output/trade_decision/latest.json
    Output/trade_decision/latest.md
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import yaml
from paper_freshness import check_paper_world_model_freshness
from pending_evaluation import write_pending_evaluation
from workbench.judgment.trade_decision import (  # noqa: E402
    build_quality_inputs,
    compose_trade_fields,
    confidence_for_size,
    determine_size,
    determine_stance,
    evidence_grade_for_size,
)
from workbench.judgment.trade_decision import (
    build_trade_thesis as _wb_build_trade_thesis,
)

from scripts._runtime_io import (
    ROOT,
    ensure_dir,
    load_json,
    load_jsonl,
    utc_now,
    write_json,
)
from system_runtime.credit_assignment import build_trade_learning_trace

JUDGMENT_PATH = ROOT / "Output" / "judgment" / "latest.json"
PROMOTION_GATE_PATH = ROOT / "Output" / "judgment" / "promotion_gate.json"
K_GATE_PATH = ROOT / "Output" / "k_measurement" / "k_measurement_gate.json"
X_GATE_PATH = ROOT / "Output" / "x_measurement" / "x_measurement_gate.json"
HMM_AUDIT_PATH = ROOT / "Output" / "hmm_stability" / "hmm_stability_audit.json"
CASELAB_DIR = ROOT / "Output" / "caselab"
PAPER_WORLD_MODEL_DIR = ROOT / "Data" / "paper_world_model"
OUTPUT_DIR = ROOT / "Output" / "trade_decision"
PAPER_SUPPORT_REGISTRY = ROOT / "governance" / "paper_support_registry.yaml"


def _load_approved_case_ids() -> set[str]:
    if not PAPER_SUPPORT_REGISTRY.exists():
        return set()
    data = yaml.safe_load(PAPER_SUPPORT_REGISTRY.read_text(encoding="utf-8")) or {}
    return {str(case_id) for case_id in data.get("approved_case_ids", [])}


def _case_source(case: dict[str, Any], *, relevance: str) -> dict[str, Any]:
    return {
        "source_file": case.get("source_file", ""),
        "content_type": "case",
        "content_id": case.get("case_id", ""),
        "relevance": relevance,
        "review_status": case.get("review_status", "needs_review"),
    }


def _is_governance_approved(case: dict[str, Any], approved_ids: set[str]) -> bool:
    case_id = str(case.get("case_id", ""))
    if case.get("review_status") != "approved":
        return False
    if not approved_ids:
        return True
    return case_id in approved_ids


def find_paper_sources(
    caselab: dict[str, Any] | None,
    judgment: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Find relevant Paper sources for the decision.

    Returns: (approved_sources, background_sources)
    - approved_sources: can be used as mechanism support
    - background_sources: can only be used as background context
    """
    approved_sources: list[dict[str, Any]] = []
    background_sources: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    approved_ids = _load_approved_case_ids()

    cases = load_jsonl(PAPER_WORLD_MODEL_DIR / "cases.jsonl")

    def _append(case: dict[str, Any], *, relevance: str) -> None:
        case_id = str(case.get("case_id", ""))
        if not case_id or case_id in seen_ids:
            return
        seen_ids.add(case_id)
        source = _case_source(case, relevance=relevance)
        if _is_governance_approved(case, approved_ids):
            approved_sources.append(source)
        else:
            background_sources.append(source)

    if caselab:
        for match in caselab.get("matches", [])[:3]:
            case_name = match.get("case_name", "")
            relevance = "high" if match.get("score", 0) > 0.5 else "medium"
            for case in cases:
                if case_name.lower() in case.get("case_id", "").lower():
                    _append(case, relevance=relevance)
                    break

    if not approved_sources:
        ranked = sorted(
            [c for c in cases if _is_governance_approved(c, approved_ids)],
            key=lambda c: (
                0 if c.get("trade_relevance") == "high" else 1,
                str(c.get("case_id", "")),
            ),
        )
        for case in ranked[:2]:
            _append(case, relevance="medium")

    if not approved_sources and not background_sources:
        for case in [c for c in cases if c.get("trade_relevance") == "high"][:2]:
            _append(case, relevance="medium")

    return approved_sources, background_sources


def _build_system_sources(
    judgment: dict, k_gate: dict | None, x_gate: dict | None,
    hmm_audit: dict | None, caselab: dict | None,
) -> list[dict[str, Any]]:
    """Build list of system sources that informed the decision."""
    sources = []
    if judgment:
        sources.append({"source": "judgment_layer", "type": "system", "status": judgment.get("decision", "UNKNOWN")})
    if k_gate:
        sources.append({"source": "k_gate", "type": "gate", "status": k_gate.get("gate_verdict", k_gate.get("verdict", "UNKNOWN"))})
    if x_gate:
        sources.append({"source": "x_gate", "type": "gate", "status": x_gate.get("gate_verdict", x_gate.get("verdict", "UNKNOWN"))})
    if hmm_audit:
        sources.append({"source": "hmm_stability", "type": "audit", "status": hmm_audit.get("stability_grade", "UNKNOWN")})
    if caselab:
        caselab_label = caselab.get("label") or caselab.get("match_quality", {}).get("label", "UNKNOWN")
        sources.append({"source": "caselab", "type": "analogy", "status": caselab_label})
    return sources


def _build_trade_thesis(
    decision: str, judgment: dict, approved_sources: list, system_sources: list,
) -> dict[str, Any]:
    """Build trade thesis from decision and supporting evidence."""
    conf = judgment.get("confidence", {})
    conf_level = conf.get("level", "unknown") if isinstance(conf, dict) else "unknown"
    claim = judgment.get("claim_ceiling", "unknown")
    meaning = judgment.get("meaning", [])
    ladder = judgment.get("claim_ladder", {})

    hypothesis = meaning[0] if meaning else f"Decision: {decision} at confidence={conf_level}"

    thesis = {
        "hypothesis": hypothesis,
        "confidence": conf_level,
        "claim_ceiling": claim,
        "support_count": len(approved_sources),
    }

    # Add claim ladder info if available
    if ladder:
        thesis["claim_ladder"] = {
            "tier": ladder.get("tier", 0),
            "label": ladder.get("label", "diagnostic_claim"),
            "claim_statement": ladder.get("claim_statement", ""),
        }
        # Add watch/invalidation conditions to the thesis
        if ladder.get("watch_conditions"):
            thesis["watch_conditions"] = ladder["watch_conditions"]
        if ladder.get("invalidation_conditions"):
            thesis["invalidation_conditions"] = ladder["invalidation_conditions"]

    return thesis


def _resolve_velocity_gate_state() -> dict[str, Any]:
    try:
        from strategy_lab.risk_gate import latest_velocity_gate_state

        return latest_velocity_gate_state()
    except Exception as exc:  # noqa: BLE001 — decision must still emit
        return {
            "state": "UNKNOWN",
            "position": None,
            "trigger": None,
            "trigger_reason": f"unavailable: {exc}",
            "velocity_20d": None,
            "n_deteriorating": None,
            "source": "error",
            "as_of_date": None,
        }


def _load_sigma_vector() -> dict[str, Any] | None:
    """Load compatibility gauge vector from the neutral pressure snapshot."""
    fw = load_json(ROOT / "Output" / "current" / "neutral_pressure_snapshot.json")
    if not isinstance(fw, dict):
        return None
    adv = fw.get("advanced") or {}
    sv = adv.get("sigma_vector")
    return sv if isinstance(sv, dict) else None


def build_trade_decision(date_str: str | None = None) -> dict[str, Any]:
    """Build complete trade decision (stance × size)."""
    if not date_str:
        date_str = utc_now().strftime("%Y-%m-%d")

    judgment = load_json(JUDGMENT_PATH)
    promotion_gate = load_json(PROMOTION_GATE_PATH)
    # K/X are research-only candidates and cannot size the operational path.
    k_gate = None
    x_gate = None
    hmm_audit = load_json(HMM_AUDIT_PATH)
    caselab = load_json(CASELAB_DIR / f"{date_str}.json")
    velocity_gate = _resolve_velocity_gate_state()
    sigma_vector = _load_sigma_vector()
    if isinstance(sigma_vector, dict) and velocity_gate.get("velocity_20d"):
        sigma_vector = {**sigma_vector, "velocity_20d": velocity_gate["velocity_20d"]}
        if velocity_gate.get("n_deteriorating") is not None:
            sigma_vector = {
                **sigma_vector,
                "n_deteriorating": velocity_gate["n_deteriorating"],
            }

    vg_state = velocity_gate.get("state", "UNKNOWN")

    if not judgment:
        learning_trace = build_trade_learning_trace(
            date=date_str,
            quality_inputs={},
            velocity_gate=velocity_gate,
            sigma_vector=sigma_vector,
            stance="WATCH",
            size=0.0,
            effective_size=0.0,
            run_id=os.environ.get("ZCODE_BUNDLE_RUN_ID"),
        )
        return {
            "schema_version": "trade_decision.v3",
            "generated_at": utc_now().isoformat(),
            "date": date_str,
            "decision": "WATCH",
            "stance": "WATCH",
            "size": 0.0,
            "effective_size": 0.0,
            "velocity_gate_state": vg_state,
            "velocity_gate": velocity_gate,
            "confidence": "low",
            "allowed_size": "zero",
            "time_horizon": "1d",
            "asset_scope": [],
            "invalidation": [],
            "risk_notes": ["Missing judgment — data unavailable"],
            "evidence_grade": "D",
            "paper_sources": {"approved_support": [], "background_context": []},
            "system_sources": [],
            "trade_thesis": {"hypothesis": "Insufficient data"},
            "learning_trace": learning_trace,
        }

    approved_sources, background_sources = find_paper_sources(caselab, judgment)
    # Live freshness wins over judgment-card cache — otherwise a recovered
    # paper_sync cannot undo permanent size step-down (constitution: stale→step-down,
    # but only while actually stale).
    freshness = check_paper_world_model_freshness()
    risk_notes: list[str] = []
    if freshness.get("stale"):
        risk_notes.append(
            f"Paper world model stale ({freshness.get('reason')}, "
            f"age={freshness.get('age_hours')}h) — size stepped down"
        )

    quality = build_quality_inputs(
        promotion_gate=promotion_gate or {},
        k_gate=k_gate,
        x_gate=x_gate,
        hmm_audit=hmm_audit,
        caselab=caselab,
        approved_sources=approved_sources,
        paper_freshness=freshness,
    )
    if quality.get("promotion_hard_blocked"):
        blocked = (promotion_gate or {}).get("blocked_gates") or []
        risk_notes.append(f"Promotion gate hard-blocked: {', '.join(map(str, blocked))}")
    if not quality.get("has_approved_paper"):
        risk_notes.append("No approved Paper sources — size discounted")
    if quality.get("hmm_grade") in ("WEAK", "UNKNOWN"):
        risk_notes.append(f"HMM grade {quality.get('hmm_grade')} — size discounted")

    stance = determine_stance(sigma_vector, velocity_gate)
    size = determine_size(quality)
    composed = compose_trade_fields(
        stance=stance,
        size=size,
        data_available=True,
        risk_notes=risk_notes,
    )
    decision = composed["decision"]
    confidence = confidence_for_size(composed["size"], decision)
    evidence_grade = evidence_grade_for_size(composed["size"], decision)

    system_sources = _build_system_sources(judgment, k_gate, x_gate, hmm_audit, caselab)
    trade_thesis = _build_trade_thesis(decision, judgment, approved_sources, system_sources)
    # Prefer workbench thesis wording for stance labels
    wb_thesis = _wb_build_trade_thesis(decision, judgment, approved_sources, system_sources)
    trade_thesis["hypothesis"] = wb_thesis.get("hypothesis", trade_thesis.get("hypothesis"))

    time_horizon = "1w" if decision in ("RISK_ON", "RISK_REDUCE", "RISK_OFF") else "1d"
    asset_scope = ["SPY", "HYG", "TLT"]
    if decision == "RISK_ON" and composed["effective_size"] >= 0.5:
        asset_scope.extend(["VIX", "KRE", "XLF"])

    invalidation = [
        "Data freshness > 48h",
        "Velocity gate EXIT",
        "Promotion gate hard-blocks",
        "Neutral pressure input becomes stale or unavailable",
    ]
    trigger_conditions = [
        "Velocity gate FULL with <3 deteriorating channels",
        "Neutral pressure gauges remain admitted and fresh",
        "CaseLab match quality improves to usable/strong",
        "Paper sources approved and fresh",
        "HMM stability improves to ADEQUATE/HIGH",
    ]
    learning_hooks = [
        f"Track stance={decision} size={composed['size']} over 1d/1w/1m horizons",
        "Compare with SPY/HYG/TLT forward returns",
        "Record if invalidation conditions triggered",
        "Feed into Learning Hub calibration",
    ]
    learning_trace = build_trade_learning_trace(
        date=date_str,
        quality_inputs=quality,
        velocity_gate=velocity_gate,
        sigma_vector=sigma_vector,
        stance=composed["stance"],
        size=composed["size"],
        effective_size=composed["effective_size"],
        run_id=os.environ.get("ZCODE_BUNDLE_RUN_ID"),
    )

    return {
        "schema_version": "trade_decision.v3",
        "generated_at": utc_now().isoformat(),
        "date": date_str,
        "decision": decision,
        "stance": composed["stance"],
        "size": composed["size"],
        "effective_size": composed["effective_size"],
        "velocity_gate_state": vg_state,
        "velocity_gate": velocity_gate,
        "confidence": confidence,
        "allowed_size": composed["allowed_size"],
        "time_horizon": time_horizon,
        "asset_scope": asset_scope,
        "invalidation": invalidation,
        "trigger_conditions": trigger_conditions,
        "risk_notes": composed["risk_notes"],
        "evidence_grade": evidence_grade,
        "learning_hooks": learning_hooks,
        "learning_trace": learning_trace,
        "paper_sources": {
            "approved_support": approved_sources,
            "background_context": background_sources,
        },
        "system_sources": system_sources,
        "trade_thesis": trade_thesis,
    }


def _format_markdown(d: dict[str, Any]) -> str:
    """Format trade decision as markdown."""
    lines = [
        f"# Trade Decision — {d.get('date', 'unknown')}",
        "",
        f"- **Decision:** {d['decision']}",
        f"- **Stance:** {d.get('stance', d['decision'])}",
        f"- **Size:** {d.get('size', 'N/A')}",
        f"- **Effective Size:** {d.get('effective_size', 'N/A')}",
        f"- **Velocity Gate:** {d.get('velocity_gate_state', 'N/A')}",
        f"- **Confidence:** {d['confidence']}",
        f"- **Evidence Grade:** {d['evidence_grade']}",
        f"- **Allowed Size:** {d.get('allowed_size', 'N/A')}",
        f"- **Time Horizon:** {d.get('time_horizon', 'N/A')}",
        "",
    ]
    thesis = d.get("trade_thesis", {})
    if thesis.get("hypothesis"):
        lines += ["## Thesis", "", thesis["hypothesis"], ""]
    risk = d.get("risk_notes", [])
    if risk:
        lines += ["## Risk Notes", ""]
        for r in risk:
            lines.append(f"- {r}")
        lines.append("")
    sources = d.get("system_sources", [])
    if sources:
        lines += ["## System Sources", ""]
        for s in sources:
            lines.append(f"- {s.get('source', '?')}: {s.get('status', '?')}")
    return "\n".join(lines) + "\n"


def write_outputs(decision: dict[str, Any]) -> dict[str, Path]:
    """Write trade decision outputs."""
    ensure_dir(OUTPUT_DIR)

    json_path = OUTPUT_DIR / "latest.json"
    md_path = OUTPUT_DIR / "latest.md"

    write_json(json_path, decision)
    md_path.write_text(_format_markdown(decision), encoding="utf-8")

    return {"json": json_path, "markdown": md_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate trade decision.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    parser.add_argument("--date", default=None, help="Override date.")
    args = parser.parse_args()

    decision = build_trade_decision(args.date)
    paths = write_outputs(decision)
    write_pending_evaluation("trade_decision_layer", decision)

    if args.json:
        print(json.dumps(decision, indent=2, ensure_ascii=False))
    else:
        print(f"Trade decision: {paths['markdown']}")
        print(f"Decision: {decision['decision']}")
        print(f"Stance: {decision.get('stance')}")
        print(f"Size: {decision.get('size')}")
        print(f"Velocity Gate: {decision.get('velocity_gate_state')}")
        print(f"Confidence: {decision['confidence']}")
        print(f"Evidence Grade: {decision['evidence_grade']}")
        paper = decision.get("paper_sources") or {}
        n_paper = (
            len(paper.get("approved_support", [])) + len(paper.get("background_context", []))
            if isinstance(paper, dict)
            else len(paper)
        )
        print(f"Paper Sources: {n_paper}")
        print(f"System Sources: {len(decision['system_sources'])}")


if __name__ == "__main__":
    main()
