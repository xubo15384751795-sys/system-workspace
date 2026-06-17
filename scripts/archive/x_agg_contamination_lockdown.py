#!/usr/bin/env python3
"""X_agg Trigger Contamination Lockdown.

Freezes all composite X_agg daily triggers and marks contaminated artifacts.
Does NOT change canonical X_agg values, M/D/K, or generate trading signals.

Output: Output/x_agg_frequency_split/X_AGG_TRIGGER_CONTAMINATION_LOCKDOWN.md
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "Output" / "x_agg_frequency_split"
REPLAY_DIR = ROOT / "Output" / "sandbox" / "structural_replay_v2"
RESULTS_PATH = REPLAY_DIR / "results.json"
SIGMA_PATH = REPLAY_DIR / "sigma_vector.json"
FREQ_DIR = OUTPUT  # frequency split output is here


def load_json(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def mark_contaminated_triggers() -> list[dict]:
    """Mark all historical X_agg triggers as contaminated."""
    results = load_json(RESULTS_PATH) or []
    contaminated = []

    for r in results:
        event_id = r.get("event_id", "unknown")
        peak_date = r.get("peak_date", "")
        path = r.get("observed_path", [])

        for entry in path:
            if entry.get("channel") == "X_agg":
                contaminated.append({
                    "event_id": event_id,
                    "peak_date": peak_date,
                    "channel": "X_agg",
                    "value": entry.get("value", 0),
                    "threshold": entry.get("threshold", 0),
                    "days_before_peak": entry.get("days_before_peak", "?"),
                    "contamination_status": "CONTAMINATED_BY_QUARTERLY_FORWARD_FILL",
                    "original_interpretation": "daily positive_spike",
                    "corrected_interpretation": "quarterly SEC OBS_DERIV_TO_ASSETS forward-fill artifact",
                    "action": "FROZEN_PENDING_DAILY_RETEST",
                })

    return contaminated


def mark_contaminated_strategies() -> list[dict]:
    """Mark X_agg-related strategy prototypes as frozen."""
    return [
        {
            "strategy": "X_agg_spike_SPY_60d",
            "previous_status": "strategy prototype retain",
            "new_status": "FROZEN_PENDING_DAILY_RETEST",
            "reason": "X_agg spike driven by quarterly forward-fill, not daily market movement",
            "action": "freeze until daily-only retest confirms validity",
        },
        {
            "strategy": "X_agg_positive_spike forward return",
            "previous_status": "candidate trigger",
            "new_status": "INVALID_FOR_DAILY_TRIGGER_INTERPRETATION",
            "reason": "11/11 historical triggers contaminated by quarterly component",
            "action": "freeze, retest with daily-only component",
        },
        {
            "strategy": "X_agg_dominant",
            "previous_status": "active trigger",
            "new_status": "FROZEN_PENDING_DAILY_RETEST",
            "reason": "dominant channel determination may be driven by stale quarterly data",
            "action": "audit whether dominant was set by quarterly component",
        },
    ]


def update_hypothesis_registry() -> list[dict]:
    """Update hypothesis statuses."""
    return [
        {
            "hypothesis": "H2: X_agg → recovery",
            "previous_status": "active",
            "new_status": "FROZEN_PENDING_DAILY_RETEST",
            "reason": "quarterly forward-fill contamination",
        },
        {
            "hypothesis": "H2b: X_agg_positive_spike",
            "previous_status": "candidate trigger",
            "new_status": "CONTAMINATED_BY_QUARTERLY_FORWARD_FILL",
            "reason": "11/11 triggers contaminated",
        },
        {
            "hypothesis": "X_agg_composite daily trigger",
            "previous_status": "active",
            "new_status": "DISABLED",
            "reason": "mixed-frequency composite cannot generate reliable daily triggers",
        },
        {
            "hypothesis": "X_agg_daily_component",
            "previous_status": "not separated",
            "new_status": "DAILY_DIAGNOSTIC_CANDIDATE",
            "reason": "only valid daily X_agg source, needs retest",
        },
        {
            "hypothesis": "X_agg_quarterly_slow",
            "previous_status": "part of composite",
            "new_status": "BACKGROUND_ONLY",
            "reason": "SEC OBS_DERIV_TO_ASSETS quarterly, too stale for daily interpretation",
        },
    ]


def build_daily_note_additions() -> dict:
    """New fields to add to daily note output."""
    return {
        "x_agg_daily_interpretation": "RESTRICTED",
        "x_agg_composite_daily_trigger": "DISABLED",
        "x_agg_quarterly_slow_component": "BACKGROUND_ONLY",
        "x_agg_daily_component_coverage": "45.6%",
        "x_agg_contamination_warning": (
            "Historical X_agg spike backtests are contaminated by quarterly forward-fill. "
            "Results cannot be interpreted as daily trigger evidence. "
            "Awaiting daily-only retest."
        ),
    }


def generate_lockdown_report(
    contaminated_triggers: list[dict],
    contaminated_strategies: list[dict],
    hypotheses: list[dict],
    daily_note_fields: dict,
) -> str:
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# X_agg Trigger Contamination Lockdown Report",
        "",
        f"**Generated:** {now}",
        f"**Purpose:** Freeze contaminated X_agg daily triggers and prevent further contamination.",
        "",
        "---",
        "",
        "## 1. Contaminated Triggers",
        "",
        f"**Total contaminated:** {len(contaminated_triggers)}",
        "",
        "| Event | Peak | Days Before | Value | Threshold | Status |",
        "|---|---|---:|---:|---:|---|",
    ]

    for t in contaminated_triggers:
        lines.append(
            f"| {t['event_id']} | {t['peak_date']} | {t['days_before_peak']} | "
            f"{t['value']:.3f} | {t['threshold']:.3f} | {t['contamination_status']} |"
        )

    lines += [
        "",
        "**All historical X_agg positive_spike triggers are contaminated.**",
        "They cannot be interpreted as daily market signals.",
        "",
        "---",
        "",
        "## 2. Frozen Strategies",
        "",
        "| Strategy | Previous Status | New Status | Reason |",
        "|---|---|---|---|",
    ]

    for s in contaminated_strategies:
        lines.append(
            f"| {s['strategy']} | {s['previous_status']} | {s['new_status']} | {s['reason']} |"
        )

    lines += [
        "",
        "---",
        "",
        "## 3. Hypothesis Registry Updates",
        "",
        "| Hypothesis | Previous | New | Reason |",
        "|---|---|---|---|",
    ]

    for h in hypotheses:
        lines.append(
            f"| {h['hypothesis']} | {h['previous_status']} | {h['new_status']} | {h['reason']} |"
        )

    lines += [
        "",
        "---",
        "",
        "## 4. Daily Note Additions",
        "",
        "The following fields must appear in daily note output:",
        "",
    ]

    for key, val in daily_note_fields.items():
        lines.append(f"- **{key}:** {val}")

    lines += [
        "",
        "---",
        "",
        "## 5. What Still Works",
        "",
        "X_agg is NOT废. These uses remain valid:",
        "",
        "- **X_agg_composite as slow structural background** — quarterly balance-sheet pressure context",
        "- **X_agg_weekly as weekly-aware diagnostic** — NFCI leverage component (76.3% coverage)",
        "- **X_agg_daily as restricted daily diagnostic** — OFR/Treasury/SOFR daily proxies (45.6% coverage)",
        "- **X_agg quarterly narrative** — shadow accumulation story, not daily timing",
        "",
        "**NOT valid after lockdown:**",
        "",
        "- X_agg_composite daily spike trigger",
        "- X_agg_quarterly_slow daily trigger",
        "- Any daily timing based on composite X_agg",
        "- Historical X_agg spike backtest results as daily signal evidence",
        "",
        "---",
        "",
        "## 6. Next Steps",
        "",
        "1. **X_agg Daily-Only Retest** — retest using only daily component (OFR, Treasury, SOFR)",
        "2. **If daily has expression** → upgrade X_agg_daily to diagnostic candidate",
        "3. **If daily has no expression** → X_agg is background-only until daily data is supplemented",
        "4. **Supplement daily sources** — FINRA margin debt, ETF flows, repo, CP, dealer leverage",
        "",
    ]

    return "\n".join(lines) + "\n"


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)

    print("Marking contaminated triggers...")
    contaminated_triggers = mark_contaminated_triggers()

    print("Marking contaminated strategies...")
    contaminated_strategies = mark_contaminated_strategies()

    print("Updating hypothesis registry...")
    hypotheses = update_hypothesis_registry()

    print("Building daily note additions...")
    daily_note_fields = build_daily_note_additions()

    # Write contaminated triggers
    ct_path = OUTPUT / "contaminated_triggers.json"
    ct_path.write_text(json.dumps(contaminated_triggers, indent=2, default=str), encoding="utf-8")
    print(f"Wrote: {ct_path}")

    # Write frozen strategies
    fs_path = OUTPUT / "frozen_strategies.json"
    fs_path.write_text(json.dumps(contaminated_strategies, indent=2, default=str), encoding="utf-8")
    print(f"Wrote: {fs_path}")

    # Write hypothesis updates
    hyp_path = OUTPUT / "hypothesis_registry_updates.json"
    hyp_path.write_text(json.dumps(hypotheses, indent=2, default=str), encoding="utf-8")
    print(f"Wrote: {hyp_path}")

    # Write daily note additions
    dn_path = OUTPUT / "daily_note_additions.json"
    dn_path.write_text(json.dumps(daily_note_fields, indent=2, default=str), encoding="utf-8")
    print(f"Wrote: {dn_path}")

    # Generate report
    report = generate_lockdown_report(contaminated_triggers, contaminated_strategies, hypotheses, daily_note_fields)
    report_path = OUTPUT / "X_AGG_TRIGGER_CONTAMINATION_LOCKDOWN.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"Wrote: {report_path}")

    print(f"\n=== Lockdown Complete ===")
    print(f"Contaminated triggers: {len(contaminated_triggers)}")
    print(f"Frozen strategies: {len(contaminated_strategies)}")
    print(f"Updated hypotheses: {len(hypotheses)}")


if __name__ == "__main__":
    main()
