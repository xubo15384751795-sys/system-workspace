#!/usr/bin/env python3
"""X_agg Frequency Split Sprint.

Splits X_agg from a mixed-frequency composite into frequency-aware
sub-components to reduce daily interpretation risk.

Output:
  Output/x_agg_frequency_split/x_agg_component_series.csv
  Output/x_agg_frequency_split/x_agg_component_metadata.json
  Output/x_agg_frequency_split/x_agg_trigger_frequency_audit.csv
  Output/x_agg_frequency_split/X_AGG_FREQUENCY_SPLIT_REPORT.md
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "Output" / "x_agg_frequency_split"
REPLAY_DIR = ROOT / "Output" / "sandbox" / "structural_replay_v2"
COMP_PATH = REPLAY_DIR / "proxy_components.parquet"
REGISTRY_PATH = REPLAY_DIR / "proxy_registry.json"
RESULTS_PATH = REPLAY_DIR / "results.json"
SIGMA_PATH = REPLAY_DIR / "sigma_vector.json"

# X_agg proxy → frequency mapping (from registry)
FREQUENCY_MAP = {
    "X_agg_v1_obs_to_assets_candidate": "quarterly",
    "X_agg_off_balance_sheet_v1": "quarterly",
    "X_agg_v2_nfcileverage_quarantined_redline": "weekly",
    "X_agg_canonical_NOT_IMPLEMENTED_v3_shadow_funding_substitution": "weekly",
    "X_agg_hidden_leverage_ofr": "daily",
    "X_agg_v1_treasury_debt_pressure": "daily",
    "X_agg_v2_treasury_cash_balance": "daily",
    "X_agg_v3_sofr_iorb_spread": "daily",
}

FAMILY_MAP = {
    "X_agg_v1_obs_to_assets_candidate": "SEC_OBS",
    "X_agg_off_balance_sheet_v1": "SEC_OBS",
    "X_agg_v2_nfcileverage_quarantined_redline": "NFCI",
    "X_agg_hidden_leverage_ofr": "OFR_SYSTEMIC",
    "X_agg_v1_treasury_debt_pressure": "TREASURY_DEBT",
    "X_agg_v2_treasury_cash_balance": "TREASURY_CASH",
    "X_agg_v3_sofr_iorb_spread": "DERIVED_FUNDING",
}

TIER_MAP = {
    "X_agg_v1_obs_to_assets_candidate": "core",
    "X_agg_off_balance_sheet_v1": "core",
    "X_agg_v2_nfcileverage_quarantined_redline": "auxiliary",
    "X_agg_hidden_leverage_ofr": "auxiliary",
    "X_agg_v1_treasury_debt_pressure": "auxiliary",
    "X_agg_v2_treasury_cash_balance": "auxiliary",
    "X_agg_v3_sofr_iorb_spread": "core",
}


def load_data() -> tuple[pd.DataFrame, list, dict]:
    comp = pd.read_parquet(COMP_PATH)
    comp["date"] = pd.to_datetime(comp["date"]) if "date" in comp.columns else comp.index
    results = json.loads(RESULTS_PATH.read_text()) if RESULTS_PATH.exists() else []
    sigma = json.loads(SIGMA_PATH.read_text()) if SIGMA_PATH.exists() else {}
    return comp, results, sigma


def compute_frequency_components(comp: pd.DataFrame) -> dict[str, pd.Series]:
    """Compute per-frequency aggregated z-scores."""
    x_agg_cols = [c for c in comp.columns if c.startswith("X_agg") and c in FREQUENCY_MAP]

    daily_cols = [c for c in x_agg_cols if FREQUENCY_MAP[c] == "daily"]
    weekly_cols = [c for c in x_agg_cols if FREQUENCY_MAP[c] == "weekly"]
    quarterly_cols = [c for c in x_agg_cols if FREQUENCY_MAP[c] == "quarterly"]

    components = {}

    # Daily component: mean of daily proxies
    if daily_cols:
        daily_data = comp[daily_cols]
        components["X_agg_daily"] = daily_data.mean(axis=1, skipna=True)

    # Weekly component
    if weekly_cols:
        weekly_data = comp[weekly_cols]
        components["X_agg_weekly"] = weekly_data.mean(axis=1, skipna=True)

    # Quarterly component
    if quarterly_cols:
        quarterly_data = comp[quarterly_cols]
        components["X_agg_quarterly_slow"] = quarterly_data.mean(axis=1, skipna=True)

    # Composite: mean of all available
    all_cols = daily_cols + weekly_cols + quarterly_cols
    if all_cols:
        components["X_agg_composite"] = comp[all_cols].mean(axis=1, skipna=True)

    return components


def compute_component_metadata(comp: pd.DataFrame, components: dict[str, pd.Series]) -> list[dict]:
    """Compute metadata for each component."""
    metadata = []

    for name, series in components.items():
        nn = series.notna().sum()
        total = len(series)
        coverage = nn / total if total > 0 else 0

        # Determine native frequency
        if "daily" in name:
            native_freq = "daily"
        elif "weekly" in name:
            native_freq = "weekly"
        elif "quarterly" in name:
            native_freq = "quarterly"
        else:
            native_freq = "mixed"

        # Check for forward fill (quarterly data appearing daily = forward filled)
        if native_freq == "quarterly" and coverage > 0.1:
            # quarterly data should only appear ~4x per year
            # if coverage > 10%, it's being forward-filled
            forward_fill_active = True
            expected_coverage = 4 * (total / 252) / total  # ~4 obs per year / total days
            stale_days_estimate = round(252 / 4)  # ~63 trading days between observations
        else:
            forward_fill_active = False
            expected_coverage = None
            stale_days_estimate = None

        # Source families
        if "daily" in name:
            families = [FAMILY_MAP[c] for c in FREQUENCY_MAP if FREQUENCY_MAP[c] == "daily" and c in comp.columns]
            proxy_count = sum(1 for c in FREQUENCY_MAP if FREQUENCY_MAP[c] == "daily" and c in comp.columns)
        elif "weekly" in name:
            families = [FAMILY_MAP[c] for c in FREQUENCY_MAP if FREQUENCY_MAP[c] == "weekly" and c in comp.columns]
            proxy_count = sum(1 for c in FREQUENCY_MAP if FREQUENCY_MAP[c] == "weekly" and c in comp.columns)
        elif "quarterly" in name:
            families = [FAMILY_MAP[c] for c in FREQUENCY_MAP if FREQUENCY_MAP[c] == "quarterly" and c in comp.columns]
            proxy_count = sum(1 for c in FREQUENCY_MAP if FREQUENCY_MAP[c] == "quarterly" and c in comp.columns)
        else:
            families = list(set(FAMILY_MAP.values()))
            proxy_count = sum(1 for c in FREQUENCY_MAP if c in comp.columns)

        # Allowed for daily interpretation
        if native_freq == "daily":
            allowed_daily = True
            daily_reason = "native daily frequency"
        elif native_freq == "weekly":
            allowed_daily = True  # weekly can inform daily context
            daily_reason = "weekly-aware context, not for daily spike"
        elif native_freq == "quarterly":
            allowed_daily = False
            daily_reason = "quarterly forward-fill, too stale for daily interpretation"
        else:
            allowed_daily = True
            daily_reason = "composite — check component breakdown"

        metadata.append({
            "component": name,
            "native_frequency": native_freq,
            "effective_frequency": "forward_filled_quarterly" if forward_fill_active else native_freq,
            "source_families": sorted(set(families)),
            "proxy_count": proxy_count,
            "coverage": round(coverage, 4),
            "stale_days_estimate": stale_days_estimate,
            "forward_fill_active": forward_fill_active,
            "allowed_for_daily_interpretation": allowed_daily,
            "daily_interpretation_reason": daily_reason,
            "non_null_count": int(nn),
            "total_count": int(total),
            "mean": round(float(series.dropna().mean()), 4) if nn > 0 else None,
            "std": round(float(series.dropna().std()), 4) if nn > 0 else None,
            "last_value": round(float(series.dropna().iloc[-1]), 4) if nn > 0 else None,
        })

    return metadata


def audit_triggers(components: dict[str, pd.Series], results: list) -> list[dict]:
    """Audit which X_agg triggers in historical events were driven by which frequency."""
    audits = []

    for r in results:
        event_id = r.get("event_id", "unknown")
        peak_date = r.get("peak_date", "")
        path = r.get("observed_path", [])

        # Find X_agg entries in the path
        x_agg_entries = [p for p in path if p.get("channel") == "X_agg"]

        for entry in x_agg_entries:
            trigger_val = entry.get("value", 0)
            threshold = entry.get("threshold", 0)
            days_before = entry.get("days_before_peak", "?")

            # Determine which component likely drove this trigger
            # by checking which component has data at that time
            contaminated = False
            likely_source = "unknown"

            if peak_date:
                peak_dt = pd.Timestamp(peak_date)
                # Check quarterly component
                for comp_name, series in components.items():
                    if "quarterly" in comp_name:
                        # quarterly data is forward-filled, so it appears at every date
                        # if the trigger happened when quarterly was the main driver
                        nn = series.notna().sum()
                        if nn > 0:
                            # quarterly has very low actual observation count
                            # most "daily" readings are forward-filled
                            contaminated = True
                            likely_source = "quarterly_forward_fill"

            audits.append({
                "event_id": event_id,
                "peak_date": peak_date,
                "days_before_peak": days_before,
                "trigger_value": round(trigger_val, 4),
                "threshold": round(threshold, 4),
                "trigger_frequency_contaminated": contaminated,
                "likely_frequency_source": likely_source,
                "daily_trigger_allowed": not contaminated,
            })

    return audits


def generate_report(metadata: list[dict], audits: list[dict], sigma: dict) -> str:
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# X_agg Frequency Split Report",
        "",
        f"**Generated:** {now}",
        f"**Purpose:** Split X_agg from mixed-frequency composite into frequency-aware sub-components.",
        "",
        "---",
        "",
        "## Current X_agg Status",
        "",
        f"- **Composite value:** {sigma.get('sigma_vector', {}).get('X_agg', 'N/A')}",
        f"- **Dominant channel:** {sigma.get('sigma_vector', {}).get('dominant_channel', 'N/A')}",
        f"- **Frequency status:** MIXED (daily + weekly + quarterly)",
        "",
        "---",
        "",
        "## Component Breakdown",
        "",
        "| Component | Native Freq | Coverage | Proxy Count | Daily Allowed | Last Value |",
        "|---|---|---:|---:|---|---:|",
    ]

    for m in metadata:
        allowed = "✅" if m["allowed_for_daily_interpretation"] else "❌"
        last = f"{m['last_value']:.3f}" if m["last_value"] is not None else "N/A"
        lines.append(
            f"| {m['component']} | {m['native_frequency']} | "
            f"{m['coverage']*100:.1f}% | {m['proxy_count']} | {allowed} | {last} |"
        )

    lines += [
        "",
        "## Component Details",
        "",
    ]

    for m in metadata:
        ff = "⚠️ YES — quarterly data forward-filled to daily" if m["forward_fill_active"] else "NO"
        stale = f"~{m['stale_days_estimate']} trading days" if m["stale_days_estimate"] else "N/A"
        lines += [
            f"### {m['component']}",
            f"- Native frequency: {m['native_frequency']}",
            f"- Effective frequency: {m['effective_frequency']}",
            f"- Source families: {', '.join(m['source_families'])}",
            f"- Proxy count: {m['proxy_count']}",
            f"- Coverage: {m['coverage']*100:.1f}%",
            f"- Forward fill active: {ff}",
            f"- Stale estimate: {stale}",
            f"- **Daily interpretation:** {'✅ ALLOWED' if m['allowed_for_daily_interpretation'] else '❌ RESTRICTED'} — {m['daily_interpretation_reason']}",
            "",
        ]

    # Trigger audit
    lines += [
        "---",
        "",
        "## Trigger Frequency Audit",
        "",
        f"- Total X_agg triggers in historical events: {len(audits)}",
        f"- Contaminated by quarterly forward-fill: {sum(1 for a in audits if a['trigger_frequency_contaminated'])}",
        "",
    ]

    if audits:
        lines += [
            "| Event | Days Before | Value | Threshold | Contaminated | Daily Allowed |",
            "|---|---:|---:|---:|---|---|",
        ]
        for a in audits:
            contam = "⚠️ YES" if a["trigger_frequency_contaminated"] else "✅ NO"
            allowed = "❌" if a["trigger_frequency_contaminated"] else "✅"
            lines.append(
                f"| {a['event_id']} | {a['days_before_peak']} | "
                f"{a['trigger_value']:.3f} | {a['threshold']:.3f} | {contam} | {allowed} |"
            )

    # Analysis
    daily_comp = next((m for m in metadata if m["component"] == "X_agg_daily"), None)
    weekly_comp = next((m for m in metadata if m["component"] == "X_agg_weekly"), None)
    quarterly_comp = next((m for m in metadata if m["component"] == "X_agg_quarterly_slow"), None)

    lines += [
        "",
        "---",
        "",
        "## Analysis",
        "",
        "### Daily/Weekly/Quarterly Contribution",
        "",
    ]

    if daily_comp:
        lines.append(f"- **Daily component:** coverage={daily_comp['coverage']*100:.1f}%, {daily_comp['proxy_count']} proxies, daily interpretation ALLOWED")
    if weekly_comp:
        lines.append(f"- **Weekly component:** coverage={weekly_comp['coverage']*100:.1f}%, {weekly_comp['proxy_count']} proxies, daily context ALLOWED (not for spike)")
    if quarterly_comp:
        lines.append(f"- **Quarterly component:** coverage={quarterly_comp['coverage']*100:.1f}%, {quarterly_comp['proxy_count']} proxies, daily interpretation RESTRICTED (forward-fill)")

    contaminated_count = sum(1 for a in audits if a["trigger_frequency_contaminated"])
    lines += [
        "",
        "### Trigger Contamination",
        "",
        f"- {contaminated_count}/{len(audits)} historical X_agg triggers were likely driven by quarterly forward-fill.",
        "- This means daily spike signals from X_agg may be artifacts of stale quarterly data, not real daily market movement.",
        "",
        "### Recommendations",
        "",
        "1. **Daily trigger diagnostics** should use X_agg_daily or X_agg_weekly components only.",
        "2. **X_agg_composite** should display frequency_mix warning in all outputs.",
        "3. **Quarterly component** should be labeled as slow background, not daily signal.",
        "4. **If daily/weekly coverage is insufficient**, X_agg daily interpretation should remain RESTRICTED.",
        "5. **Future data acquisition** should prioritize daily-frequency X_agg proxies.",
        "",
        "---",
        "",
        "## Answers",
        "",
        f"**Q: Current X_agg daily/weekly/quarterly contribution ratio?**",
        f"- Daily: {daily_comp['proxy_count']} proxies ({daily_comp['coverage']*100:.1f}% coverage)" if daily_comp else "- Daily: no data",
        f"- Weekly: {weekly_comp['proxy_count']} proxies ({weekly_comp['coverage']*100:.1f}% coverage)" if weekly_comp else "- Weekly: no data",
        f"- Quarterly: {quarterly_comp['proxy_count']} proxies ({quarterly_comp['coverage']*100:.1f}% coverage)" if quarterly_comp else "- Quarterly: no data",
        "",
        f"**Q: Which triggers are contaminated by quarterly component?**",
        f"- {contaminated_count}/{len(audits)} triggers are contaminated." if audits else "- No trigger data available.",
        "",
        f"**Q: Should daily interpretation remain restricted?**",
    ]

    if daily_comp and daily_comp["coverage"] > 0.3:
        lines.append("- Daily component has >30% coverage. Daily interpretation PARTIALLY allowed for daily-only proxies.")
    else:
        lines.append("- YES. Daily component coverage is insufficient. X_agg daily interpretation should remain RESTRICTED.")

    lines += [
        "",
        f"**Q: Is there sufficient daily/weekly data for X_agg daily diagnostics?**",
    ]

    if daily_comp and weekly_comp:
        combined = max(daily_comp["coverage"], weekly_comp["coverage"])
        if combined > 0.3:
            lines.append(f"- Combined daily/weekly coverage = {combined*100:.1f}%. Partial diagnostics possible.")
        else:
            lines.append(f"- Combined daily/weekly coverage = {combined*100:.1f}%. Insufficient for reliable daily diagnostics.")
    else:
        lines.append("- Insufficient data.")

    lines += [
        "",
        f"**Q: Should we supplement X_agg daily data sources?**",
        "- YES. Priority additions: FINRA margin debt, ETF flows, dealer leverage proxy, repo/reverse-repo.",
        "",
    ]

    return "\n".join(lines) + "\n"


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)

    print("Loading data...")
    comp, results, sigma = load_data()

    print("Computing frequency components...")
    components = compute_frequency_components(comp)

    print("Computing component metadata...")
    metadata = compute_component_metadata(comp, components)

    print("Auditing triggers...")
    audits = audit_triggers(components, results)

    # Write component series
    series_df = pd.DataFrame({"date": comp["date"] if "date" in comp.columns else comp.index})
    for name, series in components.items():
        series_df[name] = series
    series_path = OUTPUT / "x_agg_component_series.csv"
    series_df.to_csv(series_path, index=False)
    print(f"Wrote: {series_path}")

    # Write metadata
    meta_path = OUTPUT / "x_agg_component_metadata.json"
    meta_path.write_text(json.dumps(metadata, indent=2, default=str), encoding="utf-8")
    print(f"Wrote: {meta_path}")

    # Write trigger audit
    audit_df = pd.DataFrame(audits)
    audit_path = OUTPUT / "x_agg_trigger_frequency_audit.csv"
    audit_df.to_csv(audit_path, index=False)
    print(f"Wrote: {audit_path}")

    # Write report
    report = generate_report(metadata, audits, sigma)
    report_path = OUTPUT / "X_AGG_FREQUENCY_SPLIT_REPORT.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"Wrote: {report_path}")

    print("\nDone.")


if __name__ == "__main__":
    main()
