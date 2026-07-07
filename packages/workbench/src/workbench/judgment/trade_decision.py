"""Trade decision logic — pure computation, no I/O.

Extracted from scripts/trade_decision_layer.py.
These functions take dicts and return results.
They do not read files, write files, or call external services.

Phase 1 of trade_decision_layer.py module split.
"""
from __future__ import annotations

from typing import Any


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


def build_system_sources(
    judgment: dict[str, Any],
    k_gate: dict[str, Any] | None,
    x_gate: dict[str, Any] | None,
    hmm_audit: dict[str, Any] | None,
    caselab: dict[str, Any] | None,
    path_map: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Build list of system sources.

    Args:
        path_map: Optional dict mapping source_type -> path string.
                  Falls back to relative paths if not provided.
    """
    paths = path_map or {}
    sources = []

    # Judgment
    sources.append({
        "source_type": "judgment",
        "source_path": paths.get("judgment", "Output/judgment/latest.json"),
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
            "source_path": paths.get("k_gate", "Output/measurement/latest_k_gate.json"),
            "status": k_gate.get("gate_verdict", "UNKNOWN"),
            "value": {"verdict": k_gate.get("gate_verdict")},
        })

    # X gate
    if x_gate:
        sources.append({
            "source_type": "x_gate",
            "source_path": paths.get("x_gate", "Output/measurement/latest_x_gate.json"),
            "status": x_gate.get("gate_verdict", "UNKNOWN"),
            "value": {"verdict": x_gate.get("gate_verdict")},
        })

    # HMM
    if hmm_audit:
        sources.append({
            "source_type": "hmm_audit",
            "source_path": paths.get("hmm_audit", "Output/system_learning/latest/hmm_stability_audit.json"),
            "status": hmm_audit.get("stability_grade", "UNKNOWN"),
            "value": {"grade": hmm_audit.get("stability_grade")},
        })

    # CaseLab
    if caselab:
        match_quality = caselab.get("match_quality", {})
        sources.append({
            "source_type": "caselab",
            "source_path": paths.get("caselab", "Output/caselab/latest_signal.json"),
            "status": match_quality.get("label", "unknown"),
            "value": {
                "label": match_quality.get("label"),
                "score": match_quality.get("score"),
                "top_case": (caselab.get("matches", [{}]) or [{}])[0].get("case_name"),
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
