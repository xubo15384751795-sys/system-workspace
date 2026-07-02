#!/usr/bin/env python3
"""Bridge structural replay output into Output/current/.

When the Deformation run is stale or missing, this script promotes the
latest replay sigma_vector.json into a proper framework_output.json
and generates the 00_READ_ME_FIRST.md with explicit status.

v2 (2026-06-02): Added channel confidence layer, quality_status,
K interpretation hardening, X_agg validation.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

from _workspace_imports import add_scripts, add_workbench_src

add_scripts()
add_workbench_src()

from _runtime_io import ROOT, current_dir, ensure_dir

from workbench.current_bridge.reports import (
    generate_daily_market_space,
    generate_k_rebuild_plan,
    generate_md_classifier_report,
    generate_rebase_report,
    generate_summary,
    generate_x_rebuild_plan,
)
from workbench.governance.semantic import (
    MEASUREMENT_ELIGIBILITY,
    SemanticRegistry,
    build_primary_readout,
)

CURRENT = current_dir()
REPLAY_DIR = ROOT / "Output" / "sandbox" / "structural_replay_v2"
HARVESTER_LATEST = ROOT / "Data" / "harvester" / "exports" / "latest"
REBASE_DIR = ROOT / "Output" / "rebase"
DAILY_MARKET_SPACE_DIR = ROOT / "Output" / "daily_market_space"
SEMANTIC_REGISTRY_PATH = ROOT / "governance" / "semantic_registry.json"

# Proxy metadata for confidence assessment
CHANNEL_META = {
    "M": {
        "canonical_section": "§4.2 + §7.2.4",
        "data_sources": "FRED (NFCI, SOFR, DFF, IORB, BAA10YM, etc.)",
        "proxy_count": 6,
        "voting_proxies": 4,
        "family": "FRED_RATES",
        "expected_freq": "daily",
        "semantic_distance": 1,
    },
    "D": {
        "canonical_section": "§4.3 + §7.2.1",
        "data_sources": "FRED (DCPF3M, SOFR, IORB, DPRIME) + H41",
        "proxy_count": 6,
        "voting_proxies": 4,
        "family": "FRED_FUNDING",
        "expected_freq": "daily",
        "semantic_distance": 1,
    },
    "K": {
        "canonical_section": "§4.4 + §7.2.2",
        "data_sources": "CBOE (VIX9D, VIX3M, VIX6M, SKEW, VVIX) + FRED credit surface",
        "proxy_count": 10,
        "voting_proxies": 5,
        "family": "CBOE_OPTIONS+FRED_CREDIT",
        "expected_freq": "daily",
        "semantic_distance": 2,
    },
    "X_agg": {
        "canonical_section": "§4.5 + §7.2.3",
        "data_sources": "SEC (OBS_DERIV_TO_ASSETS) + OFR (FSI)",
        "proxy_count": 3,
        "voting_proxies": 2,
        "family": "SEC_OBS + OFR_SYSTEMIC",
        "expected_freq": "quarterly+daily",
        "semantic_distance": 3,
    },
}


def _load_sigma_vector() -> dict:
    sv_path = REPLAY_DIR / "sigma_vector.json"
    if not sv_path.exists():
        return {}
    return json.loads(sv_path.read_text(encoding="utf-8"))


def _load_replay_results() -> list:
    results_path = REPLAY_DIR / "results.json"
    if not results_path.exists():
        return []
    return json.loads(results_path.read_text(encoding="utf-8"))


def _load_semantic_registry() -> SemanticRegistry | None:
    if not SEMANTIC_REGISTRY_PATH.exists():
        return None
    return SemanticRegistry(SEMANTIC_REGISTRY_PATH)


def _channel_coverage(sv: dict) -> dict:
    vector = sv.get("sigma_vector", {})
    live = vector.get("channels_live", [])
    not_impl = vector.get("channels_not_implemented", [])
    total = len(live) + len(not_impl)
    return {
        "channels_live": live,
        "channels_not_implemented": not_impl,
        "total_canonical": total,
        "coverage_ratio": f"{len(live)}/{total}",
        "complete": vector.get("complete", False),
    }


def _build_channel_contributors() -> dict[str, list[dict]]:
    """Extract per-channel proxy contributors with actual z-scores.

    Reads proxy_registry.json for metadata and proxy_components.parquet
    for the latest z-score values. Returns a dict mapping each channel
    to a sorted list of contributor dicts.
    """
    registry_path = REPLAY_DIR / "proxy_registry.json"
    components_path = REPLAY_DIR / "proxy_components.parquet"
    if not registry_path.exists() or not components_path.exists():
        return {}

    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        import pandas as pd
        components = pd.read_parquet(components_path)
    except Exception:
        logger.warning("Failed to load sigma components from %s", components_path, exc_info=True)
        return {}

    # Get latest row of z-scores
    if components.empty:
        return {}
    latest = components.iloc[-1]

    # Build per-channel contributor lists
    channels: dict[str, list[dict]] = {}
    HARVESTER_PREFIXES = ("FRED:", "SEC:", "OFR:", "TREASURY:", "CBOE:", "DERIVED:")

    # Normalize channel keys: proxy_registry uses internal names (e.g.
    # "D_contraction") while framework_output uses canonical names ("D").
    _CHANNEL_ALIAS = {
        "D_contraction": "D",
        "X_PRE": "X_PRE",
        "X_REALIZED": "X_REALIZED",
    }

    for proxy in registry:
        ch = proxy.get("channel") or proxy.get("target_variable", "")
        ch = _CHANNEL_ALIAS.get(ch, ch)
        name = proxy.get("name", "")
        if not ch or not name:
            continue

        z_score = latest.get(name)
        if pd.isna(z_score):
            z_score = None
        else:
            z_score = round(float(z_score), 4)

        raw_series = proxy.get("raw_series", [])
        harvester_sourced = any(
            s.startswith(HARVESTER_PREFIXES) for s in raw_series
        ) if raw_series else False

        contributor = {
            "proxy_name": name,
            "raw_series": raw_series,
            "z_score": z_score,
            "direction": ("positive" if z_score and z_score > 0 else "negative" if z_score and z_score < 0 else "neutral"),
            "tier": proxy.get("tier", "unknown"),
            "canonical_status": proxy.get("canonical_status", "unknown"),
            "proxy_status": proxy.get("proxy_status", "unknown"),
            "harvester_sourced": harvester_sourced,
            "mechanism": proxy.get("mechanism", ""),
        }
        channels.setdefault(ch, []).append(contributor)

    # Sort each channel by absolute z-score descending (None last)
    for ch in channels:
        channels[ch].sort(
            key=lambda c: abs(c["z_score"]) if c["z_score"] is not None else 0,
            reverse=True,
        )

    return channels


def _build_channel_confidence(sv: dict, results: list) -> dict:
    """Per-channel confidence assessment."""
    vector = sv.get("sigma_vector", {})
    warnings = vector.get("semantic_warning", [])
    semantic = _load_semantic_registry()
    all_contributors = _build_channel_contributors()

    confidence = {}
    for ch in ["M", "D", "K", "X_agg"]:
        meta = CHANNEL_META.get(ch, {})
        semantic_meta = {}
        if semantic is not None:
            try:
                semantic_meta = semantic.get(ch)
            except KeyError:
                semantic_meta = {}
        val = vector.get(ch)
        is_live = val is not None
        distance = semantic_meta.get("semantic_distance", meta.get("semantic_distance"))
        proxy_status = semantic_meta.get("proxy_status")

        # Determine confidence level
        if not is_live:
            level = "not_implemented"
        elif distance is not None and distance >= 3:
            level = "low"  # PROXY_REDUCED
        elif distance is not None and distance >= 2:
            level = "medium"  # multi-family but reduced
        else:
            level = "high"

        # Check if channel has warnings
        ch_warnings = [w for w in warnings if w.startswith(f"{ch}:") and "PARTIAL" not in w]
        readout_role = MEASUREMENT_ELIGIBILITY[ch]["readout_role"]

        confidence[ch] = {
            "status": "live" if is_live else "not_implemented",
            "confidence": level,
            "value": val,
            "framework_role": MEASUREMENT_ELIGIBILITY[ch]["framework_role"],
            "readout_role": readout_role,
            "current_status": MEASUREMENT_ELIGIBILITY[ch]["current_status"],
            "readout_reason": MEASUREMENT_ELIGIBILITY[ch]["reason"],
            "proxy_quality": proxy_status or ("PROXY_REDUCED" if distance is not None and distance >= 3 else "CANONICAL"),
            "data_frequency": meta.get("expected_freq", "unknown"),
            "family_diversity": "monoculture" if "+" not in meta.get("family", "") else "multi-family",
            "family": meta.get("family", "unknown"),
            "voting_proxies": meta.get("voting_proxies", 0),
            "semantic_distance": distance,
            "canonical_section": meta.get("canonical_section", ""),
            "warnings": ch_warnings,
            "valid_for": semantic_meta.get("valid_for", []),
            "not_valid_for": semantic_meta.get("not_valid_for", []),
            "allowed_in_canonical_voting": is_live and readout_role == "primary_readout",
            "contributors": all_contributors.get(ch, []),
        }

    return confidence


def _quality_status(coverage: dict, channel_confidence: dict) -> str:
    """Distinguish ACTIVE_FULL sub-states."""
    if not coverage["complete"]:
        return "PARTIAL"

    levels = [ch["confidence"] for ch in channel_confidence.values() if ch["status"] == "live"]
    all_warnings = []
    for ch in channel_confidence.values():
        all_warnings.extend(ch.get("warnings", []))

    if all(level == "high" for level in levels):
        return "FULL_HIGH_CONFIDENCE"
    if all(level == "low" for level in levels):
        return "FULL_PROXY_REDUCED"
    if all(ch.get("proxy_quality") == "PROXY_REDUCED" for ch in channel_confidence.values() if ch["status"] == "live"):
        return "FULL_PROXY_REDUCED"
    if all_warnings:
        return "FULL_WITH_WARNINGS"
    return "FULL_PROXY_REDUCED"


def _operational_status(coverage: dict) -> str:
    """Layer 1: Is the system running?"""
    live = len(coverage["channels_live"])
    if live == 0:
        return "STOPPED"
    if live < coverage["total_canonical"]:
        return "DEGRADED"
    return "RUNNING"


def _coverage_status_layer(coverage: dict) -> str:
    """Layer 2: How many channels have data?"""
    live = len(coverage["channels_live"])
    total = coverage["total_canonical"]
    if total == 0:
        return "NO_COVERAGE"
    if live == total:
        return f"FULL_COVERAGE {live}/{total}"
    return f"PARTIAL_COVERAGE {live}/{total}"


def _measurement_quality_layer(channel_confidence: dict) -> str:
    """Layer 3: How可信 are the channels?"""
    levels = [ch["confidence"] for ch in channel_confidence.values() if ch["status"] == "live"]
    if not levels:
        return "NOT_COMPUTED"
    if all(level == "high" for level in levels):
        return "HIGH_CONFIDENCE"
    if all(level == "medium" for level in levels):
        return "MEDIUM_CONFIDENCE"
    if all(level == "low" for level in levels):
        return "LOW_CONFIDENCE_PROXY_REDUCED"
    # Mixed
    low_count = sum(1 for level in levels if level == "low")
    if low_count > len(levels) / 2:
        return "LOW_CONFIDENCE_PROXY_REDUCED"
    return "MIXED_CONFIDENCE"


def _validity_scope(channel_confidence: dict) -> dict:
    """Determine what this system can and cannot claim."""
    all_distance_3 = all(
        ch.get("semantic_distance", 0) >= 3
        for ch in channel_confidence.values()
        if ch["status"] == "live"
    )
    all_proxy_reduced = all(
        ch.get("proxy_quality") == "PROXY_REDUCED"
        for ch in channel_confidence.values()
        if ch["status"] == "live"
    )

    if all_distance_3 and all_proxy_reduced:
        return {
            "scope": "PARTIAL_STRUCTURAL_STRESS_DIAGNOSTIC",
            "valid_for": ["M/D primary market-space readout", "partial morphology stress warning", "structural trend observation"],
            "not_valid_for": [
                "Not valid for: complete market morphology state",
                "Not valid for: trading signals",
                "Not valid for: directional conviction claims",
                "Not valid for: primary executive state from K/X_agg",
                "Not valid for: primary executive state from cofire_count or dominant_channel",
            ],
            "disclaimer": "本系统当前只适合作为代理型结构压力诊断，不适合作为完整市场形态判断。",
        }
    return {
        "scope": "STRUCTURAL_DIAGNOSTIC",
        "valid_for": ["M/D primary market-space readout", "structural stress diagnosis", "regime observation"],
        "not_valid_for": ["Not valid for: trading signals", "Not valid for: primary executive state from K/X_agg until measurement gates pass"],
        "disclaimer": "System provides structural diagnostics, not trading signals.",
    }


def _k_interpretation(vector: dict, results: list) -> dict:
    """K interpretation hardening: what does dominant=K mean?"""
    k_val = vector.get("K")
    if k_val is None:
        return {"status": "not_implemented"}

    # Determine if K is compression or stress
    # K > 0: vol surface is distorted (stress)
    # K < 0: vol surface is compressed (low-vol complacency)
    is_stress = k_val > 0
    abs_k = abs(k_val)

    # Get K proxy contributions from latest event
    k_contributions = {}
    if results:
        latest = results[-1]
        cap = latest.get("channel_at_peak", {})
        # K value at peak
        k_at_peak = cap.get("K", 0)
        k_contributions["value_at_latest_event"] = k_at_peak
        k_contributions["event"] = latest.get("event_id", "unknown")

    return {
        "status": "live",
        "value": k_val,
        "absolute_deviation": abs_k,
        "is_dominant": vector.get("dominant_channel") == "K",
        "interpretation": "high_vol_stress" if is_stress else "low_vol_compression",
        "interpretation_detail": (
            f"K = {k_val:.3f}: IV surface is {'distorted (stress)' if is_stress else 'compressed (low-vol complacency)'}. "
            f"Absolute deviation = {abs_k:.3f}."
        ),
        "proxy_sources": "VIX9D/3M/6M butterfly (iv_distortion) + SKEW (tail_convexity) + VVIX (vol_of_vol)",
        "contributions": k_contributions,
    }


def _x_agg_validation(vector: dict, results: list) -> dict:
    """X_agg validation: is it real signal or coverage filler?"""
    x_val = vector.get("X_agg")
    if x_val is None:
        return {"status": "not_implemented"}

    # Check X_agg contribution across events
    x_agg_events = []
    for ev in results:
        cap = ev.get("channel_at_peak", {})
        x_at_peak = cap.get("X_agg", 0) or 0
        if abs(x_at_peak) > 0.01:
            x_agg_events.append({
                "event": ev.get("event_id"),
                "x_agg": x_at_peak,
                "is_dominant": abs(x_at_peak) > max(
                    abs(cap.get("M", 0) or 0),
                    abs(cap.get("D_contraction", 0) or 0),
                    abs(cap.get("K", 0) or 0),
                ),
            })

    # Correlation with other channels (simplified)
    [ev.get("channel_at_peak", {}).get("M", 0) or 0 for ev in results]
    [ev.get("channel_at_peak", {}).get("X_agg", 0) or 0 for ev in results]

    # Check if X_agg fires in key crisis events
    crisis_events = {"gfc_2008", "covid_2020", "svb_2023"}
    crisis_coverage = {}
    for ev in results:
        eid = ev.get("event_id", "")
        if eid in crisis_events:
            cap = ev.get("channel_at_peak", {})
            crisis_coverage[eid] = {
                "x_agg": cap.get("X_agg", 0) or 0,
                "contributes": abs(cap.get("X_agg", 0) or 0) > 0.01,
            }

    return {
        "status": "live",
        "value": x_val,
        "events_with_contribution": len(x_agg_events),
        "events_where_dominant": sum(1 for e in x_agg_events if e["is_dominant"]),
        "crisis_coverage": crisis_coverage,
        "is_coverage_filler": len(x_agg_events) < 3,
        "data_sources": "SEC:OBS_DERIV_TO_ASSETS (quarterly) + OFR_FSI (daily)",
        "frequency_note": "Quarterly SEC data resampled to daily via _freq_aware_zscore",
    }


def _overall_status(coverage: dict) -> str:
    live = len(coverage["channels_live"])
    total = coverage["total_canonical"]
    if total == 0:
        return "MISSING_OUTPUT"
    if live == total:
        return "ACTIVE_FULL"
    if live >= 2:
        return "ACTIVE_PARTIAL"
    if live >= 1:
        return "DEGRADED_PARTIAL"
    return "DEGRADED"


def _dominant_pressure(sv: dict) -> tuple[str, str]:
    vector = sv.get("sigma_vector", {})
    dominant = vector.get("dominant_channel")
    if not dominant or dominant == "NONE":
        return "no active pressure channel", "none"
    cofire = vector.get("cofire_count", 0)
    return dominant, f"cofire={cofire}"


def _readout_policy_text() -> str:
    return (
        "Framework remains canonical M/D/K/X_agg. Daily executive state is "
        "measurement-eligible M/D primary; K is diagnostic/rebuild, X_agg is "
        "background-only with daily trigger disabled."
    )


def build_framework_output() -> dict:
    sv = _load_sigma_vector()
    results = _load_replay_results()
    coverage = _channel_coverage(sv)
    overall = _overall_status(coverage)
    dominant, confidence_str = _dominant_pressure(sv)
    vector = sv.get("sigma_vector", {})
    primary_readout = vector.get("primary_readout") or build_primary_readout(vector)
    measurement_eligibility = vector.get("measurement_eligibility") or MEASUREMENT_ELIGIBILITY
    channel_confidence = _build_channel_confidence(sv, results)
    quality = _quality_status(coverage, channel_confidence)
    k_interp = _k_interpretation(vector, results)
    x_agg_val = _x_agg_validation(vector, results)

    # 3-layer status
    operational = _operational_status(coverage)
    coverage_layer = _coverage_status_layer(coverage)
    measurement_quality = _measurement_quality_layer(channel_confidence)
    validity = _validity_scope(channel_confidence)

    # Check harvester freshness
    harvester_release = "unknown"
    if HARVESTER_LATEST.exists():
        catalog_path = HARVESTER_LATEST / "catalog.json"
        if catalog_path.exists():
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
            harvester_release = catalog.get("release_id", str(HARVESTER_LATEST.resolve().name))

    now = datetime.now(UTC).isoformat()

    return {
        "schema_version": "workbench.framework_output.v3",
        "framework_id": "structural_deformation",
        "framework_version": "0.3.0",
        "run_id": f"replay_bridge_{now[:10]}",
        "as_of": now,
        "status": "partial" if overall == "ACTIVE_PARTIAL" else overall.lower(),
        "basic": {
            "overall": overall,
            "quality_status": quality,
            "main_pressure": primary_readout.get("state", "PRIMARY_READOUT_UNAVAILABLE"),
            "confidence": "M/D primary; " + confidence_str + " legacy diagnostic",
            "summary": (
                f"Structural framework {overall} ({quality}). "
                f"Canonical channels live: {', '.join(coverage['channels_live'])}. "
                f"Primary daily readout: {primary_readout.get('state', 'PRIMARY_READOUT_UNAVAILABLE')} "
                f"from M/D. Legacy dominant/cofire are diagnostic only: {dominant}, {confidence_str}. "
                f"K/X remain canonical but measurement-limited."
            ),
            "primary_market_space": primary_readout.get("state", "PRIMARY_READOUT_UNAVAILABLE"),
            "daily_readout_policy": _readout_policy_text(),
            "legacy_diagnostic_pressure": dominant,
            "legacy_diagnostic_confidence": confidence_str,
            # 3-layer status (new)
            "operational_status": operational,
            "coverage_status": coverage_layer,
            "measurement_quality": measurement_quality,
            "validity_scope": validity["scope"],
            "valid_for": validity["valid_for"],
            "not_valid_for": validity["not_valid_for"],
            "disclaimer": validity["disclaimer"],
        },
        "advanced": {
            "sigma_vector": vector,
            "channel_coverage": coverage,
            "channel_confidence": channel_confidence,
            "measurement_eligibility": measurement_eligibility,
            "primary_readout": primary_readout,
            "quality_status": quality,
            "measurement_blind_spot": not coverage["complete"],
            "coverage_ratio": coverage["coverage_ratio"],
            "harvester_release": harvester_release,
            "semantic_warnings": vector.get("semantic_warning", []),
            "k_interpretation": k_interp,
            "x_agg_validation": x_agg_val,
        },
        "artifacts": {
            "sigma_vector_json": str(REPLAY_DIR / "sigma_vector.json"),
            "replay_results": str(REPLAY_DIR / "results.json"),
            "evaluation_report": str(REPLAY_DIR / "evaluation_report.md"),
            "measurement_eligibility": str(REBASE_DIR / "measurement_eligibility.json"),
            "rebase_report": str(REBASE_DIR / "DEFORMATION_CORE_REBASE_REPORT.md"),
            "daily_market_space": str(DAILY_MARKET_SPACE_DIR / "latest.md"),
        },
        "evidence_links": [
            str(REPLAY_DIR / "evaluation_report.md"),
            str(REPLAY_DIR / "sigma_vector.json"),
        ],
        "next_actions": _next_actions(coverage, quality),
    }


def _next_actions(coverage: dict, quality: str) -> list[str]:
    actions = []
    if quality == "FULL_PROXY_REDUCED":
        actions.append("All channels are PROXY_REDUCED (semantic_distance=3). Improve proxy quality to reduce semantic distance.")
    if quality == "FULL_WITH_WARNINGS":
        actions.append("Review governance warnings in channel_confidence.")
    not_impl = coverage["channels_not_implemented"]
    actions.append("Use M/D as the current primary daily market-space readout.")
    actions.append("Not valid for: cofire_count and dominant_channel are legacy diagnostics, not primary executive state.")
    if "K" in not_impl:
        actions.append("K channel: connect vol surface + realized vol/jump + cross-asset curvature data before primary reactivation.")
    else:
        actions.append("K channel: keep diagnostic/rebuild until measurement gate proves unique curvature increment.")
    if "X_agg" in not_impl:
        actions.append("X_agg channel: connect official support/liquidity shadow/leverage-flow data before reactivation.")
    else:
        actions.append("X_agg channel: keep background-only; daily trigger remains disabled until discrimination retest passes.")
    actions.append("Review X_agg frequency mismatch (quarterly vs weekly) before any daily interpretation.")
    return actions


def write_readme(fw_output: dict) -> str:
    basic = fw_output["basic"]
    advanced = fw_output["advanced"]
    coverage = advanced["channel_coverage"]
    channel_conf = advanced.get("channel_confidence", {})
    primary_readout = advanced.get("primary_readout", {})
    eligibility = advanced.get("measurement_eligibility", {})
    k_interp = advanced.get("k_interpretation", {})
    x_agg_val = advanced.get("x_agg_validation", {})

    lines = [
        "# Current Risk Check",
        "",
        "## deformation-framework",
        "",
        "### Status (3-Layer)",
        f"- **Operational Status:** {basic.get('operational_status', 'UNKNOWN')}",
        f"- **Coverage Status:** {basic.get('coverage_status', 'UNKNOWN')}",
        f"- **Measurement Quality:** {basic.get('measurement_quality', 'UNKNOWN')}",
        f"- **Validity Scope:** {basic.get('validity_scope', 'UNKNOWN')}",
        "",
        "### Validity",
        f"- **Valid for:** {', '.join(basic.get('valid_for', []))}",
        f"- **NOT valid for:** {', '.join(basic.get('not_valid_for', []))}",
        f"- **Disclaimer:** {basic.get('disclaimer', '')}",
        "",
        "### Daily Executive Readout",
        f"- **Primary Market Space:** {primary_readout.get('state', 'PRIMARY_READOUT_UNAVAILABLE')}",
        f"- **Primary channels:** {', '.join(primary_readout.get('eligible_channels', ['M', 'D']))}",
        f"- **Policy:** {basic.get('daily_readout_policy', _readout_policy_text())}",
        f"- **K role:** {eligibility.get('K', {}).get('current_status', 'THEORY_RETAINED_MEASUREMENT_INCOMPLETE')}",
        f"- **X_agg role:** {eligibility.get('X_agg', {}).get('current_status', 'BACKGROUND_ONLY_REBUILD_REQUIRED')}",
        "",
        "### Basic Check",
        f"- Overall (legacy): **{basic['overall']}**",
        f"- Quality: **{basic['quality_status']}**",
        f"- Main pressure: {basic['main_pressure']}",
        f"- Confidence: {basic['confidence']}",
        f"- Summary: {basic['summary']}",
        "",
        "### Channel Coverage",
        f"- Live channels: {', '.join(coverage['channels_live'])}",
        f"- NOT_IMPLEMENTED: {', '.join(coverage['channels_not_implemented']) or 'none'}",
        f"- Coverage ratio: {coverage['coverage_ratio']}",
        f"- Measurement blind spot: {'YES' if advanced.get('measurement_blind_spot') else 'NO'}",
        "",
        "### Channel Confidence",
        "",
        "| Channel | Status | Readout Role | Confidence | Proxy Quality | Family | Semantic Distance |",
        "|---------|--------|--------------|------------|---------------|--------|-------------------|",
    ]
    for ch in ["M", "D", "K", "X_agg"]:
        cc = channel_conf.get(ch, {})
        lines.append(
            f"| {ch} | {cc.get('status', '?')} | {cc.get('readout_role', '?')} | "
            f"{cc.get('confidence', '?')} | "
            f"{cc.get('proxy_quality', '?')} | {cc.get('family', '?')} | "
            f"{cc.get('semantic_distance', '?')} |"
        )
    lines.append("")

    sv = advanced.get("sigma_vector", {})
    if sv:
        lines.extend([
            "### SigmaVector",
            f"- M: {sv.get('M')}",
            f"- D: {sv.get('D')}",
            f"- K: {sv.get('K')}",
            f"- X_agg: {sv.get('X_agg')}",
            f"- Dominant: {sv.get('dominant_channel')} (legacy diagnostic only)",
            f"- Cofire count: {sv.get('cofire_count')} (legacy diagnostic only)",
            "",
        ])

    # K interpretation
    if k_interp.get("status") == "live":
        lines.extend([
            "### K Interpretation",
            f"- Value: {k_interp.get('value', 'n/a')}",
            f"- Interpretation: {k_interp.get('interpretation', 'n/a')}",
            f"- Detail: {k_interp.get('interpretation_detail', 'n/a')}",
            f"- Is dominant: {k_interp.get('is_dominant', False)}",
            f"- Sources: {k_interp.get('proxy_sources', 'n/a')}",
            "",
        ])

    # X_agg validation
    if x_agg_val.get("status") == "live":
        lines.extend([
            "### X_agg Validation",
            f"- Value: {x_agg_val.get('value', 'n/a')}",
            f"- Events with contribution: {x_agg_val.get('events_with_contribution', 0)}",
            f"- Events where dominant: {x_agg_val.get('events_where_dominant', 0)}",
            f"- Coverage filler: {'YES' if x_agg_val.get('is_coverage_filler') else 'NO'}",
            f"- Crisis coverage: {json.dumps(x_agg_val.get('crisis_coverage', {}), default=str)}",
            "",
        ])

    warnings = advanced.get("semantic_warnings", [])
    if warnings:
        lines.extend(["### Warnings"])
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")

    lines.extend([
        "### Data Recency",
        "- Output source: structural_replay_v2 bridge (canonical)",
        f"- Harvester release: {advanced.get('harvester_release', 'unknown')}",
        f"- Generated at: {fw_output['as_of']}",
        "",
        "## What To Inspect Next",
    ])
    for i, action in enumerate(fw_output.get("next_actions", []), 1):
        lines.append(f"{i}. {action}")
    lines.extend([
        "",
        "## Open",
        f"- Sigma vector: `{fw_output['artifacts']['sigma_vector_json']}`",
        f"- Replay results: `{fw_output['artifacts']['replay_results']}`",
        f"- Evaluation report: `{fw_output['artifacts']['evaluation_report']}`",
        "",
        "## Deeper Commands",
        "- Basic check: `./sys check`",
        "- Evidence: `./sys evidence`",
        "- Full report: `./sys open`",
    ])
    return "\n".join(lines) + "\n"


def write_rebase_outputs(fw_output: dict) -> dict[str, Path]:
    ensure_dir(REBASE_DIR)
    ensure_dir(DAILY_MARKET_SPACE_DIR)

    paths = {
        "measurement_eligibility": REBASE_DIR / "measurement_eligibility.json",
        "deformation_core_rebase": REBASE_DIR / "DEFORMATION_CORE_REBASE_REPORT.md",
        "framework_compatible_rebase": REBASE_DIR / "FRAMEWORK_COMPATIBLE_READOUT_REBASE_REPORT.md",
        "md_classifier": REBASE_DIR / "MD_PRIMARY_SPACE_CLASSIFIER_REPORT.md",
        "k_rebuild": REBASE_DIR / "K_REBUILD_PLAN.md",
        "x_rebuild": REBASE_DIR / "X_REBUILD_PLAN.md",
        "daily_market_space": DAILY_MARKET_SPACE_DIR / "latest.md",
        "daily_market_space_alias": DAILY_MARKET_SPACE_DIR / "daily_market_space_latest.md",
    }

    paths["measurement_eligibility"].write_text(
        json.dumps(fw_output["advanced"].get("measurement_eligibility", MEASUREMENT_ELIGIBILITY), indent=2),
        encoding="utf-8",
    )
    rebase_report = generate_rebase_report(fw_output)
    paths["deformation_core_rebase"].write_text(rebase_report, encoding="utf-8")
    paths["framework_compatible_rebase"].write_text(rebase_report, encoding="utf-8")
    paths["md_classifier"].write_text(generate_md_classifier_report(fw_output), encoding="utf-8")
    paths["k_rebuild"].write_text(generate_k_rebuild_plan(fw_output), encoding="utf-8")
    paths["x_rebuild"].write_text(generate_x_rebuild_plan(fw_output), encoding="utf-8")
    daily = generate_daily_market_space(fw_output)
    paths["daily_market_space"].write_text(daily, encoding="utf-8")
    paths["daily_market_space_alias"].write_text(daily, encoding="utf-8")
    return paths


def main() -> None:
    ensure_dir(CURRENT)

    sv = _load_sigma_vector()
    if not sv:
        print("ERROR: No sigma_vector.json found in replay output.")
        print("Run structural replay first: python3 scripts/structural_replay_v2.py")
        sys.exit(1)

    fw_output = build_framework_output()

    # Write framework_output.json
    fw_path = CURRENT / "framework_output.json"
    fw_path.write_text(json.dumps(fw_output, indent=2, default=str), encoding="utf-8")
    print(f"Wrote: {fw_path}")

    # Note: 00_READ_ME_FIRST.md is now written by build_readme_first.py
    # after system index is built

    # Write latest_summary.md
    summary = generate_summary(fw_output)
    summary_path = CURRENT / "latest_summary.md"
    summary_path.write_text(summary, encoding="utf-8")
    print(f"Wrote: {summary_path}")

    model_run_path = CURRENT / "model_run.json"
    replay_results = REPLAY_DIR / "results.json"
    run_id = f"replay_{fw_output.get('as_of', datetime.now(UTC).strftime('%Y-%m-%d'))}"
    if replay_results.exists():
        try:
            replay_meta = json.loads(replay_results.read_text(encoding="utf-8"))
            run_id = str(replay_meta.get("run_id") or replay_meta.get("tag") or run_id)
        except Exception:
            logger.debug("Failed to read replay results.json for model_run", exc_info=True)
    as_of = str(fw_output.get("as_of") or datetime.now(UTC).strftime("%Y-%m-%d"))
    model_run_path.write_text(
        json.dumps(
            {
                "schema_version": "workbench.model_run.v1",
                "model_id": "structural_replay_v2",
                "producer": "scripts/bridge_replay_to_current.py",
                "run_id": run_id,
                "run_date": as_of[:10],
                "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "status": "success",
                "input_bundle": as_of[:10].replace("-", ""),
                "artifacts": {
                    "framework_output": {
                        "path": "framework_output.json",
                        "kind": "json",
                        "description": "Bridged framework readout from structural replay.",
                    },
                    "latest_summary": {
                        "path": "latest_summary.md",
                        "kind": "markdown",
                        "description": "Human-readable replay summary.",
                    },
                },
                "framework_payload": {
                    "source": "structural_replay_v2",
                    "framework_status": fw_output.get("status"),
                    "quality_status": fw_output.get("basic", {}).get("quality_status"),
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Wrote: {model_run_path}")

    # Write readout-rebase artifacts
    rebase_paths = write_rebase_outputs(fw_output)
    for path in rebase_paths.values():
        print(f"Wrote: {path}")

    # Print status
    print()
    print(f"Status: {fw_output['basic']['overall']}")
    print(f"Quality: {fw_output['basic']['quality_status']}")
    print(f"Coverage: {fw_output['advanced']['coverage_ratio']}")
    print(f"Primary readout: {fw_output['advanced']['primary_readout'].get('state')}")


if __name__ == "__main__":
    main()
