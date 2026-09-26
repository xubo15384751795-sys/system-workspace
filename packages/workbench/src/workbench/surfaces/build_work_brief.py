"""Build work brief — answer key questions from existing artifacts.

1. What is the system's current reaction?
2. Why is it reacting this way?
3. What is the most important blocker?
4. What is the most useful next work?
5. What can be said? (allowed language)
6. What cannot be said? (forbidden language)
7. What is the mechanism hypothesis?
8. Does the system need a full refresh?

Reads only existing output files. No governance YAML, no new registries.
"""
from __future__ import annotations

import json
import logging
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from verity.runtime.runtime_io import ROOT, current_dir, ensure_dir, surface_dir

logger = logging.getLogger(__name__)

CURRENT = current_dir()  # Phase 1.1: honor CURRENT_OUTPUT_DIR candidate redirect
JUDGMENT = surface_dir("judgment")
TRADE = surface_dir("trade_decision")
ML_SIGNALS = ROOT / "Output" / "state" / "ml_signals"

_PATH_KEYS = (
    "current",
    "judgment",
    "trade",
    "ml_signals",
    "caselab",
    "harvester_catalog",
)


def _default_paths() -> dict[str, Path]:
    """Return legacy-compatible input/output path bindings."""
    return {
        "current": CURRENT,
        "judgment": JUDGMENT,
        "trade": TRADE,
        "ml_signals": ML_SIGNALS,
        "caselab": ROOT / "Output" / "state" / "caselab",
        "harvester_catalog": ROOT / "Data" / "harvester" / "exports" / "latest" / "catalog.json",
    }


def _resolve_paths(paths: Mapping[str, Path] | None = None) -> dict[str, Path]:
    """Resolve explicit generation paths without changing no-arg behavior."""
    resolved = _default_paths()
    if paths is None:
        return resolved
    unknown = sorted(set(paths) - set(_PATH_KEYS))
    if unknown:
        raise ValueError(f"unknown work-brief path keys: {', '.join(unknown)}")
    resolved.update({key: Path(value) for key, value in paths.items()})
    return resolved


def _load(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Failed to load %s", path, exc_info=True)
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

    return "No hard blockers"


def _limiters(status: dict, judgment: dict) -> list[str]:
    """Identify limiting factors that constrain the system but don't block it."""
    limiters = []
    pg = status.get("promotion_gate", {}) if status else {}

    # Watch reasons from promotion gate
    for r in pg.get("watch_reasons", []):
        if r not in limiters:
            limiters.append(r)

    # Confidence reasons that aren't already covered
    conf = (judgment or {}).get("confidence", {})
    reasons = conf.get("reasons", []) if isinstance(conf, dict) else []
    for r in reasons:
        r_lower = r.lower()
        if "proxy" in r_lower or "measurement" in r_lower or "caselab" in r_lower:
            if r not in limiters:
                limiters.append(r)

    return limiters[:5]


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


def _hmm_signal(ml_signals_dir: Path | None = None) -> dict[str, Any] | None:
    """Read latest HMM signal and extract degeneracy-relevant summary."""
    hmm_path = (ml_signals_dir or ML_SIGNALS) / "latest" / "regime_hmm.json"
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


def _can_say(judgment: dict | None) -> list[str]:
    """What the system can say right now — from claim ladder allowed language."""
    if not judgment:
        return ["No judgment artifact — cannot make claims"]
    ladder = judgment.get("claim_ladder", {})
    allowed = ladder.get("allowed_language", [])
    if not allowed:
        return ["No explicit allowed language defined"]
    # Add context-specific items
    items = [f"Can use: {', '.join(allowed)}"]
    claim = ladder.get("claim_statement", "")
    if claim:
        items.append(f"Current claim: {claim[:200]}")
    return items


def _cannot_say(judgment: dict | None) -> list[str]:
    """What the system cannot say — from claim ladder forbidden language."""
    if not judgment:
        return ["No judgment artifact — no restrictions defined"]
    ladder = judgment.get("claim_ladder", {})
    forbidden = ladder.get("forbidden_language", [])
    if not forbidden:
        return ["No explicit forbidden language defined"]
    items = [f"Cannot use: {', '.join(forbidden)}"]
    # Add ceiling-specific restrictions
    ceiling = judgment.get("claim_ceiling", "")
    if ceiling:
        items.append(f"Claim ceiling: {ceiling}")
    tier = ladder.get("tier", 0)
    if tier <= 1:
        items.append("Cannot make directional forecasts (tier ≤ 1)")
        items.append("Cannot recommend positions (tier ≤ 1)")
    return items


def _mechanism_hypothesis(judgment: dict | None, caselab: dict | None) -> dict[str, Any]:
    """Extract mechanism hypothesis from CaseLab and judgment."""
    result: dict[str, Any] = {
        "status": "no_data",
        "mechanisms": [],
        "confidence": "unknown",
        "match_quality": "unknown",
    }

    # From CaseLab
    if caselab:
        mc = caselab.get("mechanism_context", {})
        result["mechanisms"] = mc.get("mechanism_types", [])
        mq = caselab.get("match_quality", {})
        result["match_quality"] = mq.get("label", "unknown")
        result["top_score"] = mq.get("top_score", 0)
        result["gap_to_usable"] = mq.get("gap_to_usable", 0)
        # Top match info
        matches = caselab.get("matches", [])
        if matches:
            top = matches[0]
            result["top_case"] = top.get("case_name", "unknown")
            result["matched_mechanisms"] = top.get("matched_mechanisms", [])
            result["missing_mechanisms"] = top.get("missing_mechanisms", [])
        result["status"] = "available"

    # From judgment claim ladder
    if judgment:
        ladder = judgment.get("claim_ladder", {})
        claim = ladder.get("claim_statement", "")
        if "resembles" in claim:
            # Extract mechanism names from claim
            after = claim.split("resembles")[1].split(".")[0]
            mechs = [m.strip() for m in after.split(",") if "_" in m.strip()]
            if mechs and not result["mechanisms"]:
                result["mechanisms"] = mechs
        result["tier"] = ladder.get("tier", 0)
        result["label"] = ladder.get("label", "unknown")

    return result


def _needs_full_refresh(
    fw: dict | None,
    judgment: dict | None,
    *,
    current_dir_path: Path | None = None,
    judgment_dir: Path | None = None,
    harvester_catalog_path: Path | None = None,
) -> dict[str, Any]:
    """Check if a full refresh is needed based on artifact freshness."""
    result: dict[str, Any] = {
        "needed": False,
        "reasons": [],
        "recommendation": "quick_reaction_sufficient",
    }

    now = datetime.now(UTC).timestamp()

    # Check framework_output freshness
    current = current_dir_path or CURRENT
    judgment_root = judgment_dir or JUDGMENT
    fw_path = current / "framework_output.json"
    if fw_path.exists():
        age_hours = (now - fw_path.stat().st_mtime) / 3600
        if age_hours > 48:
            result["needed"] = True
            result["reasons"].append(f"framework_output is {age_hours:.0f}h old (>48h)")
        elif age_hours > 24:
            result["reasons"].append(f"framework_output is {age_hours:.0f}h old (consider refresh)")
    else:
        result["needed"] = True
        result["reasons"].append("No framework_output found")

    # Check judgment freshness
    judgment_path = judgment_root / "latest.json"
    if judgment_path.exists():
        age_hours = (now - judgment_path.stat().st_mtime) / 3600
        if age_hours > 48:
            result["needed"] = True
            result["reasons"].append(f"judgment is {age_hours:.0f}h old (>48h)")
    else:
        result["needed"] = True
        result["reasons"].append("No judgment artifact found")

    # Check Harvester freshness
    harvester_catalog = harvester_catalog_path or (
        ROOT / "Data" / "harvester" / "exports" / "latest" / "catalog.json"
    )
    if harvester_catalog.exists():
        age_hours = (now - harvester_catalog.stat().st_mtime) / 3600
        if age_hours > 72:
            result["needed"] = True
            result["reasons"].append(f"Harvester release is {age_hours:.0f}h old (>72h)")
    else:
        result["reasons"].append("No Harvester release found (may be OK for quick mode)")

    # Check data gaps freshness
    gaps_path = current / "data_gaps.json"
    if gaps_path.exists():
        age_hours = (now - gaps_path.stat().st_mtime) / 3600
        if age_hours > 24:
            result["reasons"].append(f"data_gaps is {age_hours:.0f}h old (stale)")

    if result["needed"]:
        result["recommendation"] = "run_full_refresh"
    elif result["reasons"]:
        result["recommendation"] = "standard_run_sufficient"
    else:
        result["recommendation"] = "quick_reaction_sufficient"

    return result


def _load_caselab(caselab_dir: Path | None = None) -> dict[str, Any] | None:
    """Load today's CaseLab signal if available."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    path = (caselab_dir or ROOT / "Output" / "state" / "caselab") / f"{today}.json"
    return _load(path)


def build_work_brief(paths: Mapping[str, Path] | None = None) -> dict[str, Any]:
    """Build the work brief against legacy or explicit generation paths."""
    resolved = _resolve_paths(paths)
    current = resolved["current"]
    judgment_dir = resolved["judgment"]
    trade_dir = resolved["trade"]
    status = _load(current / "status.json")
    fw = _load(current / "framework_output.json")
    judgment = _load(judgment_dir / "latest.json")
    trade = _load(trade_dir / "latest.json")
    quality = _load(current / "quality_validation.json")
    hmm = _hmm_signal(resolved["ml_signals"])
    caselab = _load_caselab(resolved["caselab"])

    reaction = _current_reaction(status, fw, judgment, trade)
    reasons = _why(status, judgment, quality)
    blocker = _most_important_blocker(status, judgment)
    limiters = _limiters(status, judgment)
    next_work = _next_work(judgment, quality)
    sigma = _sigma_snapshot(fw)
    can_say = _can_say(judgment)
    cannot_say = _cannot_say(judgment)
    mechanism_hypothesis = _mechanism_hypothesis(judgment, caselab)
    refresh_check = _needs_full_refresh(
        fw,
        judgment,
        current_dir_path=current,
        judgment_dir=judgment_dir,
        harvester_catalog_path=resolved["harvester_catalog"],
    )

    result: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "reaction": reaction,
        "why": reasons,
        "most_important_blocker": blocker,
        "limiters": limiters,
        "next_work": next_work,
        "can_say": can_say,
        "cannot_say": cannot_say,
        "mechanism_hypothesis": mechanism_hypothesis,
        "needs_full_refresh": refresh_check,
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
    ]

    limiters = b.get("limiters", [])
    if limiters:
        lines += [
            "## Limiters",
            "",
        ]
        for limiter in limiters:
            lines.append(f"- {limiter}")
        lines.append("")

    lines += [
        "## Next Useful Work",
        "",
    ]
    for i, action in enumerate(b["next_work"], 1):
        lines.append(f"{i}. {action}")

    # Can say / Cannot say
    can_say = b.get("can_say", [])
    if can_say:
        lines += ["", "## What Can Be Said", ""]
        for item in can_say:
            lines.append(f"- {item}")
        lines.append("")

    cannot_say = b.get("cannot_say", [])
    if cannot_say:
        lines += ["## What Cannot Be Said", ""]
        for item in cannot_say:
            lines.append(f"- {item}")
        lines.append("")

    # Mechanism hypothesis
    mh = b.get("mechanism_hypothesis", {})
    if mh.get("mechanisms"):
        lines += ["## Mechanism Hypothesis", ""]
        lines.append(f"- **Status:** {mh.get('status', 'unknown')}")
        lines.append(f"- **Mechanisms:** {', '.join(mh.get('mechanisms', []))}")
        if mh.get("match_quality"):
            lines.append(f"- **Match quality:** {mh.get('match_quality')} (score={mh.get('top_score', 0):.3f})")
        if mh.get("top_case"):
            lines.append(f"- **Top case:** {mh.get('top_case')}")
        if mh.get("matched_mechanisms"):
            lines.append(f"- **Matched:** {', '.join(mh.get('matched_mechanisms', []))}")
        if mh.get("missing_mechanisms"):
            lines.append(f"- **Missing:** {', '.join(mh.get('missing_mechanisms', []))}")
        if mh.get("tier") is not None:
            lines.append(f"- **Claim tier:** {mh.get('tier')} ({mh.get('label', '')})")
        lines.append("")

    # Needs full refresh
    refresh = b.get("needs_full_refresh", {})
    if refresh:
        needed = refresh.get("needed", False)
        icon = "🔴" if needed else "🟢"
        rec = refresh.get("recommendation", "unknown")
        lines += [
            "## Full Refresh Check",
            "",
            f"- {icon} **Needs full refresh:** {'YES' if needed else 'No'}",
            f"- **Recommendation:** {rec}",
        ]
        if refresh.get("reasons"):
            lines.append("- Reasons:")
            for reason in refresh["reasons"]:
                lines.append(f"  - {reason}")
        lines.append("")

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


def _check_closure_chain(paths: Mapping[str, Path] | None = None) -> None:
    """Warn if running standalone and upstream artifacts are newer."""
    resolved = _resolve_paths(paths)
    judgment_path = resolved["judgment"] / "latest.json"
    current_brief = resolved["current"] / "work_brief.json"

    if not judgment_path.exists():
        print("WARNING: No judgment card found. Run the full pipeline first.")
        return

    judgment_mtime = judgment_path.stat().st_mtime
    if current_brief.exists():
        brief_mtime = current_brief.stat().st_mtime
        if judgment_mtime > brief_mtime:
            print(
                "WARNING: Closure chain broken — judgment card is newer than work brief. "
                "This work brief may be stale. Re-run the full pipeline to close the chain."
            )


def write_work_brief(
    brief: dict[str, Any],
    *,
    output_dir: Path | None = None,
) -> tuple[Path, Path]:
    """Write JSON and Markdown to an explicit current-output surface."""
    target_dir = output_dir or CURRENT
    ensure_dir(target_dir)
    json_path = target_dir / "work_brief.json"
    json_path.write_text(
        json.dumps(brief, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    md_path = target_dir / "work_brief.md"
    md_path.write_text(to_markdown(brief), encoding="utf-8")
    return json_path, md_path


def main() -> None:
    json_mode = "--json" in sys.argv

    # Check closure chain when running standalone
    _check_closure_chain()

    brief = build_work_brief()

    _json_path, md_path = write_work_brief(brief)
    md = md_path.read_text(encoding="utf-8")

    if json_mode:
        print(json.dumps(brief, indent=2, ensure_ascii=False))
    else:
        print(md)


if __name__ == "__main__":
    main()
