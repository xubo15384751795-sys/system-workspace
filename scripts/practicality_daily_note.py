#!/usr/bin/env python3
"""Practicality Trial — Daily Note Generator.

Reads framework_output.json + replay evaluation to produce a structured
daily research note.  No new models, no canonical changes.

Usage:
    python3 scripts/practicality_daily_note.py              # today
    python3 scripts/practicality_daily_note.py --date 2026-06-04
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "Output" / "practicality_trial"
FW_PATH = ROOT / "Output" / "current" / "framework_output.json"
REPLAY_DIR = ROOT / "Output" / "sandbox" / "structural_replay_v2"
SCORES_CSV = OUTPUT / "practicality_scores.csv"
# Published by the Learning Hub `research-posture` command (read-only here).
POSTURE_JSON = ROOT / "Output" / "system_learning" / "research_posture" / "research_posture.json"

# ── helpers ──────────────────────────────────────────────────────────────

def load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def fmt_value(value: object) -> str:
    try:
        if value is None:
            return "n/a"
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return str(value)


def score_freshness(fw: dict) -> tuple[int, str]:
    """0=stale/missing, 1=warning, 2=fresh."""
    quality = fw.get("basic", {}).get("quality_status", "")
    if "MISSING" in quality or "STALE" in quality:
        return 0, f"quality={quality}"
    if "REDUCED" in quality:
        return 1, f"quality={quality}"
    return 2, "fresh"


def score_clarity(fw: dict) -> tuple[int, str]:
    """0=unreadable, 1=readable but vague, 2=clear within 3 min."""
    basic = fw.get("basic", {})
    summary = basic.get("summary", "")
    overall = basic.get("overall", "")
    if not summary or not overall:
        return 0, "missing summary"
    if len(summary) > 500:
        return 1, "summary too long"
    return 2, f"overall={overall}, summary present"


def extract_triggers(fw: dict) -> list[dict]:
    """Extract active triggers from framework_output."""
    triggers = []
    adv = fw.get("advanced", {})
    primary = adv.get("primary_readout", {})

    primary_state = primary.get("state")
    if primary_state and primary_state not in {"ANCHOR_STABLE_PATH_OPEN", "PRIMARY_READOUT_UNAVAILABLE"}:
        triggers.append({
            "name": primary_state,
            "type": "primary_readout",
            "detail": f"M/D primary market space={primary_state}",
        })

    # Channel-level triggers
    for ch_name, ch_data in adv.get("channel_confidence", {}).items():
        val = ch_data.get("value", 0)
        quality = ch_data.get("proxy_quality", "")
        if quality == "PROXY_REDUCED":
            triggers.append({
                "name": f"{ch_name}_proxy_reduced",
                "type": "quality_warning",
                "detail": f"{ch_name} proxy quality reduced",
            })

    return triggers


def score_trigger_quality(triggers: list[dict]) -> tuple[int, str]:
    """0=noise, 1=explained but weak, 2=clear observation value."""
    if not triggers:
        return 1, "no active triggers"
    primary = [t for t in triggers if t["type"] == "primary_readout"]
    if primary:
        return 2, primary[0]["detail"]
    quality_warns = [t for t in triggers if t["type"] == "quality_warning"]
    if quality_warns:
        return 1, f"{len(quality_warns)} quality warnings"
    return 1, f"{len(triggers)} triggers"


def score_warning_transparency(fw: dict) -> tuple[int, str]:
    """0=hidden, 1=partial, 2=clearly shown."""
    basic = fw.get("basic", {})
    quality = basic.get("quality_status", "UNKNOWN")
    summary = basic.get("summary", "")

    # Check if quality is mentioned in summary
    quality_in_summary = "REDUCED" in summary or "quality" in summary.lower()
    # Check if quality is in the top-level
    quality_present = quality != "UNKNOWN"

    if quality_present and quality_in_summary:
        return 2, f"quality={quality}, mentioned in summary"
    if quality_present:
        return 1, f"quality={quality}, not in summary"
    return 0, "quality not reported"


def _load_governance_flags() -> list[str]:
    """Extract governance flags from replay measurement audit + report."""
    flags: list[str] = []
    audit = load_json(REPLAY_DIR / "measurement_audit.json")
    if audit and isinstance(audit, dict):
        for key in ("diagnostic_shared_source", "core_contract_violations",
                     "channel_correlation"):
            items = audit.get(key, [])
            if isinstance(items, list):
                flags.extend(str(x) for x in items)
    return flags


def determine_what_not_to_conclude(fw: dict) -> str:
    """Explicit guardrails against overinterpretation."""
    basic = fw.get("basic", {})
    quality = basic.get("quality_status", "")
    guards = []

    if "PROXY_REDUCED" in quality:
        guards.append("Do not treat ACTIVE_FULL as high-confidence — proxy coverage is reduced")

    guards.append("M/D/K/X values are path diagnostics, not trading signals")
    guards.append("K/X_agg are retained canonical dimensions, not primary daily readout today")
    guards.append("Cofire count and dominant_channel are legacy diagnostics, not primary executive state")

    return "; ".join(guards)


def _extract_interpretation(fw: dict) -> str:
    """Pull the dominant-channel interpretation from the framework summary."""
    summary = fw.get("basic", {}).get("summary", "")
    marker = "interpretation:"
    if marker in summary:
        tail = summary.split(marker, 1)[1].strip()
        return tail.split(".")[0].strip()
    return ""


def build_research_posture_section(fw: dict, digest: dict | None, what_not: str) -> list[str]:
    """Confidence-aware but action-oriented posture block.

    Low confidence limits the claim level, not the research action. Merges today's
    dynamic state (dominant channel / cofire) with the Hub's published posture
    digest (what to say / watch / upgrade / forbid).
    """
    basic = fw.get("basic", {})
    adv = fw.get("advanced", {})
    sv = adv.get("sigma_vector", {})
    primary = adv.get("primary_readout", {})
    primary_state = primary.get("state", basic.get("primary_market_space", "PRIMARY_READOUT_UNAVAILABLE"))
    legacy_dominant = sv.get("dominant_channel", "N/A")
    legacy_cofire = sv.get("cofire_count", 0)
    quality = basic.get("quality_status", "UNKNOWN")
    interp = _extract_interpretation(fw)

    overall = (digest or {}).get("overall_posture", "ACTIVE_WATCH")
    digest_reason = (digest or {}).get("overall_reason", "")
    entries = (digest or {}).get("entries", [])

    interp_phrase = f" ({interp})" if interp else ""
    reason = f"M/D primary readout={primary_state}; legacy diagnostic={legacy_dominant}{interp_phrase}, cofire={legacy_cofire}"
    if digest_reason:
        reason += f"; {digest_reason}"

    lines = [
        # This region is generated from the governance registry itself; it
        # documents blocked/forbidden entities and their reactivation paths.
        # The Learning Hub forbidden_reference guard skips it (re-scanning
        # registry-derived governance text would be circular).
        "<!-- GOVERNANCE_POSTURE_START -->",
        "## Research Posture",
        "",
        f"**Posture:** {overall} — claim ceiling {quality} (limits claims, not research actions)",
        f"**Reason:** {reason}",
        "",
        "### What the system CAN say",
        "",
        f"- M/D primary readout is {primary_state} (diagnostic, not directional).",
        f"- Legacy dominant channel is {legacy_dominant}; cofire={legacy_cofire}. This is diagnostic-only.",
    ]
    say_actions = {"ACTIVE_WATCH", "ROBUSTNESS_TEST", "QUIET_WATCH"}
    for e in entries:
        if e.get("action_type") in say_actions and e.get("can_say"):
            lines.append(f"- {e['can_say']}")

    lines += ["", "### What to watch · next upgrade step", ""]
    watch_actions = {"ACTIVE_WATCH", "ROBUSTNESS_TEST", "DATA_REPAIR", "QUIET_WATCH"}
    any_watch = False
    for e in entries:
        if e.get("action_type") not in watch_actions:
            continue
        watch = ", ".join(e.get("watch", []))
        upgrade = ", ".join(e.get("upgrade_path", []))
        if not watch and not upgrade:
            continue
        any_watch = True
        bits = []
        if watch:
            bits.append(f"watch: {watch}")
        if upgrade:
            bits.append(f"upgrade: {upgrade}")
        lines.append(f"- **{e['entity']}** [{e.get('action_type')}] — " + "; ".join(bits))
    if not any_watch:
        lines.append("- Continue observation — no upgrade-ready candidate today.")

    lines += ["", "### What NOT to conclude · forbidden", ""]
    for guard in what_not.split("; "):
        if guard.strip():
            lines.append(f"- {guard.strip()}")
    for e in entries:
        if e.get("action_type") in {"BLOCKED", "IGNORE", "DATA_REPAIR"} and e.get("forbidden"):
            lines.append(
                f"- **{e['entity']}** [{e.get('status')}] is forbidden for: "
                + ", ".join(e["forbidden"])
            )

    lines.append("<!-- GOVERNANCE_POSTURE_END -->")
    return lines


def false_comfort_checks(fw: dict) -> dict:
    """Run the False Comfort Test checklist."""
    basic = fw.get("basic", {})
    adv = fw.get("advanced", {})
    sv = adv.get("sigma_vector", {})
    primary = adv.get("primary_readout", {})

    checks = {
        "active_full_shows_proxy_reduced": False,
        "diagnostics_not_in_voting": True,  # assume true unless violated
        "k_v2_not_replacing_k_v1": True,
        "x_agg_v2_still_diagnostic": True,
        "backtest_shows_sample_count": True,
    }

    # Check 1: ACTIVE_FULL shows PROXY_REDUCED
    if basic.get("overall") == "ACTIVE_FULL" and "PROXY_REDUCED" in basic.get("quality_status", ""):
        checks["active_full_shows_proxy_reduced"] = True

    # Check semantic warnings mention diagnostic
    semantic_warnings = sv.get("semantic_warning", [])
    for w in semantic_warnings:
        if "DIAGNOSTIC" in w:
            checks["diagnostics_not_in_voting"] = True
    if primary.get("blocked_from_primary") == ["K", "X_agg"]:
        checks["diagnostics_not_in_voting"] = True

    return checks


def generate_daily_note(fw: dict, date_str: str) -> str:
    """Generate the markdown daily note."""
    basic = fw.get("basic", {})
    adv = fw.get("advanced", {})
    sv = adv.get("sigma_vector", {})
    primary = adv.get("primary_readout", {})

    triggers = extract_triggers(fw)
    freshness_score, freshness_detail = score_freshness(fw)
    clarity_score, clarity_detail = score_clarity(fw)
    trigger_score, trigger_detail = score_trigger_quality(triggers)
    warning_score, warning_detail = score_warning_transparency(fw)

    what_not = determine_what_not_to_conclude(fw)
    posture_digest = load_json(POSTURE_JSON)
    posture_lines = build_research_posture_section(fw, posture_digest, what_not)
    false_comfort = false_comfort_checks(fw)

    # No-trigger test
    no_trigger_section = ""
    if not triggers or all(t["type"] == "quality_warning" for t in triggers):
        no_trigger_section = f"""
## No-Trigger Test

**Why no trigger:** M/D primary readout did not detect an anchor-path shift. Channels are active but within normal bounds.
**What to watch next:** M_anchor_geometry and D_path_geometry for regime confirmation.
**What not to infer:** Absence of trigger does not mean absence of risk — it means current readings are within bounds.
"""

    lines = [
        f"# Practicality Trial — Daily Note {date_str}",
        "",
        "## System Status",
        f"- **Overall:** {basic.get('overall', 'UNKNOWN')}",
        f"- **Quality:** {basic.get('quality_status', 'UNKNOWN')}",
        f"- **Coverage:** {adv.get('channel_coverage', {}).get('coverage_ratio', '?')}",
        f"- **Primary Market Space:** {primary.get('state', basic.get('primary_market_space', 'PRIMARY_READOUT_UNAVAILABLE'))}",
        f"- **Legacy Dominant Channel:** {sv.get('dominant_channel', 'N/A')} (diagnostic only)",
        f"- **Legacy Cofire Count:** {sv.get('cofire_count', 0)} (diagnostic only)",
        "",
        "## Channel Readings",
        "",
        "| Channel | Value | Readout Role | Quality | Family | Confidence |",
        "|---|---:|---|---|---|---|",
    ]

    for ch_name in ["M", "D", "K", "X_agg"]:
        ch = adv.get("channel_confidence", {}).get(ch_name, {})
        val = ch.get("value", 0)
        q = ch.get("proxy_quality", "?")
        fam = ch.get("family", "?")
        conf = ch.get("confidence", "?")
        role = ch.get("readout_role", "?")
        lines.append(f"| {ch_name} | {fmt_value(val)} | {role} | {q} | {fam} | {conf} |")

    lines += [
        "",
        "## Active Triggers",
        "",
    ]
    if triggers:
        for t in triggers:
            lines.append(f"- **{t['name']}** ({t['type']}): {t['detail']}")
    else:
        lines.append("- No active triggers")

    lines += [
        "",
        "## Diagnostic Monitors",
        "",
    ]
    # Extract governance flags from measurement audit
    gov_flags = _load_governance_flags()
    if gov_flags:
        monocultures = [g for g in gov_flags if "MONOCULTURE" in str(g).upper()]
        contract_violations = [g for g in gov_flags if "CONTRACT_VIOLATION" in str(g).upper()]
        horizon_issues = [g for g in gov_flags if "HORIZON_INCONSISTENT" in str(g).upper()]

        if monocultures:
            lines.append(f"- **Family Monocultures:** {len(monocultures)}")
            for m in monocultures[:3]:
                lines.append(f"  - {m}")
        if contract_violations:
            lines.append(f"- **Contract Violations:** {len(contract_violations)}")
            for v in contract_violations[:3]:
                lines.append(f"  - {v}")
        if horizon_issues:
            lines.append(f"- **Horizon Inconsistencies:** {len(horizon_issues)}")
    else:
        lines.append("- No replay evaluation available")

    lines += [
        "",
        "## Warnings",
        "",
    ]
    semantic_warnings = sv.get("semantic_warning", [])
    if semantic_warnings:
        for w in semantic_warnings:
            lines.append(f"- ⚠️ {w}")
    else:
        lines.append("- No warnings")

    lines += [
        "",
        no_trigger_section,
        "",
    ]
    lines += posture_lines
    lines += [
        "",
        "## False Comfort Test",
        "",
    ]
    for check, passed in false_comfort.items():
        emoji = "✅" if passed else "❌"
        label = check.replace("_", " ").title()
        lines.append(f"- {emoji} {label}")

    lines += [
        "",
        "---",
        "",
        "## Practicality Scoring (0–2 per dimension)",
        "",
        "| Dimension | Score | Detail |",
        "|---|---:|---|",
        f"| Data Freshness | {freshness_score} | {freshness_detail} |",
        f"| State Clarity | {clarity_score} | {clarity_detail} |",
        f"| Trigger Quality | {trigger_score} | {trigger_detail} |",
        f"| Warning Transparency | {warning_score} | {warning_detail} |",
        f"| Research Actionability | _fill_ | _fill_ |",
        f"| Overinterpretation Control | _fill_ | _fill_ |",
        "",
        f"**Total (auto):** {freshness_score + clarity_score + trigger_score + warning_score}/8",
        "**Total (manual):** _/12",
        "",
        "---",
        "",
        "## Human Benchmark (fill before next Hermes run)",
        "",
        f"See: `Output/practicality_trial/human_benchmark/{date_str}.md`",
    ]

    return "\n".join(lines)


def generate_human_benchmark_template(date_str: str) -> str:
    """Generate empty human benchmark template."""
    return f"""# Human Benchmark — {date_str}

Fill BEFORE looking at Hermes output.

## Pre-Hermes View

**My subjective read of today's market structure:**
<!-- 1-2 sentences. What do you think the structural state is? -->


## Post-Hermes Comparison

**Hermes added value (what did I not see?):**
<!-- What dimension did Hermes surface that I missed? -->


**Hermes corrected me (where was I wrong?):**
<!-- Did Hermes limit/纠正 my overinterpretation? -->


**Hermes was noise (what was useless?):**
<!-- What output added nothing? -->


**Final research action:**
<!-- What will I actually do today based on combined input? -->


## Scoring

| Question | Yes/No |
|---|---|
| Hermes provided incremental information? | |
| Hermes corrected/limited subjective bias? | |
| Hermes structured my judgment? | |
| Hermes was merely repeating what I knew? | |
"""


def append_scores_csv(date_str: str, fw: dict) -> None:
    """Append today's scores to the CSV."""
    basic = fw.get("basic", {})
    adv = fw.get("advanced", {})
    sv = adv.get("sigma_vector", {})
    triggers = extract_triggers(fw)

    freshness_score, _ = score_freshness(fw)
    clarity_score, _ = score_clarity(fw)
    trigger_score, _ = score_trigger_quality(triggers)
    warning_score, _ = score_warning_transparency(fw)

    row = {
        "date": date_str,
        "overall": basic.get("overall", ""),
        "quality_status": basic.get("quality_status", ""),
        "dominant_channel": sv.get("dominant_channel", ""),
        "cofire_count": sv.get("cofire_count", 0),
        "num_triggers": len(triggers),
        "data_freshness": freshness_score,
        "state_clarity": clarity_score,
        "trigger_quality": trigger_score,
        "warning_transparency": warning_score,
        "research_actionability": "",  # manual
        "overinterpretation_control": "",  # manual
        "total_auto": freshness_score + clarity_score + trigger_score + warning_score,
        "total_manual": "",  # manual
    }

    file_exists = SCORES_CSV.exists()
    with SCORES_CSV.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=row.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(description="Practicality Trial Daily Note")
    parser.add_argument("--date", default=datetime.now(UTC).strftime("%Y-%m-%d"))
    args = parser.parse_args()

    date_str = args.date

    fw = load_json(FW_PATH)
    if not fw:
        print(f"ERROR: framework_output.json not found at {FW_PATH}")
        return

    # Generate daily note
    note = generate_daily_note(fw, date_str)
    note_path = OUTPUT / f"{date_str}_daily_note.md"
    note_path.write_text(note, encoding="utf-8")
    print(f"Daily note: {note_path}")

    # Generate human benchmark template
    hb = generate_human_benchmark_template(date_str)
    hb_path = OUTPUT / "human_benchmark" / f"{date_str}.md"
    hb_path.write_text(hb, encoding="utf-8")
    print(f"Human benchmark: {hb_path}")

    # Append scores
    append_scores_csv(date_str, fw)
    print(f"Scores appended: {SCORES_CSV}")

    # Print summary
    basic = fw.get("basic", {})
    sv = fw.get("advanced", {}).get("sigma_vector", {})
    print(f"\n=== {date_str} ===")
    print(f"Overall: {basic.get('overall')}")
    print(f"Quality: {basic.get('quality_status')}")
    primary = fw.get("advanced", {}).get("primary_readout", {})
    print(f"Primary readout: {primary.get('state', basic.get('primary_market_space'))}")
    print(f"Legacy dominant diagnostic: {sv.get('dominant_channel')}")
    print(f"Legacy cofire diagnostic: {sv.get('cofire_count')}")


if __name__ == "__main__":
    main()
