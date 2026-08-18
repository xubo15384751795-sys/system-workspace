"""Report generation functions — pure computation, no I/O.

Extracted from scripts/bridge_replay_to_current.py.
These functions take a framework_output dict and return markdown strings.
They do not read files, write files, or call external services.

Phase 1 of bridge_replay_to_current.py module split.
"""
from __future__ import annotations

from datetime import UTC, datetime


def fmt_value(value: object) -> str:
    """Format a numeric value to 3 decimal places, or 'n/a' if None."""
    try:
        if value is None:
            return "n/a"
        if isinstance(value, (int, float, str)):
            return f"{float(value):.3f}"
        return str(value)
    except (TypeError, ValueError):
        return str(value)


def generate_summary(fw_output: dict) -> str:
    """Generate a human-readable latest_summary.md."""
    basic = fw_output["basic"]
    adv = fw_output["advanced"]
    sv = adv.get("sigma_vector", {})
    primary_readout = adv.get("primary_readout", {})
    k_interp = adv.get("k_interpretation", {})

    lines = [
        f"# Structural Risk Run - {datetime.now(UTC).strftime('%Y-%m-%d')}",
        "",
        "## Status",
        f"- **Operational:** {basic.get('operational_status', 'UNKNOWN')}",
        f"- **Coverage:** {basic.get('coverage_status', 'UNKNOWN')}",
        f"- **Measurement Quality:** {basic.get('measurement_quality', 'UNKNOWN')}",
        f"- **Validity Scope:** {basic.get('validity_scope', 'UNKNOWN')}",
        "",
        "## Main Signal",
        f"- Morphology: {basic['overall']}",
        f"- Sigma: {sv.get('operator_penalty', 'n/a')}",
        f"- Singular regime: {'yes' if adv.get('measurement_blind_spot') else 'no'}",
        f"- Primary market space: {primary_readout.get('state', 'PRIMARY_READOUT_UNAVAILABLE')}",
        f"- Legacy leading channel: {sv.get('dominant_channel', 'N/A')} (diagnostic only)",
        "- Escalation: no",
        "",
        "## Interpretation",
        basic["summary"],
        "",
        "## M/D/K/X Snapshot",
    ]

    for ch in ["M", "D", "K", "X_agg"]:
        val = sv.get(ch)
        conf = adv.get("channel_confidence", {}).get(ch, {})
        interp = k_interp.get("interpretation", "") if ch == "K" else ""
        if val is not None:
            label = f" ({interp})" if interp else ""
            lines.append(f"- {ch}: {val:.3f} ({conf.get('confidence', '?')}){label}")
        else:
            lines.append(f"- {ch}: n/a")

    lines += [
        "",
        "## Data And Reproducibility",
        "- Data backend: harvester",
        f"- Harvester release: {adv.get('harvester_release', 'unknown')}",
        f"- Generated at: {fw_output['as_of']}",
        "",
        "## Caveats",
        "- This package summarizes the persisted structural snapshot and available diagnostics.",
        "- Daily executive state is M/D primary; K and X_agg are retained canonical dimensions but measurement-limited today.",
        "- cofire_count and dominant_channel are legacy diagnostics, not the primary daily state.",
        "- It is not a trading instruction.",
        "",
        "## Validity",
        f"- **Valid for:** {', '.join(basic.get('valid_for', []))}",
        f"- **NOT valid for:** {', '.join(basic.get('not_valid_for', []))}",
        f"- **Disclaimer:** {basic.get('disclaimer', '')}",
        "",
        "## Data Recency",
        f"- Quality status: {basic['quality_status']}",
        f"- Coverage: {adv.get('coverage_ratio', '?')}",
        f"- Measurement blind spot: {'YES' if adv.get('measurement_blind_spot') else 'NO'}",
    ]

    return "\n".join(lines) + "\n"


def generate_rebase_report(fw_output: dict) -> str:
    """Generate the Deformation Core Rebase Report."""
    adv = fw_output["advanced"]
    primary = adv.get("primary_readout", {})
    eligibility = adv.get("measurement_eligibility", {})
    sv = adv.get("sigma_vector", {})

    lines = [
        "# Deformation Core Rebase Report",
        "",
        f"Generated at: {fw_output['as_of']}",
        "",
        "## Decision",
        "",
        "Canonical framework space remains M / D / K / X_agg.",
        "Daily executive readout is rebased to measurement-eligible M/D primary.",
        "K and X_agg are not removed; they are retained as canonical but measurement-limited dimensions.",
        "",
        "## Primary Daily Readout",
        "",
        f"- Primary Market Space: {primary.get('state', 'PRIMARY_READOUT_UNAVAILABLE')}",
        f"- M anchor geometry: {fmt_value(sv.get('M'))}",
        f"- D path geometry: {fmt_value(sv.get('D'))}",
        "- K curvature geometry: diagnostic/rebuild only",
        "- X hidden geometry: background-only; daily trigger disabled",
        "",
        "## Measurement Eligibility",
        "",
        "| Channel | Framework Role | Readout Role | Current Status | Reason |",
        "|---|---|---|---|---|",
    ]
    for ch in ["M", "D", "K", "X_agg"]:
        e = eligibility.get(ch, {})
        lines.append(
            f"| {ch} | {e.get('framework_role', '')} | {e.get('readout_role', '')} | "
            f"{e.get('current_status', '')} | {e.get('reason', '')} |"
        )

    lines += [
        "",
        "## Governance Locks",
        "",
        "- Do not rewrite SigmaVector as two-dimensional.",
        "- Do not mark K/X_agg as removed from the framework.",
        "- Do not restore X_agg daily triggers.",
        "- Do not use cofire_count or dominant_channel as primary executive state.",
        "",
        "## Canonical Contract",
        "",
        "- SigmaVector retains M / D / K / X_agg.",
        "- dominant_channel and cofire_count remain legacy diagnostics over canonical live channels.",
        "- primary_readout is the daily decision layer and is computed from M/D only.",
    ]
    return "\n".join(lines) + "\n"


def generate_md_classifier_report(fw_output: dict) -> str:
    """Generate the M/D Primary Space Classifier Report."""
    primary = fw_output["advanced"].get("primary_readout", {})
    lines = [
        "# M/D Primary Space Classifier Report",
        "",
        f"Generated at: {fw_output['as_of']}",
        "",
        "## Current State",
        "",
        f"- State: {primary.get('state', 'PRIMARY_READOUT_UNAVAILABLE')}",
        f"- Basis: {primary.get('basis', '')}",
        f"- M: {fmt_value(primary.get('M_anchor_geometry', {}).get('value'))} "
        f"({primary.get('M_anchor_geometry', {}).get('status', 'unknown')})",
        f"- D: {fmt_value(primary.get('D_path_geometry', {}).get('value'))} "
        f"({primary.get('D_path_geometry', {}).get('status', 'unknown')})",
        "",
        "## Output States",
        "",
        "- ANCHOR_STABLE_PATH_OPEN",
        "- ANCHOR_DRIFT_PATH_OPEN",
        "- ANCHOR_STABLE_PATH_STRESS",
        "- ANCHOR_DRIFT_PATH_STRESS",
        "- POLICY_MARKET_GAP",
        "- FUNDING_PATH_NARROWING",
        "- CREDIT_PATH_STRESS",
        "- MIXED_ANCHOR_PATH_STRESS",
        "",
        "## Primitive Mapping",
        "",
        "- M_anchor_geometry maps to A_t anchor configuration, tau_t policy-market latency, and S_t actor interpretation when data are available.",
        "- D_path_geometry maps to L_t liquidation path feasibility, P_t positional constraint when data are available, and tau_t funding/clearing latency.",
    ]
    return "\n".join(lines) + "\n"


def generate_k_rebuild_plan(fw_output: dict) -> str:
    """Generate the K Rebuild Plan."""
    sv = fw_output["advanced"].get("sigma_vector", {})
    return "\n".join([
        "# K Rebuild Plan",
        "",
        f"Generated at: {fw_output['as_of']}",
        "",
        "## Current Status",
        "",
        "- Status: THEORY_RETAINED_MEASUREMENT_INCOMPLETE",
        f"- Current K value: {fmt_value(sv.get('K'))}",
        "- Current issue: proxy is too narrow and dominated by SKEW/VVIX-style option sentiment.",
        "- Daily role: diagnostic/rebuild only; no primary daily state authority.",
        "",
        "## Required Families",
        "",
        "- Implied vol surface: VIX, VVIX, SKEW, VIX term structure.",
        "- Realized transition: realized volatility, drawdown velocity, jump proxy, realized correlation.",
        "- Cross-asset curvature: SPY/TLT, HYG/TLT, SLV/GLD, UUP, rolling correlations, dispersion.",
        "- Rates volatility: MOVE-style rates vol and curve-stress terms when available.",
        "",
        "## Reactivation Gate",
        "",
        "K can re-enter primary daily readout only after the rebuilt measurement passes a utility/discrimination gate and shows unique curvature increment beyond M/D and vol-stress duplicates.",
    ]) + "\n"


def generate_x_rebuild_plan(fw_output: dict) -> str:
    """Generate the X Rebuild Plan."""
    sv = fw_output["advanced"].get("sigma_vector", {})
    return "\n".join([
        "# X Rebuild Plan",
        "",
        f"Generated at: {fw_output['as_of']}",
        "",
        "## Current Status",
        "",
        "- Status: BACKGROUND_ONLY_REBUILD_REQUIRED",
        f"- Current X_agg value: {fmt_value(sv.get('X_agg'))}",
        "- Current issue: OFR_FSI-style daily proxy overlaps VIX/vol stress and lacks hidden-geometry increment.",
        "- Daily role: background only; daily trigger disabled.",
        "",
        "## Required Families",
        "",
        "- Official support: Fed facilities, discount window, BTFP, reserve stress.",
        "- Liquidity shadow: RRP, TGA, money-market funds, repo and funding substitutions.",
        "- Leverage flow: margin debt, ETF flows, dealer positioning, prime-brokerage/dealer proxies where available.",
        "- Slow balance sheet: SEC OBS, quarterly balance sheet and maturity transformation indicators.",
        "",
        "## Reactivation Gate",
        "",
        "X_agg can re-enter primary daily/weekly readout only after new shadow-leverage data pass discrimination retest. Until then, X_agg daily trigger remains disabled.",
    ]) + "\n"


def generate_daily_market_space(fw_output: dict, readout_policy_text: str = "") -> str:
    """Generate the Daily Market Space report."""
    basic = fw_output["basic"]
    adv = fw_output["advanced"]
    primary = adv.get("primary_readout", {})
    channel_conf = adv.get("channel_confidence", {})

    lines = [
        f"# Daily Market Space - {fw_output['as_of'][:10]}",
        "",
        "## Primary Space",
        "",
        f"- State: {primary.get('state', 'PRIMARY_READOUT_UNAVAILABLE')}",
        "- Readout: M_anchor_geometry + D_path_geometry",
        f"- Policy: {basic.get('daily_readout_policy', readout_policy_text)}",
        "",
        "## Channel Roles",
        "",
        "| Channel | Value | Readout Role | Current Status |",
        "|---|---:|---|---|",
    ]
    for ch in ["M", "D", "K", "X_agg"]:
        cc = channel_conf.get(ch, {})
        lines.append(
            f"| {ch} | {fmt_value(cc.get('value'))} | {cc.get('readout_role', '?')} | "
            f"{cc.get('current_status', '?')} |"
        )

    lines += [
        "",
        "## Secondary Diagnostics",
        "",
        "- K: retained as curvature geometry, diagnostic/rebuild only.",
        "- X_agg: retained as hidden geometry, background-only; daily trigger disabled.",
        "- dominant_channel and cofire_count: diagnostic only, not the primary executive state.",
        "",
        "## Rebuild Queue",
        "",
        "- K: rebuild with vol surface, realized transition, cross-asset curvature and rates volatility.",
        "- X_agg: rebuild with official support, liquidity shadow, leverage flow and slow balance-sheet data.",
    ]
    return "\n".join(lines) + "\n"
