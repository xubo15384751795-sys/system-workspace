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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
from pending_evaluation import write_pending_evaluation

JUDGMENT_PATH = ROOT / "Output" / "judgment" / "latest.json"
PROMOTION_GATE_PATH = ROOT / "Output" / "judgment" / "promotion_gate.json"
K_GATE_PATH = ROOT / "Output" / "k_measurement" / "k_measurement_gate.json"
X_GATE_PATH = ROOT / "Output" / "x_measurement" / "x_measurement_gate.json"
HMM_AUDIT_PATH = ROOT / "Output" / "hmm_stability" / "hmm_stability_audit.json"
CASELAB_DIR = ROOT / "Output" / "caselab"
PAPER_WORLD_MODEL_DIR = ROOT / "Data" / "paper_world_model"
OUTPUT_DIR = ROOT / "Output" / "trade_decision"


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    items = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def find_paper_sources(
    caselab: dict[str, Any] | None,
    judgment: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Find relevant Paper sources for the decision.

    Returns: (approved_sources, background_sources)
    - approved_sources: can be used as mechanism support
    - background_sources: can only be used as background context
    """
    approved_sources = []
    background_sources = []

    # Load paper world model
    cases = load_jsonl(PAPER_WORLD_MODEL_DIR / "cases.jsonl")
    mechanisms = load_jsonl(PAPER_WORLD_MODEL_DIR / "mechanisms.jsonl")

    # Get caselab matches
    if caselab:
        matches = caselab.get("matches", [])
        for match in matches[:3]:  # Top 3 matches
            case_name = match.get("case_name", "")
            # Find matching case in paper world model
            for case in cases:
                if case_name.lower() in case.get("case_id", "").lower():
                    source = {
                        "source_file": case.get("source_file", ""),
                        "content_type": "case",
                        "content_id": case.get("case_id", ""),
                        "relevance": "high" if match.get("score", 0) > 0.5 else "medium",
                        "review_status": case.get("review_status", "needs_review"),
                    }
                    if case.get("review_status") == "approved":
                        approved_sources.append(source)
                    else:
                        background_sources.append(source)
                    break

    # If no caselab matches, use top cases by trade_relevance
    if not approved_sources and not background_sources:
        high_relevance = [c for c in cases if c.get("trade_relevance") == "high"]
        for case in high_relevance[:2]:
            source = {
                "source_file": case.get("source_file", ""),
                "content_type": "case",
                "content_id": case.get("case_id", ""),
                "relevance": "medium",
                "review_status": case.get("review_status", "needs_review"),
            }
            if case.get("review_status") == "approved":
                approved_sources.append(source)
            else:
                background_sources.append(source)

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
        sources.append({"source": "k_gate", "type": "gate", "status": k_gate.get("verdict", "UNKNOWN")})
    if x_gate:
        sources.append({"source": "x_gate", "type": "gate", "status": x_gate.get("verdict", "UNKNOWN")})
    if hmm_audit:
        sources.append({"source": "hmm_stability", "type": "audit", "status": hmm_audit.get("stability_grade", "UNKNOWN")})
    if caselab:
        sources.append({"source": "caselab", "type": "analogy", "status": caselab.get("label", "UNKNOWN")})
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


def _determine_decision(
    judgment: dict, promotion_gate: dict, k_gate: dict | None,
    x_gate: dict | None, hmm_audit: dict | None, caselab: dict | None,
    approved_sources: list,
) -> tuple[str, str, str, list[str]]:
    """Determine trade decision from system state."""
    risk_notes: list[str] = []

    pg_status = promotion_gate.get("overall_status", "UNKNOWN")
    conf_level = (judgment.get("confidence", {}).get("level") if isinstance(judgment.get("confidence"), dict) else "unknown")
    claim_ceiling = judgment.get("claim_ceiling", "unknown")
    ladder = judgment.get("claim_ladder", {})
    ladder_tier = ladder.get("tier", 0) if ladder else 0

    # If promotion gate is blocked, no trade
    if pg_status == "BLOCKED":
        blocked = promotion_gate.get("blocked_gates", [])
        risk_notes.append(f"Promotion gate BLOCKED: {', '.join(blocked)}")
        # Include claim ladder context even when blocked
        if ladder_tier >= 1:
            risk_notes.append(
                f"Claim ladder: Tier {ladder_tier} ({ladder.get('label', '?')}) — "
                f"{ladder.get('claim_statement', '')[:100]}"
            )
        return "NO_TRADE", "low", "D", risk_notes

    # Low confidence → watch only
    if conf_level == "low":
        risk_notes.append("Confidence is low")
        if ladder_tier >= 1:
            risk_notes.append(
                f"Claim ladder: Tier {ladder_tier} ({ladder.get('label', '?')}) — "
                f"mechanism hypothesis available but not operationally actionable"
            )
        return "NO_TRADE", "low", "D", risk_notes

    # Check HMM stability
    if hmm_audit:
        hmm_grade = hmm_audit.get("stability_grade", "UNKNOWN")
        if hmm_grade == "WEAK":
            risk_notes.append("HMM stability WEAK")
            return "NO_TRADE", "low", "D", risk_notes

    # Check gates
    if k_gate and k_gate.get("verdict") == "FAIL":
        risk_notes.append("K gate FAIL")
    if x_gate and x_gate.get("verdict") == "FAIL":
        risk_notes.append("X gate FAIL")

    # If we have approved paper sources and gates pass, consider watch
    if approved_sources and conf_level in ("medium", "high"):
        evidence_grade = "B" if len(approved_sources) >= 2 else "C"
        return "WATCH", conf_level, evidence_grade, risk_notes

    # Default
    if risk_notes:
        return "NO_TRADE", "low", "D", risk_notes

    return "WATCH", conf_level or "low", "D", risk_notes


def build_trade_decision(date_str: str | None = None) -> dict[str, Any]:
    """Build complete trade decision."""
    if not date_str:
        date_str = datetime.now(UTC).strftime("%Y-%m-%d")

    # Load all inputs
    judgment = load_json(JUDGMENT_PATH)
    promotion_gate = load_json(PROMOTION_GATE_PATH)
    k_gate = load_json(K_GATE_PATH)
    x_gate = load_json(X_GATE_PATH)
    hmm_audit = load_json(HMM_AUDIT_PATH)
    caselab = load_json(CASELAB_DIR / f"{date_str}.json")

    if not judgment or not promotion_gate:
        return {
            "schema_version": "trade_decision.v1",
            "generated_at": datetime.now(UTC).isoformat(),
            "date": date_str,
            "decision": "NO_TRADE",
            "confidence": "low",
            "allowed_size": "zero",
            "time_horizon": "1d",
            "asset_scope": [],
            "invalidation": [],
            "risk_notes": ["Missing judgment or promotion gate"],
            "evidence_grade": "D",
            "paper_sources": [],
            "system_sources": [],
            "trade_thesis": {"hypothesis": "Insufficient data"},
        }

    # Find paper sources first (needed for Paper quality gate)
    approved_sources, background_sources = find_paper_sources(caselab, judgment)

    # Determine decision (now includes Paper quality gate)
    decision, confidence, evidence_grade, risk_notes = _determine_decision(
        judgment, promotion_gate, k_gate, x_gate, hmm_audit, caselab, approved_sources
    )

    # Build system sources
    system_sources = _build_system_sources(judgment, k_gate, x_gate, hmm_audit, caselab)

    # Build trade thesis (only approved sources can be mechanism support)
    trade_thesis = _build_trade_thesis(decision, judgment, approved_sources, system_sources)

    # Combine all paper sources for output
    all_paper_sources = approved_sources + background_sources

    # Determine allowed size
    allowed_size = "zero"
    if decision in ("RISK_REDUCE", "HEDGE"):
        allowed_size = "small"
    elif decision in ("TACTICAL_LONG", "TACTICAL_SHORT"):
        allowed_size = "medium"

    # Determine time horizon
    time_horizon = "1d"
    if decision in ("WATCH", "RISK_REDUCE"):
        time_horizon = "1w"
    elif decision in ("HEDGE", "TACTICAL_LONG", "TACTICAL_SHORT"):
        time_horizon = "1w"

    # Asset scope
    asset_scope = ["SPY", "HYG", "TLT"]
    if decision in ("TACTICAL_LONG", "TACTICAL_SHORT"):
        asset_scope.extend(["VIX", "KRE", "XLF"])

    # Invalidation conditions
    invalidation = [
        "Data freshness > 48h",
        "Promotion gate status changes to BLOCKED",
        "K/X gate verdict changes to FAIL",
    ]

    # Trigger conditions (what would upgrade the decision)
    trigger_conditions = []
    if decision in ("NO_TRADE", "WATCH"):
        trigger_conditions = [
            "Confidence improves to medium/high",
            "K/X gates pass",
            "CaseLab match quality improves to usable/strong",
            "Paper sources approved",
            "HMM stability improves to ADEQUATE",
        ]
    elif decision in ("HEDGE", "RISK_REDUCE"):
        trigger_conditions = [
            "Confidence improves to high",
            "All gates pass",
            "CaseLab match quality improves to strong",
            "Forward calibration shows favorable asymmetry",
        ]

    # Learning hooks (how this decision will be calibrated)
    learning_hooks = [
        f"Track {decision} outcome over 1d/1w/1m horizons",
        "Compare with SPY/HYG/TLT forward returns",
        "Record if invalidation conditions triggered",
        "Feed into Learning Hub calibration",
    ]

    return {
        "schema_version": "trade_decision.v2",
        "generated_at": datetime.now(UTC).isoformat(),
        "date": date_str,
        "decision": decision,
        "confidence": confidence,
        "allowed_size": allowed_size,
        "time_horizon": time_horizon,
        "asset_scope": asset_scope,
        "invalidation": invalidation,
        "trigger_conditions": trigger_conditions,
        "risk_notes": risk_notes,
        "evidence_grade": evidence_grade,
        "learning_hooks": learning_hooks,
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
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = OUTPUT_DIR / "latest.json"
    md_path = OUTPUT_DIR / "latest.md"

    json_path.write_text(json.dumps(decision, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(_format_markdown(decision), encoding="utf-8")

    return {"json": json_path, "markdown": md_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate trade decision.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    parser.add_argument("--date", default=None, help="Override date.")
    args = parser.parse_args()

    decision = build_trade_decision(args.date)
    paths = write_outputs(decision)
    eval_path = write_pending_evaluation("trade_decision_layer", decision)

    if args.json:
        print(json.dumps(decision, indent=2, ensure_ascii=False))
    else:
        print(f"Trade decision: {paths['markdown']}")
        print(f"Decision: {decision['decision']}")
        print(f"Confidence: {decision['confidence']}")
        print(f"Evidence Grade: {decision['evidence_grade']}")
        print(f"Paper Sources: {len(decision['paper_sources'])}")
        print(f"System Sources: {len(decision['system_sources'])}")


if __name__ == "__main__":
    main()
