"""Trade decision logic — pure computation, no I/O.

Phase 4: stance (signal) × size (quality).
WATCH only when key inputs are unavailable.
"""
from __future__ import annotations

from typing import Any

SIZE_LADDER: tuple[float, ...] = (0.0, 0.25, 0.5, 1.0)
STANCE_WEIGHT: dict[str, float] = {
    "RISK_ON": 1.0,
    "RISK_REDUCE": 0.5,
    "RISK_OFF": 0.0,
}
DEFAULT_COFIRE_V = 0.2
DEFAULT_COFIRE_N = 3


def snap_size(raw: float) -> float:
    """Snap a continuous size to the discrete ladder."""
    if raw <= 0:
        return 0.0
    best = 0.0
    best_dist = abs(raw - 0.0)
    for level in SIZE_LADDER:
        dist = abs(raw - level)
        if dist < best_dist or (dist == best_dist and level > best):
            best = level
            best_dist = dist
    return best


def step_down_size(size: float) -> float:
    """Drop one rung on the size ladder (Paper stale path)."""
    snapped = snap_size(size)
    if snapped in SIZE_LADDER:
        idx = SIZE_LADDER.index(snapped)
    else:
        idx = max(i for i, v in enumerate(SIZE_LADDER) if v <= snapped)
    return SIZE_LADDER[max(0, idx - 1)]


def size_to_allowed_label(size: float) -> str:
    if size <= 0:
        return "zero"
    if size <= 0.25:
        return "small"
    if size <= 0.5:
        return "medium"
    return "large"


def _count_deteriorating(
    velocity_20d: dict[str, Any] | None,
    cofire_v: float = DEFAULT_COFIRE_V,
) -> int | None:
    if not isinstance(velocity_20d, dict):
        return None
    count = 0
    found = False
    for ch in ("M", "D"):
        if ch not in velocity_20d:
            continue
        found = True
        try:
            if float(velocity_20d[ch]) > cofire_v:
                count += 1
        except (TypeError, ValueError):
            continue
    return count if found else None


def determine_stance(
    sigma_vector: dict[str, Any] | None,
    velocity_gate_state: dict[str, Any] | None,
) -> str:
    """Signal layer: neutral-gauge velocity → RISK_ON / RISK_REDUCE / RISK_OFF.

    EXIT → RISK_OFF; 3+ channels deteriorating without exit → RISK_REDUCE;
    otherwise RISK_ON. Without channel velocities, degrade to FULL→ON / EXIT→OFF
    (never invent RISK_REDUCE).
    """
    vg = velocity_gate_state or {}
    state = vg.get("state")
    position = vg.get("position")

    if state == "EXIT":
        return "RISK_OFF"
    if position is not None:
        try:
            if float(position) < 1.0:
                return "RISK_OFF"
        except (TypeError, ValueError):
            return "RISK_OFF"

    n_det = vg.get("n_deteriorating")
    if n_det is None and isinstance(sigma_vector, dict):
        n_det = sigma_vector.get("n_deteriorating")
    if n_det is None:
        vel = vg.get("velocity_20d")
        if vel is None and isinstance(sigma_vector, dict):
            vel = sigma_vector.get("velocity_20d")
        cofire_v = DEFAULT_COFIRE_V
        if isinstance(sigma_vector, dict) and sigma_vector.get("cofire_v") is not None:
            try:
                cofire_v = float(sigma_vector["cofire_v"])
            except (TypeError, ValueError):
                cofire_v = DEFAULT_COFIRE_V
        n_det = _count_deteriorating(vel if isinstance(vel, dict) else None, cofire_v)

    if n_det is not None and int(n_det) >= DEFAULT_COFIRE_N:
        return "RISK_REDUCE"

    return "RISK_ON"


def determine_size(quality_inputs: dict[str, Any] | None) -> float:
    """Quality layer: gates contribute discounts, not binary blocks.

    Returns a ladder size in {0, 0.25, 0.5, 1.0}.
    """
    q = quality_inputs or {}
    size = 1.0

    if (q.get("k_verdict") or "UNKNOWN") == "FAIL":
        size *= 0.5
    if (q.get("x_verdict") or "UNKNOWN") == "FAIL":
        size *= 0.5

    hmm = q.get("hmm_grade") or "UNKNOWN"
    if hmm in ("WEAK", "UNKNOWN"):
        size *= 0.5

    caselab = q.get("caselab_label") or "unknown"
    if caselab not in ("usable", "strong"):
        size *= 0.5

    if not q.get("has_approved_paper"):
        size *= 0.5

    proxy = q.get("proxy_quality")
    if proxy in ("poor", "rejected", "quarantined"):
        size *= 0.5

    size = snap_size(size)

    if q.get("paper_stale"):
        size = step_down_size(size)

    if q.get("promotion_hard_blocked"):
        size = 0.0

    return size


def compose_trade_fields(
    *,
    stance: str,
    size: float,
    data_available: bool,
    risk_notes: list[str] | None = None,
) -> dict[str, Any]:
    """Compose decision / exposure fields from stance × size."""
    notes = list(risk_notes or [])
    if not data_available:
        return {
            "decision": "WATCH",
            "stance": "WATCH",
            "size": 0.0,
            "effective_size": 0.0,
            "allowed_size": "zero",
            "risk_notes": notes,
        }

    weight = STANCE_WEIGHT.get(stance, 0.0)
    effective = snap_size(weight * float(size))
    return {
        "decision": stance,
        "stance": stance,
        "size": float(size),
        "effective_size": effective,
        "allowed_size": size_to_allowed_label(effective),
        "risk_notes": notes,
    }


def build_quality_inputs(
    *,
    promotion_gate: dict[str, Any] | None,
    k_gate: dict[str, Any] | None,
    x_gate: dict[str, Any] | None,
    hmm_audit: dict[str, Any] | None,
    caselab: dict[str, Any] | None,
    approved_sources: list[dict[str, Any]] | None,
    paper_freshness: dict[str, Any] | None = None,
    proxy_quality: str | None = None,
) -> dict[str, Any]:
    """Normalize quality inputs for determine_size."""
    pg = promotion_gate or {}
    pg_status = pg.get("overall_status", "UNKNOWN")
    blocked = pg.get("blocked_gates") or pg.get("blocking_reasons") or []
    soft_block = pg_status == "BLOCKED" and set(blocked) <= {"calibration_samples"}
    hard_blocked = pg_status == "BLOCKED" and not soft_block

    k_verdict = (k_gate or {}).get("gate_verdict", (k_gate or {}).get("verdict", "UNKNOWN"))
    x_verdict = (x_gate or {}).get("gate_verdict", (x_gate or {}).get("verdict", "UNKNOWN"))
    hmm_grade = (hmm_audit or {}).get("stability_grade", "UNKNOWN")
    caselab_label = ((caselab or {}).get("match_quality") or {}).get("label") or (
        (caselab or {}).get("label") or "unknown"
    )
    freshness = paper_freshness or {}

    return {
        "k_verdict": k_verdict,
        "x_verdict": x_verdict,
        "hmm_grade": hmm_grade,
        "caselab_label": caselab_label,
        "has_approved_paper": bool(approved_sources),
        "paper_stale": bool(freshness.get("stale")),
        "promotion_hard_blocked": hard_blocked,
        "promotion_soft_blocked": soft_block,
        "proxy_quality": proxy_quality,
    }


def evidence_grade_for_size(size: float, stance: str) -> str:
    if stance == "WATCH" or size <= 0:
        return "D"
    if size >= 1.0:
        return "A"
    if size >= 0.5:
        return "B"
    return "C"


def confidence_for_size(size: float, stance: str) -> str:
    if stance == "WATCH" or size <= 0:
        return "low"
    if size >= 1.0:
        return "high"
    if size >= 0.5:
        return "medium"
    return "low"


def determine_decision(
    judgment: dict[str, Any],
    promotion_gate: dict[str, Any],
    k_gate: dict[str, Any] | None,
    x_gate: dict[str, Any] | None,
    hmm_audit: dict[str, Any] | None,
    caselab: dict[str, Any] | None,
    paper_sources: list[dict[str, Any]] | None = None,
    *,
    sigma_vector: dict[str, Any] | None = None,
    velocity_gate_state: dict[str, Any] | None = None,
    paper_freshness: dict[str, Any] | None = None,
    proxy_quality: str | None = None,
) -> tuple[str, str, str, list[str]]:
    """Compatibility wrapper: returns (decision, confidence, evidence_grade, risk_notes)."""
    risk_notes: list[str] = []
    if not judgment:
        risk_notes.append("Missing judgment — data unavailable")
        return "WATCH", "low", "D", risk_notes

    approved = [s for s in (paper_sources or []) if s.get("review_status") == "approved"]
    quality = build_quality_inputs(
        promotion_gate=promotion_gate,
        k_gate=k_gate,
        x_gate=x_gate,
        hmm_audit=hmm_audit,
        caselab=caselab,
        approved_sources=approved,
        paper_freshness=paper_freshness or judgment.get("paper_world_model_freshness"),
        proxy_quality=proxy_quality,
    )
    if quality["promotion_hard_blocked"]:
        risk_notes.append(
            f"Promotion gate hard-blocked: {promotion_gate.get('blocked_gates') or promotion_gate.get('blocking_reasons')}"
        )
    if quality["paper_stale"]:
        risk_notes.append("Paper world model stale — size stepped down one rung")
    if not quality["has_approved_paper"]:
        risk_notes.append("No approved Paper sources — size discounted")

    stance = determine_stance(sigma_vector, velocity_gate_state)
    size = determine_size(quality)
    composed = compose_trade_fields(
        stance=stance,
        size=size,
        data_available=True,
        risk_notes=risk_notes,
    )
    decision = composed["decision"]
    conf = confidence_for_size(composed["size"], decision)
    grade = evidence_grade_for_size(composed["size"], decision)
    return decision, conf, grade, composed["risk_notes"]


def build_system_sources(
    judgment: dict[str, Any],
    k_gate: dict[str, Any] | None,
    x_gate: dict[str, Any] | None,
    hmm_audit: dict[str, Any] | None,
    caselab: dict[str, Any] | None,
    path_map: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Build list of system sources."""
    paths = path_map or {}
    sources = []

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

    if k_gate:
        sources.append({
            "source_type": "k_gate",
            "source_path": paths.get("k_gate", "Output/measurement/latest_k_gate.json"),
            "status": k_gate.get("gate_verdict", "UNKNOWN"),
            "value": {"verdict": k_gate.get("gate_verdict")},
        })

    if x_gate:
        sources.append({
            "source_type": "x_gate",
            "source_path": paths.get("x_gate", "Output/measurement/latest_x_gate.json"),
            "status": x_gate.get("gate_verdict", "UNKNOWN"),
            "value": {"verdict": x_gate.get("gate_verdict")},
        })

    if hmm_audit:
        sources.append({
            "source_type": "hmm_audit",
            "source_path": paths.get("hmm_audit", "Output/system_learning/latest/hmm_stability_audit.json"),
            "status": hmm_audit.get("stability_grade", "UNKNOWN"),
            "value": {"grade": hmm_audit.get("stability_grade")},
        })

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
    if decision == "WATCH":
        hypothesis = "Data unavailable — monitor only; no stance assigned."
    elif decision == "RISK_OFF":
        hypothesis = "Velocity gate EXIT — flatten / stay flat (shadow position size 0)."
    elif decision == "RISK_REDUCE":
        hypothesis = "Multi-channel deterioration without EXIT — reduce shadow position."
    elif decision == "RISK_ON":
        hypothesis = "No velocity EXIT — risk-on stance; size set by quality discounts."
    elif decision == "NO_TRADE":
        hypothesis = "Legacy NO_TRADE mapped to flat exposure."
    else:
        hypothesis = "Decision pending further analysis."

    mechanism_support = []
    for source in paper_sources:
        if source.get("content_type") == "case":
            mechanism_support.append(f"Case: {source.get('content_id', 'unknown')}")

    observable_conditions = []
    for source in system_sources:
        if source.get("source_type") == "judgment":
            observable_conditions.append(f"Judgment: {source.get('status', 'unknown')}")
        elif source.get("source_type") == "k_gate":
            observable_conditions.append(f"K gate: {source.get('status', 'unknown')}")
        elif source.get("source_type") == "x_gate":
            observable_conditions.append(f"X gate: {source.get('status', 'unknown')}")

    what_would_upgrade = []
    if decision in ("WATCH", "RISK_OFF", "RISK_REDUCE"):
        what_would_upgrade.append("Velocity gate returns to FULL with <3 deteriorating channels")
        what_would_upgrade.append("K/X gates pass and HMM grade improves")
        what_would_upgrade.append("CaseLab match quality improves to usable/strong")

    return {
        "hypothesis": hypothesis,
        "mechanism_support": mechanism_support,
        "observable_conditions": observable_conditions,
        "what_would_upgrade": what_would_upgrade,
        "what_would_invalidate": [
            "Data freshness degrades",
            "Velocity gate EXIT",
            "Promotion gate hard-blocks",
        ],
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
        f"- **Stance:** {decision.get('stance', decision['decision'])}",
        f"- **Size:** {decision.get('size', 'N/A')}",
        f"- **Effective Size:** {decision.get('effective_size', 'N/A')}",
        f"- **Velocity Gate:** {decision.get('velocity_gate_state', 'N/A')}",
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
        if paper:
            for source in paper:
                lines.append(
                    f"- [{source.get('content_type', 'unknown')}] "
                    f"{source.get('content_id', 'unknown')} ({source.get('review_status', 'unknown')})"
                )
        else:
            lines.append("- None")

    lines += [
        "",
        "## System Sources",
        "",
    ]
    for source in decision['system_sources']:
        lines.append(f"- [{source.get('source_type', source.get('source', '?'))}] {source['status']}")

    lines += [
        "",
        "---",
        "",
        "*This is a research judgment, not a trading signal. "
        "Use for paper trading / shadow position calibration only.*",
    ]

    return "\n".join(lines) + "\n"
