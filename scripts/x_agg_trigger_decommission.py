#!/usr/bin/env python3
"""X_agg Trigger Decommission.

Formally disables all X_agg composite daily triggers and updates
hypothesis/strategy registries.

Output: Output/x_agg_frequency_split/X_AGG_TRIGGER_DECOMMISSION_REPORT.md
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "Output" / "x_agg_frequency_split"
LOCKDOWN = OUTPUT / "X_AGG_TRIGGER_CONTAMINATION_LOCKDOWN.md"
RETEST = ROOT / "Output" / "x_agg_daily_retest" / "X_AGG_DAILY_RETEST_REPORT.md"


def load_json(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def build_hypothesis_registry() -> list[dict]:
    return [
        {
            "id": "H2",
            "hypothesis": "X_agg → recovery",
            "previous_status": "FROZEN_PENDING_DAILY_RETEST",
            "new_status": "FROZEN_PENDING_NEW_DAILY_DATA",
            "reason": "Daily-only retest failed: 1504 triggers at z≥1.5, 0 matched control pairs, insufficient discrimination.",
            "valid_uses": ["slow structural background", "historical context"],
            "invalid_uses": ["daily trigger", "daily timing", "strategy prototype"],
        },
        {
            "id": "H2b",
            "hypothesis": "X_agg_positive_spike",
            "previous_status": "CONTAMINATED_BY_QUARTERLY_FORWARD_FILL",
            "new_status": "DISABLED_CONTAMINATED",
            "reason": "11/11 historical triggers contaminated by quarterly SEC OBS_DERIV_TO_ASSETS forward-fill.",
            "valid_uses": [],
            "invalid_uses": ["daily trigger", "backtest strategy", "forward return evidence"],
        },
        {
            "id": "X_agg_composite",
            "hypothesis": "X_agg composite daily trigger",
            "previous_status": "DISABLED",
            "new_status": "DISABLED_CONTAMINATED",
            "reason": "Mixed-frequency composite cannot generate reliable daily triggers.",
            "valid_uses": ["slow structural background"],
            "invalid_uses": ["daily spike", "daily timing"],
        },
        {
            "id": "X_agg_daily",
            "hypothesis": "X_agg daily component",
            "previous_status": "DAILY_DIAGNOSTIC_CANDIDATE",
            "new_status": "DAILY_DIAGNOSTIC_CANDIDATE / INSUFFICIENT_DISCRIMINATION",
            "reason": "4 daily proxies (OFR, Treasury debt/cash, SOFR-IORB) have 45.6% coverage but z≥1.5 triggers 1504 times. No discrimination power.",
            "valid_uses": ["diagnostic warning", "data quality monitor"],
            "invalid_uses": ["daily trigger", "strategy prototype"],
        },
        {
            "id": "X_agg_weekly",
            "hypothesis": "X_agg weekly component",
            "previous_status": "WEEKLY_CONTEXT",
            "new_status": "WEEKLY_CONTEXT",
            "reason": "NFCI leverage weekly (76.3% coverage). Valid for weekly-aware context, not daily spike.",
            "valid_uses": ["weekly context", "slow leverage indicator"],
            "invalid_uses": ["daily spike trigger"],
        },
        {
            "id": "X_agg_quarterly",
            "hypothesis": "X_agg quarterly component",
            "previous_status": "BACKGROUND_ONLY",
            "new_status": "BACKGROUND_ONLY",
            "reason": "SEC OBS_DERIV_TO_ASSETS quarterly (8.6% coverage). Too stale for any timing.",
            "valid_uses": ["slow balance-sheet background"],
            "invalid_uses": ["daily trigger", "weekly trigger", "any timing signal"],
        },
    ]


def build_strategy_registry() -> list[dict]:
    return [
        {
            "strategy": "X_agg_spike_SPY_60d",
            "previous_status": "FROZEN_PENDING_DAILY_RETEST",
            "new_status": "FROZEN_PENDING_NEW_DAILY_DATA",
            "reason": "Composite spike contaminated. Daily-only retest insufficient.",
            "can_reactivate": True,
            "reactivation_condition": "New daily shadow leverage data + discrimination retest",
        },
        {
            "strategy": "X_agg_positive_spike forward return",
            "previous_status": "INVALID_FOR_DAILY_TRIGGER_INTERPRETATION",
            "new_status": "DISABLED_CONTAMINATED",
            "reason": "All historical triggers contaminated by quarterly forward-fill.",
            "can_reactivate": False,
            "reactivation_condition": "N/A — must rebuild from daily-only component",
        },
        {
            "strategy": "X_agg_dominant daily trigger",
            "previous_status": "FROZEN_PENDING_DAILY_RETEST",
            "new_status": "DISABLED_CONTAMINATED",
            "reason": "Dominant channel determination may have been driven by stale quarterly data.",
            "can_reactivate": True,
            "reactivation_condition": "New daily data + discrimination validation",
        },
    ]


def build_daily_note_schema() -> dict:
    return {
        "x_agg_daily_trigger": "DISABLED",
        "x_agg_composite": "SLOW_STRUCTURAL_BACKGROUND",
        "x_agg_daily_component": "INSUFFICIENT_DISCRIMINATION",
        "x_agg_weekly": "WEEKLY_CONTEXT",
        "x_agg_quarterly_slow": "BACKGROUND_ONLY",
        "x_agg_contamination_status": "DECOMMISSIONED",
        "x_agg_reactivation": "PENDING_NEW_DAILY_DATA",
        "x_agg_warning": (
            "X_agg daily trigger decommissioned. "
            "Historical spike results contaminated by quarterly forward-fill. "
            "Daily component has insufficient discrimination (1504 triggers at z≥1.5). "
            "X_agg currently serves as slow structural background only."
        ),
    }


def generate_report(
    hypotheses: list[dict],
    strategies: list[dict],
    daily_schema: dict,
) -> str:
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# X_agg Trigger Decommission Report",
        "",
        f"**Generated:** {now}",
        f"**Purpose:** Formally decommission all X_agg daily triggers.",
        "",
        "---",
        "",
        "## 1. Decommission Summary",
        "",
        "| Item | Previous Status | New Status |",
        "|---|---|---|",
    ]

    for h in hypotheses:
        lines.append(f"| {h['id']}: {h['hypothesis']} | {h['previous_status']} | {h['new_status']} |")
    for s in strategies:
        lines.append(f"| Strategy: {s['strategy']} | {s['previous_status']} | {s['new_status']} |")

    lines += [
        "",
        "---",
        "",
        "## 2. Hypothesis Registry (Final)",
        "",
    ]

    for h in hypotheses:
        lines += [
            f"### {h['id']}: {h['hypothesis']}",
            f"- **Status:** {h['new_status']}",
            f"- **Reason:** {h['reason']}",
            f"- **Valid uses:** {', '.join(h['valid_uses']) if h['valid_uses'] else 'none'}",
            f"- **Invalid uses:** {', '.join(h['invalid_uses'])}",
            "",
        ]

    lines += [
        "---",
        "",
        "## 3. Strategy Registry (Final)",
        "",
        "| Strategy | Status | Can Reactivate | Condition |",
        "|---|---|---|---|",
    ]

    for s in strategies:
        react = "✅" if s["can_reactivate"] else "❌"
        lines.append(
            f"| {s['strategy']} | {s['new_status']} | {react} | {s['reactivation_condition']} |"
        )

    lines += [
        "",
        "---",
        "",
        "## 4. Daily Note Schema",
        "",
        "The following fields must appear in all daily notes:",
        "",
    ]

    for key, val in daily_schema.items():
        lines.append(f"- **{key}:** {val}")

    lines += [
        "",
        "---",
        "",
        "## 5. What X_agg Can Still Do",
        "",
        "### ✅ Valid uses (post-decommission):",
        "- Slow structural background (quarterly balance-sheet pressure context)",
        "- Weekly leverage context (NFCI weekly, 76.3% coverage)",
        "- Historical structural narrative",
        "- Data acquisition priority map",
        "- Diagnostic warning (daily component z-score monitor)",
        "",
        "### ❌ Invalid uses (post-decommission):",
        "- Daily spike trigger",
        "- Daily timing signal",
        "- Daily strategy prototype",
        "- Forward return evidence for daily triggers",
        "- Dominant channel daily determination",
        "",
        "---",
        "",
        "## 6. Reactivation Path",
        "",
        "To reactivate X_agg daily triggers:",
        "",
        "1. **Acquire new daily shadow leverage data** (FINRA margin, ETF flows, repo, CP, dealer leverage)",
        "2. **Rebuild daily component** with new data",
        "3. **Retest discrimination** — z-score distribution, trigger frequency, matched control",
        "4. **Validate forward returns** with proper control group",
        "5. **Only then** promote back to DAILY_DIAGNOSTIC_CANDIDATE",
        "",
        "Estimated timeline: depends on data acquisition. Not a code problem.",
        "",
    ]

    return "\n".join(lines) + "\n"


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)

    hypotheses = build_hypothesis_registry()
    strategies = build_strategy_registry()
    daily_schema = build_daily_note_schema()

    # Write registries
    hyp_path = OUTPUT / "hypothesis_registry_final.json"
    hyp_path.write_text(json.dumps(hypotheses, indent=2, default=str), encoding="utf-8")
    print(f"Wrote: {hyp_path}")

    strat_path = OUTPUT / "strategy_registry_final.json"
    strat_path.write_text(json.dumps(strategies, indent=2, default=str), encoding="utf-8")
    print(f"Wrote: {strat_path}")

    schema_path = OUTPUT / "daily_note_schema_x_agg.json"
    schema_path.write_text(json.dumps(daily_schema, indent=2, default=str), encoding="utf-8")
    print(f"Wrote: {schema_path}")

    # Generate report
    report = generate_report(hypotheses, strategies, daily_schema)
    report_path = OUTPUT / "X_AGG_TRIGGER_DECOMMISSION_REPORT.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"Wrote: {report_path}")

    print(f"\n=== Decommission Complete ===")
    print(f"Hypotheses: {len(hypotheses)}")
    print(f"Strategies: {len(strategies)}")


if __name__ == "__main__":
    main()
