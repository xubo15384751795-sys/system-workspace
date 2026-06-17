"""Build work brief — answer 4 questions from existing artifacts.

1. What is the system's current reaction?
2. Why is it reacting this way?
3. What is the most important blocker?
4. What is the most useful next work?

Reads only existing output files. No governance YAML, no new registries.
"""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CURRENT = ROOT / "Output" / "current"
JUDGMENT = ROOT / "Output" / "judgment"
TRADE = ROOT / "Output" / "trade_decision"
ML_SIGNALS = ROOT / "Output" / "ml_signals"


def _load(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _current_reaction(status: dict, fw: dict, judgment: dict, trade: dict | None) -> dict[str, str]:
    return {
        "framework_status": fw.get("status", "UNKNOWN") if fw else "NO_ARTIFACT",
        "judgment_decision": judgment.get("decision", "UNKNOWN") if judgment else "NO_ARTIFACT",
        "confidence": (judgment.get("confidence", {}).get("level", "UNKNOWN") if judgment else "NO_ARTIFACT"),
        "trade_decision": (trade.get("decision", "NO_DATA") if trade else "NO_ARTIFACT"),
        "promotion_gate": status.get("promotion_gate", {}).get("status", "UNKNOWN") if status else "NO_ARTIFACT",
    }


def _why(status: dict, judgment: dict, quality: dict | None) -> list[str]:
    reasons = []
    # From judgment confidence reasons
    if judgment:
        for r in (judgment.get("confidence", {}).get("reasons", []))[:5]:
            reasons.append(r)
    # From promotion gate blocking reasons
    if status:
        for r in status.get("promotion_gate", {}).get("blocking_reasons", []):
            if r not in reasons:
                reasons.append(r)
    # From quality validation
    if quality and quality.get("status") == "FAIL":
        for issue in quality.get("issues", []):
            reasons.append(f"Quality: {issue.get('message', issue.get('rule', 'unknown'))}")
    return reasons


def _most_important_blocker(status: dict, judgment: dict) -> str:
    """Pick the single most important blocker."""
    pg = status.get("promotion_gate", {}) if status else {}
    blocked = pg.get("blocked_gates", [])
    reasons = pg.get("blocking_reasons", [])

    # Confidence is usually the root blocker
    if "confidence" in blocked:
        conf_reasons = (judgment or {}).get("confidence", {}).get("reasons", [])
        if conf_reasons:
            return conf_reasons[0]
        return "Confidence is low"

    if "hmm" in blocked:
        return "HMM stability is WEAK — regime labels unreliable"

    if "caselab" in blocked:
        return "CaseLab has no reliable analogy match"

    if "claim_ceiling" in blocked:
        return f"Claim ceiling is {(judgment or {}).get('claim_ceiling', 'unknown')}"

    if reasons:
        return reasons[0]

    return "No blockers identified"


def _next_work(judgment: dict, quality: dict | None) -> list[str]:
    """Determine the most useful next work items."""
    actions = []
    conf = (judgment or {}).get("confidence", {})
    reasons = conf.get("reasons", []) if isinstance(conf, dict) else []

    for r in reasons:
        r_lower = r.lower()
        if "hmm" in r_lower and "stability" in r_lower:
            actions.append("Improve HMM stability: longer training window or rolling refit")
        if "proxy" in r_lower or "measurement" in r_lower:
            actions.append("Improve measurement quality: validate proxy inputs")
        if "quality validation" in r_lower:
            actions.append("Fix quality validation errors before re-running")
        if "diverge" in r_lower:
            actions.append("Investigate HMM vs M/D/K/X divergence")

    if quality and quality.get("status") == "FAIL":
        actions.append("Address quality validation failures")

    # Deduplicate, keep order
    seen = set()
    unique = []
    for a in actions:
        if a not in seen:
            seen.add(a)
            unique.append(a)

    if not unique:
        unique.append("Re-run after refreshing artifacts")

    return unique[:4]


def _sigma_snapshot(fw: dict | None) -> dict[str, Any] | None:
    if not fw:
        return None
    adv = fw.get("advanced", {})
    sigma = adv.get("sigma_vector", {})
    if not sigma:
        return None
    return {
        "M": sigma.get("M"),
        "D": sigma.get("D"),
        "K": sigma.get("K"),
        "X_agg": sigma.get("X_agg"),
        "channels_live": sigma.get("channels_live", []),
        "dominant_channel": sigma.get("dominant_channel"),
        "cofire_count": sigma.get("cofire_count"),
    }


def _hmm_signal() -> dict[str, Any] | None:
    """Read latest HMM signal and extract degeneracy-relevant summary."""
    hmm_path = ML_SIGNALS / "latest" / "regime_hmm.json"
    hmm = _load(hmm_path)
    if not hmm:
        return None

    regime = hmm.get("regime", {})
    stability = hmm.get("stability", {})
    degeneracy = hmm.get("degeneracy", {})

    return {
        "regime": regime.get("current", "unknown"),
        "probability": regime.get("probability"),
        "state_probs": regime.get("state_probs", {}),
        "usable_for_core_judgment": degeneracy.get("usable_for_core_judgment", False),
        "warnings": degeneracy.get("warnings", []),
        "flags": degeneracy.get("flags", []),
        "feature_count": stability.get("feature_count", 0),
        "sample_days": stability.get("sample_days", 0),
        "posterior_entropy": stability.get("posterior_entropy", 0),
    }


def build_work_brief() -> dict[str, Any]:
    status = _load(CURRENT / "status.json")
    fw = _load(CURRENT / "framework_output.json")
    judgment = _load(JUDGMENT / "latest.json")
    trade = _load(TRADE / "latest.json")
    quality = _load(CURRENT / "quality_validation.json")
    hmm = _hmm_signal()

    reaction = _current_reaction(status, fw, judgment, trade)
    reasons = _why(status, judgment, quality)
    blocker = _most_important_blocker(status, judgment)
    next_work = _next_work(judgment, quality)
    sigma = _sigma_snapshot(fw)

    result: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "reaction": reaction,
        "why": reasons,
        "most_important_blocker": blocker,
        "next_work": next_work,
        "sigma": sigma,
    }
    if hmm:
        result["hmm_signal"] = hmm

    # Claim ladder from judgment card
    if judgment:
        ladder = judgment.get("claim_ladder")
        if ladder:
            result["claim_ladder"] = ladder

    return result


def to_markdown(b: dict) -> str:
    r = b["reaction"]
    lines = [
        f"# Work Brief — {b['generated_at'][:10]}",
        "",
        "## System Reaction",
        "",
        f"- Status: **{r['framework_status']}**",
        f"- Judgment: **{r['judgment_decision']}**",
        f"- Confidence: **{r['confidence']}**",
        f"- Trade: **{r['trade_decision']}**",
        f"- Promotion gate: **{r['promotion_gate']}**",
        "",
        "## Why",
        "",
    ]
    for reason in b["why"]:
        lines.append(f"- {reason}")
    lines += [
        "",
        "## Most Important Blocker",
        "",
        f"**{b['most_important_blocker']}**",
        "",
        "## Next Useful Work",
        "",
    ]
    for i, action in enumerate(b["next_work"], 1):
        lines.append(f"{i}. {action}")

    hmm = b.get("hmm_signal")
    if hmm:
        usable = hmm.get("usable_for_core_judgment", False)
        icon = "✅" if usable else "🚫"
        lines += [
            "",
            "## HMM Regime Signal",
            "",
            f"- Regime: **{hmm.get('regime', 'unknown')}** (prob={hmm.get('probability', '?')})",
            f"- {icon} Usable for core judgment: **{usable}**",
            f"- Features: {hmm.get('feature_count', '?')}, Sample days: {hmm.get('sample_days', '?')}",
            f"- Posterior entropy: {hmm.get('posterior_entropy', '?')}",
        ]
        warnings = hmm.get("warnings", [])
        if warnings:
            lines.append("- Warnings:")
            for w in warnings:
                lines.append(f"  - {w}")
        state_probs = hmm.get("state_probs", {})
        if state_probs:
            probs_str = ", ".join(f"{k}={v:.3f}" for k, v in state_probs.items() if isinstance(v, (int, float)))
            lines.append(f"- State probs: {probs_str}")

    # Claim ladder
    ladder = b.get("claim_ladder")
    if ladder:
        tier = ladder.get("tier", 0)
        label = ladder.get("label", "diagnostic_claim")
        lines += [
            "",
            "## Claim Ladder",
            "",
            f"- **Tier {tier}: {label}**",
            f"- Claim: {ladder.get('claim_statement', 'N/A')}",
        ]
        if ladder.get("promotion_conditions"):
            lines.append("- Next step:")
            for tier_key, cond in ladder["promotion_conditions"].items():
                lines.append(f"  - {tier_key}: {cond}")
        if ladder.get("demotion_risk"):
            lines.append(f"- Demotion risk: {ladder['demotion_risk']}")

    sigma = b.get("sigma")
    if sigma:
        lines += [
            "",
            "## Sigma Snapshot",
            "",
        ]
        for ch in sigma.get("channels_live", []):
            val = sigma.get(ch)
            lines.append(f"- {ch}: {val}" if val is not None else f"- {ch}: null")
        lines.append(f"- dominant: {sigma.get('dominant_channel')}")
        lines.append(f"- cofire: {sigma.get('cofire_count')}")

    lines += ["", "---", f"*{b['generated_at']}*"]
    return "\n".join(lines) + "\n"


def main() -> None:
    json_mode = "--json" in sys.argv

    brief = build_work_brief()

    CURRENT.mkdir(parents=True, exist_ok=True)
    (CURRENT / "work_brief.json").write_text(
        json.dumps(brief, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    md = to_markdown(brief)
    (CURRENT / "work_brief.md").write_text(md, encoding="utf-8")

    if json_mode:
        print(json.dumps(brief, indent=2, ensure_ascii=False))
    else:
        print(md)


if __name__ == "__main__":
    main()
