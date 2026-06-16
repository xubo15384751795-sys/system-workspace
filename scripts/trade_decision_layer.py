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


def determine_decision(
    judgment: dict[str, Any],
    promotion_gate: dict[str, Any],
    k_gate: dict[str, Any] | None,
    x_gate: dict[str, Any] | None,
    hmm_audit: dict[str, Any] | None,
    caselab: dict[str, Any] | None,
    paper_sources: list[dict[str, Any]] | None = None,
) -> tuple[str, str, str, list[str]]:
    """Determine trade decision based on all inputs.

    Returns: (decision, confidence, evidence_grade, risk_notes)
    """
    risk_notes = []

    # Get judgment confidence
    conf_level = (judgment.get("confidence") or {}).get("level", "low")
    claim_ceiling = judgment.get("claim_ceiling", "diagnostic_watch_only")

    # Get gate statuses
    gate_status = promotion_gate.get("overall_status", "BLOCKED")
    k_verdict = (k_gate or {}).get("gate_verdict", "UNKNOWN")
    x_verdict = (x_gate or {}).get("gate_verdict", "UNKNOWN")
    hmm_grade = (hmm_audit or {}).get("stability_grade", "UNKNOWN")
    caselab_label = ((caselab or {}).get("match_quality") or {}).get("label", "unknown")

    # Check Paper source quality
    approved_sources = [s for s in (paper_sources or []) if s.get("review_status") == "approved"]
    has_approved_paper = len(approved_sources) > 0

    # Default to NO_TRADE
    decision = "NO_TRADE"
    confidence = "low"
    evidence_grade = "D"

    # Check if we can make any decision
    if gate_status == "BLOCKED":
        risk_notes.append(f"Promotion gate blocked: {promotion_gate.get('blocking_reasons', [])}")
        return "NO_TRADE", confidence, evidence_grade, risk_notes

    # Paper quality gate: no approved sources = max WATCH
    if not has_approved_paper:
        risk_notes.append("No approved Paper sources - max WATCH")
        return "WATCH", "low", "D", risk_notes

    # Determine decision based on confidence and gates
    if conf_level == "low":
        decision = "WATCH"
        confidence = "low"
        evidence_grade = "C"
        risk_notes.append("Low confidence - watch only")
    elif conf_level == "medium":
        # Check if gates allow active decisions
        if k_verdict == "PASS" and x_verdict == "PASS" and hmm_grade in ("ADEQUATE", "HIGH"):
            if caselab_label in ("usable", "strong"):
                decision = "HEDGE"
                confidence = "medium"
                evidence_grade = "B"
            else:
                decision = "WATCH"
                confidence = "medium"
                evidence_grade = "C"
                risk_notes.append("CaseLab not usable - watch only")
        else:
            decision = "WATCH"
            confidence = "medium"
            evidence_grade = "C"
            risk_notes.append(f"K={k_verdict}, X={x_verdict}, HMM={hmm_grade}")
    elif conf_level == "high":
        # High confidence requires all gates to pass
        if k_verdict == "PASS" and x_verdict == "PASS" and hmm_grade == "HIGH":
            if caselab_label == "strong":
                decision = "TACTICAL_LONG"
                confidence = "high"
                evidence_grade = "A"
            else:
                decision = "HEDGE"
                confidence = "high"
                evidence_grade = "B"
                risk_notes.append("CaseLab not strong - hedge only")
        else:
            decision = "RISK_REDUCE"
            confidence = "medium"
            evidence_grade = "B"
            risk_notes.append("Gates not fully passing - risk reduce only")

    return decision, confidence, evidence_grade, risk_notes


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


def build_system_sources(
    judgment: dict[str, Any],
    k_gate: dict[str, Any] | None,
    x_gate: dict[str, Any] | None,
    hmm_audit: dict[str, Any] | None,
    caselab: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Build list of system sources."""
    sources = []

    # Judgment
    sources.append({
        "source_type": "judgment",
        "source_path": str(JUDGMENT_PATH),
        "status": judgment.get("decision", "UNKNOWN"),
        "value": {
            "decision": judgment.get("decision"),
            "confidence": (judgment.get("confidence") or {}).get("level"),
            "claim_ceiling": judgment.get("claim_ceiling"),
        },
    })

    # K gate
    if k_gate:
        sources.append({
            "source_type": "k_gate",
            "source_path": str(K_GATE_PATH),
            "status": k_gate.get("gate_verdict", "UNKNOWN"),
            "value": {"verdict": k_gate.get("gate_verdict")},
        })

    # X gate
    if x_gate:
        sources.append({
            "source_type": "x_gate",
            "source_path": str(X_GATE_PATH),
            "status": x_gate.get("gate_verdict", "UNKNOWN"),
            "value": {"verdict": x_gate.get("gate_verdict")},
        })

    # HMM
    if hmm_audit:
        sources.append({
            "source_type": "hmm",
            "source_path": str(HMM_AUDIT_PATH),
            "status": hmm_audit.get("stability_grade", "UNKNOWN"),
            "value": {
                "stability_grade": hmm_audit.get("stability_grade"),
                "sample_days": hmm_audit.get("sample_days"),
            },
        })

    # CaseLab
    if caselab:
        sources.append({
            "source_type": "caselab",
            "source_path": str(CASELAB_DIR / f"{datetime.now(UTC).strftime('%Y-%m-%d')}.json"),
            "status": ((caselab or {}).get("match_quality") or {}).get("label", "unknown"),
            "value": {
                "top_score": ((caselab or {}).get("match_quality") or {}).get("top_score"),
                "label": ((caselab or {}).get("match_quality") or {}).get("label"),
            },
        })

    return sources


def build_trade_thesis(
    decision: str,
    judgment: dict[str, Any],
    paper_sources: list[dict[str, Any]],
    system_sources: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build trade thesis from decision and sources."""
    # Get structural state
    primary = (judgment.get("meaning") or [""])[0] if judgment.get("meaning") else ""

    # Build hypothesis
    if decision == "NO_TRADE":
        hypothesis = "No trade opportunity identified based on current evidence."
    elif decision == "WATCH":
        hypothesis = "Monitor for setup - evidence insufficient for active position."
    elif decision == "RISK_REDUCE":
        hypothesis = "Consider reducing exposure - structural risks elevated."
    elif decision == "HEDGE":
        hypothesis = "Add hedging position - moderate risk of adverse move."
    elif decision in ("TACTICAL_LONG", "TACTICAL_SHORT"):
        hypothesis = f"Active position warranted - {decision.lower().replace('tactical_', '')} bias."
    else:
        hypothesis = "Decision pending further analysis."

    # Build mechanism support
    mechanism_support = []
    for source in paper_sources:
        if source.get("content_type") == "case":
            mechanism_support.append(f"Case: {source.get('content_id', 'unknown')}")

    # Build observable conditions
    observable_conditions = []
    for source in system_sources:
        if source.get("source_type") == "judgment":
            observable_conditions.append(f"Judgment: {source.get('status', 'unknown')}")
        elif source.get("source_type") == "k_gate":
            observable_conditions.append(f"K gate: {source.get('status', 'unknown')}")
        elif source.get("source_type") == "x_gate":
            observable_conditions.append(f"X gate: {source.get('status', 'unknown')}")

    # Build upgrade conditions
    what_would_upgrade = []
    if decision in ("NO_TRADE", "WATCH"):
        what_would_upgrade.append("Confidence improves to medium/high")
        what_would_upgrade.append("K/X gates pass")
        what_would_upgrade.append("CaseLab match quality improves")

    # Build invalidation conditions
    what_would_invalidate = [
        "Data freshness degrades",
        "Promotion gate blocks",
        "Paper mechanism match fails",
    ]

    return {
        "hypothesis": hypothesis,
        "mechanism_support": mechanism_support,
        "observable_conditions": observable_conditions,
        "what_would_upgrade": what_would_upgrade,
        "what_would_invalidate": what_would_invalidate,
    }


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
    decision, confidence, evidence_grade, risk_notes = determine_decision(
        judgment, promotion_gate, k_gate, x_gate, hmm_audit, caselab, approved_sources
    )

    # Build system sources
    system_sources = build_system_sources(judgment, k_gate, x_gate, hmm_audit, caselab)

    # Build trade thesis (only approved sources can be mechanism support)
    trade_thesis = build_trade_thesis(decision, judgment, approved_sources, system_sources)

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


def format_markdown(decision: dict[str, Any]) -> str:
    """Format trade decision as markdown."""
    lines = [
        f"# Trade Decision — {decision['date']}",
        "",
        f"**Generated:** {decision['generated_at']}",
        "",
        "---",
        "",
        "## Decision",
        "",
        f"- **Decision:** {decision['decision']}",
        f"- **Confidence:** {decision['confidence']}",
        f"- **Evidence Grade:** {decision['evidence_grade']}",
        f"- **Allowed Size:** {decision['allowed_size']}",
        f"- **Time Horizon:** {decision['time_horizon']}",
        f"- **Asset Scope:** {', '.join(decision['asset_scope'])}",
        "",
        "## Trade Thesis",
        "",
        f"**Hypothesis:** {decision['trade_thesis']['hypothesis']}",
        "",
    ]

    if decision['trade_thesis'].get('mechanism_support'):
        lines.append("**Mechanism Support:**")
        for m in decision['trade_thesis']['mechanism_support']:
            lines.append(f"- {m}")
        lines.append("")

    if decision['trade_thesis'].get('observable_conditions'):
        lines.append("**Observable Conditions:**")
        for c in decision['trade_thesis']['observable_conditions']:
            lines.append(f"- {c}")
        lines.append("")

    lines += [
        "## Invalidation",
        "",
    ]
    for inv in decision['invalidation']:
        lines.append(f"- {inv}")

    if decision.get('trigger_conditions'):
        lines += [
            "",
            "## Trigger Conditions (What Would Upgrade This)",
            "",
        ]
        for cond in decision['trigger_conditions']:
            lines.append(f"- {cond}")

    if decision['risk_notes']:
        lines += [
            "",
            "## Risk Notes",
            "",
        ]
        for note in decision['risk_notes']:
            lines.append(f"- {note}")

    if decision.get('learning_hooks'):
        lines += [
            "",
            "## Learning Hooks",
            "",
        ]
        for hook in decision['learning_hooks']:
            lines.append(f"- {hook}")

    lines += [
        "",
        "## Paper Sources",
        "",
    ]

    paper = decision.get('paper_sources', {})
    if isinstance(paper, dict):
        approved = paper.get('approved_support', [])
        background = paper.get('background_context', [])

        if approved:
            lines.append("### Approved Support")
            for source in approved:
                lines.append(f"- [{source['content_type']}] {source['content_id']}")
            lines.append("")

        if background:
            lines.append("### Background Context")
            for source in background:
                lines.append(f"- [{source['content_type']}] {source['content_id']} ({source['review_status']})")
            lines.append("")

        if not approved and not background:
            lines.append("- None")
    else:
        # Legacy format
        if paper:
            for source in paper:
                lines.append(f"- [{source.get('content_type', 'unknown')}] {source.get('content_id', 'unknown')} ({source.get('review_status', 'unknown')})")
        else:
            lines.append("- None")

    lines += [
        "",
        "## System Sources",
        "",
    ]
    for source in decision['system_sources']:
        lines.append(f"- [{source['source_type']}] {source['status']}")

    lines += [
        "",
        "---",
        "",
        "*This is a research judgment, not a trading signal. Use for paper trading and calibration only.*",
    ]

    return "\n".join(lines) + "\n"


def write_outputs(decision: dict[str, Any]) -> dict[str, Path]:
    """Write trade decision outputs."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = OUTPUT_DIR / "latest.json"
    md_path = OUTPUT_DIR / "latest.md"

    json_path.write_text(json.dumps(decision, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(format_markdown(decision), encoding="utf-8")

    return {"json": json_path, "markdown": md_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate trade decision.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    parser.add_argument("--date", default=None, help="Override date.")
    args = parser.parse_args()

    decision = build_trade_decision(args.date)
    paths = write_outputs(decision)

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
