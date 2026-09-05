#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────────
# ARCHIVED_FALSIFIED — evidence-reproduction entrypoint only.
# The full historical replay logic is retained as evidence, but direct
# execution is denied before legacy theory dependencies are imported unless
# an explicit isolated-reproduction override is present.
# ─────────────────────────────────────────────────────────────────────────────
"""Structural Deformation System — M/D/K/X Measurement Engine v2.

ARCHIVE USE ONLY: reproduce historical crisis-window evidence in an isolated
location. This script is not part of the daily pipeline and has no authority
to publish current output, affect judgment, or promote artifacts.

Uses the official Harvester panel with 27 series across FRED, H41, SEC,
Treasury, and yfinance sources.  Builds M/D/K/X proxies from real
structural preset components rather than yfinance approximations.

Output:
  Output/sandbox/structural_replay_v2/
    evaluation_report.md
    event_windows/
    results.json
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from omegaconf import DictConfig, OmegaConf

REPO_ROOT = Path(__file__).resolve().parent.parent

# Deny ordinary execution before importing any archived framework dependency.
# This makes governance failure deterministic even when the legacy runtime is
# not installed or importable.
def _bootstrap_archive_imports() -> None:
    from scripts._deformation_archive_guard import prepend_archive_src, require_archived_reproduction  # noqa: I001

    if __name__ == "__main__":
        require_archived_reproduction()
    prepend_archive_src()


_bootstrap_archive_imports()

from replay.scoring import (  # noqa: E402
    compute_contract_violations,
    compute_derivative_contamination,
    compute_family_concentration,
    compute_horizon_consistency,
    compute_pc1_variance,
    compute_realized_activation_quality,
    compute_residual_uniqueness,
    compute_sparsity_flags,
    compute_vif,
)
from workbench.governance.report_gate import validate_report_verdict  # noqa: E402
from workbench.governance.semantic import (  # noqa: E402
    SemanticRegistry,
    build_sigma_vector,
)

from scripts._constants import TRADING_DAYS_PER_YEAR  # noqa: E402
from scripts._proxy_aggregation import coupled_aggregate  # noqa: E402
from scripts._replay_registry import (  # noqa: E402
    CHANNELS,
    KNOWN_DATA_GAPS,
    PROXY_REGISTRY,
    STRESS_EVENTS,
    VARIABLES,
    MeasurementBundle,
    load_official_panel,
)
from scripts._replay_transforms import (  # noqa: E402
    _component,  # noqa: F401
    _diff_abs,  # noqa: F401
    _jump_activation_score,  # noqa: F401
    _pct_component,  # noqa: F401
    _rolling_zscore,  # noqa: F401
)
from scripts._runtime_io import ensure_dir  # noqa: E402

CONFIG_PATH = (
    REPO_ROOT / "configs" / "structural_replay" / "config.yaml"
)
SEMANTIC_REGISTRY_PATH = REPO_ROOT / "governance" / "semantic_registry.json"


def load_cfg() -> DictConfig:
    """Load YAML config and merge Hydra-style ``key=value`` overrides from argv.

    Examples:
        python scripts/structural_replay_v2.py
        python scripts/structural_replay_v2.py panel.release_id=2026-04-22-r1
        python scripts/structural_replay_v2.py run.tag=weekly output.subdir=runs/weekly
    """
    os.environ.setdefault("STRUCTURAL_PROJECT", str(REPO_ROOT))
    base = OmegaConf.load(CONFIG_PATH)
    overrides = OmegaConf.from_cli(sys.argv[1:])
    return OmegaConf.merge(base, overrides)


def build_measurement_bundle(panel: pd.DataFrame) -> MeasurementBundle:
    """Build audited structural channels from registered proxy components.

    The output is intentionally path-oriented. VIX, HY OAS, TEDRATE, and broad
    stress indices remain available as benchmarks/controls, but they no longer
    define D/K/X structural channels.

    Phase C1: each proxy's builder is wrapped in try/except. A builder that
    raises records BUILD_FAILED (not silent available=False); the proxy is
    excluded from aggregation and the channel is flagged degraded if the
    roster shrinks below quorum. See _proxy_state.ProxyState.
    """
    from scripts._proxy_state import (
        classify_build_result,
        is_active_for_aggregation,
        registry_row_with_state,
    )

    component_values = pd.DataFrame(index=panel.index)
    registry_rows: list[dict] = []
    build_results: dict[str, Any] = {}
    for spec in PROXY_REGISTRY:
        # Phase C1: catch builder exceptions -> BUILD_FAILED, do NOT crash the
        # whole pipeline. A failed K builder degrades only the K channel.
        build_error: str | None = None
        value = None
        try:
            value = spec.builder(panel)
        except Exception as exc:
            build_error = f"{type(exc).__name__}: {exc}"
        result = classify_build_result(spec.name, value, build_error=build_error)
        build_results[spec.name] = result
        if is_active_for_aggregation(result):
            component_values[spec.name] = result.value

    channels = pd.DataFrame(index=panel.index)
    coverage = pd.DataFrame(index=panel.index)
    confidence = pd.DataFrame(index=panel.index)

    # ── Step 1: Collect canonical voting specs per channel ─────────────────
    canonical_channels = {"M", "D_contraction", "K", "X_agg"}
    channel_specs: dict[str, list[str]] = {}
    channel_present: dict[str, list] = {}

    for ch in CHANNELS:
        specs = [
            s for s in PROXY_REGISTRY
            if s.target_variable == ch
            and s.tier in ("core", "auxiliary")
            and s.canonical_status == "canonical_voting"
        ]
        present = [s for s in specs if s.name in component_values.columns]
        channel_present[ch] = present
        if ch in canonical_channels:
            channel_specs[ch] = [s.name for s in present]

    # Advance canonical voting proxies using runtime evidence, not registry
    # declaration alone.  Active components are emitted to proxy_components;
    # canonical voters additionally enter the aggregation roster.
    for spec in PROXY_REGISTRY:
        result = build_results[spec.name]
        if not is_active_for_aggregation(result):
            continue
        if (
            spec.target_variable in canonical_channels
            and spec.tier in ("core", "auxiliary")
            and spec.canonical_status == "canonical_voting"
        ):
            result.eligible_to_vote = True
            result.in_roster = spec.name in channel_specs.get(spec.target_variable, [])
            result.emitted = result.in_roster

    # ── Step 2: Coupled aggregation for canonical channels ────────────────
    # M, D, K, X are coupled through ODE drift equations. Instead of
    # computing each independently, we iterate until cross-channel
    # dependencies converge.
    coupled = coupled_aggregate(component_values, channel_specs)
    for ch in canonical_channels:
        channels[ch] = coupled[ch]
        present = channel_present[ch]
        if present:
            names = [s.name for s in present]
            comp = component_values[names]
            valid = comp.notna()
            in_roster = valid.cummax()
            n_in_roster = in_roster.sum(axis=1)
            coverage[ch] = (valid.sum(axis=1) / n_in_roster.clip(lower=1)).fillna(0.0)
        else:
            coverage[ch] = 0.0
        confidence[ch] = coverage[ch].map(confidence_label)

    # ── Step 3: Non-canonical channels (X_PRE, X_REALIZED, Pi_t) ─────────
    # These use the original independent aggregation (they don't vote).
    for ch in CHANNELS:
        if ch in canonical_channels:
            continue
        present = channel_present[ch]
        if not present:
            channels[ch] = np.nan
            coverage[ch] = 0.0
            confidence[ch] = coverage[ch].map(confidence_label)
            continue

        var = VARIABLES.get(ch)
        use_family_or = bool(var and var.expected_freq == "mixed")

        if use_family_or:
            by_family: dict[str, list[str]] = {}
            for s in present:
                by_family.setdefault(s.raw_family, []).append(s.name)
            family_aggs = pd.DataFrame(index=panel.index)
            for fam, names_in_fam in by_family.items():
                family_aggs[fam] = component_values[names_in_fam].max(axis=1, skipna=True)
            valid_fam = family_aggs.notna()
            in_roster_fam = valid_fam.cummax()
            n_in_roster_fam = in_roster_fam.sum(axis=1)
            channels[ch] = family_aggs.mean(axis=1, skipna=True)
            coverage[ch] = (valid_fam.sum(axis=1) / n_in_roster_fam.clip(lower=1)).fillna(0.0)
        else:
            names = [s.name for s in present]
            comp = component_values[names]
            valid = comp.notna()
            channels[ch] = comp.mean(axis=1, skipna=True)
            in_roster = valid.cummax()
            n_in_roster = in_roster.sum(axis=1)
            coverage[ch] = (valid.sum(axis=1) / n_in_roster.clip(lower=1)).fillna(0.0)
        confidence[ch] = coverage[ch].map(confidence_label)

    registry_rows = [registry_row_with_state(spec, build_results[spec.name]) for spec in PROXY_REGISTRY]
    semantic = SemanticRegistry(SEMANTIC_REGISTRY_PATH)
    registry_rows = [semantic.attach_metadata(row, row["target_variable"]) for row in registry_rows]
    audit = audit_measurement_layers(channels, component_values, registry_rows, panel)
    return MeasurementBundle(
        channels=channels.clip(-4, 4),
        components=component_values,
        coverage=coverage,
        confidence=confidence,
        registry=registry_rows,
        audit=audit,
    )


def confidence_label(value: float) -> str:
    if value >= 0.75:
        return "VALID_FULL"
    if value >= 0.50:
        return "VALID_PARTIAL"
    if value >= 0.25:
        return "DIAGNOSTIC_ONLY"
    return "INVALID"


def audit_measurement_layers(
    channels: pd.DataFrame,
    components: pd.DataFrame,
    registry_rows: list[dict],
    panel: pd.DataFrame,
) -> dict:
    """v2: hardened measurement audit with CORE/DIGANOSTIC tier enforcement.

    CORE raw-series sharing across channels → HARD_ERROR (blocks execution).
    allow_derivative_reuse no longer silences; emits AUTHORIZED_SHARED_DERIVATIVE.
    independence_group cross-channel sharing enforced for CORE tier.
    core_contract violations downgrade or fail based on tier.
    """
    available = [r for r in registry_rows if r["available"]]
    voting = [r for r in available if r["tier"] in ("core", "auxiliary")]
    # Quarantined / non-canonical proxies stay computable for research, but must
    # not veto the daily measurement path via CORE isolation HARD_ERROR.
    def _enforced_core(row: dict) -> bool:
        status = str(row.get("canonical_status") or "")
        if status.startswith("quarantined") or status == "extension_beyond_canonical":
            return False
        return row["tier"] == "core"

    core_rows = [r for r in available if _enforced_core(r)]
    diagnostic_rows = [r for r in available if r["tier"] not in ("core", "auxiliary")]

    # ── 1) CORE raw-series isolation (HARD_ERROR) ──────────────────────────
    core_raw_channels: dict[str, set[str]] = {}
    core_raw_sharing: list[dict] = []
    for row in core_rows:
        for raw in row["raw_series"]:
            core_raw_channels.setdefault(raw, set()).add(row["target_variable"])
    for raw, channels_seen in core_raw_channels.items():
        if len(channels_seen) > 1:
            core_raw_sharing.append({
                "raw_series": raw,
                "channels": sorted(channels_seen),
                "severity": "HARD_ERROR",
                "message": f"CORE RAW-SERIES SHARING: {raw} appears in {sorted(channels_seen)}",
            })

    # ── 2) Authorized / diagnostic shared-source detection ──────────────────
    authorized_shared_derivative: list[dict] = []
    diagnostic_shared_source: list[dict] = []
    all_voting_raw: dict[str, set[str]] = {}
    for row in voting:
        for raw in row["raw_series"]:
            all_voting_raw.setdefault(raw, set()).add(row["target_variable"])
    # Check diagnostic rows against voting channels
    for row in diagnostic_rows:
        for raw in row["raw_series"]:
            if raw in all_voting_raw:
                voting_chs = all_voting_raw[raw] - {row["target_variable"]}
                if voting_chs:
                    diagnostic_shared_source.append({
                        "raw_series": raw,
                        "diagnostic_proxy": row["name"],
                        "diagnostic_channel": row["target_variable"],
                        "voting_channels": sorted(voting_chs),
                        "severity": "DIAGNOSTIC_SHARED_SOURCE",
                    })
    # allow_derivative_reuse → now emits AUTHORIZED, not silent
    for row in voting:
        if row.get("allow_derivative_reuse"):
            for raw in row["raw_series"]:
                if raw in all_voting_raw and len(all_voting_raw[raw]) > 1:
                    authorized_shared_derivative.append({
                        "raw_series": raw,
                        "channels": sorted(all_voting_raw[raw]),
                        "proxy": row["name"],
                        "tier": row["tier"],
                        "reason": "allow_derivative_reuse=True on proxy",
                        "severity": "AUTHORIZED_SHARED_DERIVATIVE",
                    })

    # ── 3) independence_group cross-channel enforcement ─────────────────────
    group_channels: dict[str, set[str]] = {}
    group_sharing: list[dict] = []
    for row in core_rows:
        g = row.get("independence_group", "")
        if not g:
            continue
        group_channels.setdefault(g, set()).add(row["target_variable"])
    for g, chs in group_channels.items():
        if len(chs) > 1:
            group_sharing.append({
                "independence_group": g,
                "channels": sorted(chs),
                "severity": "HARD_ERROR",
                "message": f"INDEPENDENCE_GROUP CROSSING: {g!r} in CORE of {sorted(chs)}",
            })

    # ── 4) core_contract violations ─────────────────────────────────────────
    core_contract_violations: list[dict] = []
    for row in core_rows + [r for r in voting if r["tier"] == "auxiliary"]:
        var = VARIABLES.get(row["target_variable"])
        if var is None or not var.core_contract:
            continue
        g = row.get("independence_group", "")
        if not g:
            continue
        allowed = set(var.core_contract.get("allowed_groups", ()))
        forbidden = set(var.core_contract.get("forbidden_groups", ()))
        if g in forbidden:
            core_contract_violations.append({
                "channel": row["target_variable"],
                "proxy": row["name"],
                "tier": row["tier"],
                "independence_group": g,
                "violation": "FORBIDDEN_GROUP",
                "message": f"{row['name']} (group={g!r}) violates {row['target_variable']} core_contract forbidden_groups",
            })
        elif allowed and g not in allowed:
            core_contract_violations.append({
                "channel": row["target_variable"],
                "proxy": row["name"],
                "tier": row["tier"],
                "independence_group": g,
                "violation": "UNLISTED_GROUP",
                "message": f"{row['name']} (group={g!r}) not in {row['target_variable']} core_contract allowed_groups",
            })

    # ── 5) Cross-channel statistics (unchanged from v1) ─────────────────────
    channel_corr = channels[CHANNELS].corr(min_periods=TRADING_DAYS_PER_YEAR).round(3).fillna(0.0)
    max_corr = 0.0
    if len(channel_corr) > 1:
        vals = channel_corr.where(~np.eye(len(channel_corr), dtype=bool)).abs().stack()
        max_corr = float(vals.max()) if not vals.empty else 0.0

    residual_uniqueness = compute_residual_uniqueness(channels, panel)
    pc1_variance = compute_pc1_variance(channels)
    vif = compute_vif(channels)
    family_concentration = compute_family_concentration(voting)
    derivative_contamination = compute_derivative_contamination(channels)
    sparsity_flag = compute_sparsity_flags(channels, registry_rows)
    contract_violations = compute_contract_violations(registry_rows, VARIABLES)
    horizon_consistency = compute_horizon_consistency(registry_rows, VARIABLES)

    # ── 6) Build warnings (v2: tier-aware severity) ─────────────────────────
    warnings: list[str] = []

    # HARD_ERROR — core raw-series sharing (blocks execution)
    hard_errors: list[str] = []
    for item in core_raw_sharing:
        hard_errors.append(item["message"])
    for item in group_sharing:
        hard_errors.append(item["message"])

    # AUTHORIZED (was silences; now visible)
    for item in authorized_shared_derivative:
        warnings.append(
            f"AUTHORIZED_SHARED_DERIVATIVE: {item['proxy']} ({item['tier']}) "
            f"shares raw_series={item['raw_series']!r} across {item['channels']}. "
            f"reason={item['reason']}"
        )

    # DIAGNOSTIC (info-level, always visible)
    for item in diagnostic_shared_source:
        warnings.append(
            f"DIAGNOSTIC_SHARED_SOURCE: {item['diagnostic_proxy']} "
            f"({item['diagnostic_channel']}, diagnostic) reads {item['raw_series']!r} "
            f"which also feeds {item['voting_channels']} voting."
        )

    # Core contract violations
    for v in core_contract_violations:
        warnings.append(f"CORE_CONTRACT_VIOLATION: {v['message']}")

    # Statistical warnings (unchanged thresholds)
    if max_corr >= 0.85:
        warnings.append("CHANNEL_COLLAPSE: pairwise channel correlation exceeds 0.85.")
    elif max_corr >= 0.70:
        warnings.append("CHANNEL_CORRELATION_WARNING: pairwise channel correlation exceeds 0.70.")
    if pc1_variance >= 0.75:
        warnings.append("SCALAR_REGRESSION: first principal component explains more than 75% of channel variance.")
    elif pc1_variance >= 0.65:
        warnings.append("PC1_DOMINANCE_WARNING: first principal component explains more than 65% of channel variance.")
    weak = [ch for ch, val in residual_uniqueness.items() if val < 0.20]
    if weak:
        warnings.append(f"RESIDUAL_UNIQUENESS_WEAK: {', '.join(weak)} residual uniqueness below 0.20.")

    # Family warnings
    for ch, fams in family_concentration.items():
        if not fams:
            continue
        top_family, top_share = max(fams.items(), key=lambda kv: kv[1])
        if top_share > 0.75:
            warnings.append(
                f"FAMILY_MONOCULTURE: {ch} is {top_share:.0%} sourced from raw_family={top_family!r}."
            )
    family_overlap_pairs: list[tuple[str, str, str]] = []
    for ch1 in CHANNELS:
        for ch2 in CHANNELS:
            if ch1 >= ch2:
                continue
            shared = set(family_concentration.get(ch1, {})) & set(family_concentration.get(ch2, {}))
            for fam in shared:
                if (
                    family_concentration[ch1][fam] >= 0.30
                    and family_concentration[ch2][fam] >= 0.30
                    and abs(channel_corr.loc[ch1, ch2]) > 0.40
                ):
                    family_overlap_pairs.append((ch1, ch2, fam))
    for ch1, ch2, fam in family_overlap_pairs:
        warnings.append(
            f"FAMILY_CONTAMINATION: {ch1} and {ch2} both depend on raw_family={fam!r} "
            f"with corr={channel_corr.loc[ch1, ch2]:.2f}."
        )
    for entry in derivative_contamination:
        warnings.append(
            f"DERIVATIVE_CONTAMINATION: {entry['channel']} ~ Δ^{entry['order']}({entry['source']}) "
            f"corr={entry['correlation']:.2f}."
        )
    for ch, info in sparsity_flag.items():
        if info["false_independence"]:
            warnings.append(
                f"SPARSITY_FALSE_INDEPENDENCE: {ch} non_zero_coverage={info['non_zero_coverage']:.2f}, "
                f"low cross-channel R^2 may be due to dormancy, not orthogonality."
            )
    for v in contract_violations:
        warnings.append(
            f"CONTRACT_VIOLATION: variable={v['variable']} expects freq={v['expected_freq']!r}, "
            f"but core proxy={v['proxy']!r} is freq={v['actual_freq']!r}."
        )
    for ch, info in horizon_consistency.items():
        if info.get("warning"):
            horizons_str = ", ".join(f"{f}×{n}" for f, n in info["horizons"].items())
            warnings.append(
                f"HORIZON_INCONSISTENT: {ch} (expected_freq={info['expected_freq']!r}) "
                f"mixes {info['n_freq_classes']} freq classes ({horizons_str}); "
                f"channel-mean aggregates unevenly across information-per-unit-time."
            )

    return {
        "hard_errors": hard_errors,
        "core_raw_sharing": core_raw_sharing,
        "independence_group_sharing": group_sharing,
        "authorized_shared_derivative": authorized_shared_derivative,
        "diagnostic_shared_source": diagnostic_shared_source,
        "core_contract_violations": core_contract_violations,
        "channel_correlation": channel_corr.to_dict(),
        "max_abs_channel_correlation": max_corr,
        "pc1_variance_share": pc1_variance,
        "vif": vif,
        "residual_uniqueness": residual_uniqueness,
        "family_concentration": family_concentration,
        "derivative_contamination": derivative_contamination,
        "sparsity_flag": sparsity_flag,
        "contract_violations": contract_violations,
        "horizon_consistency": horizon_consistency,
        "known_data_gaps": list(KNOWN_DATA_GAPS),
        "warnings": warnings,
    }



# compute_* functions moved to replay/scoring.py
# Import: from replay.scoring import compute_family_concentration, ...

# ── Benchmark Signals ────────────────────────────────────────────────────────

def build_benchmark_signals(panel: pd.DataFrame) -> pd.DataFrame:
    """Build benchmark stress signals from standard indicators."""
    signals = pd.DataFrame(index=panel.index)

    # VIX
    if "FRED:VIXCLS" in panel.columns:
        vix = panel["FRED:VIXCLS"].interpolate(limit=5)
        mu = vix.expanding(TRADING_DAYS_PER_YEAR).mean()
        sigma = vix.expanding(TRADING_DAYS_PER_YEAR).std().replace(0, 1)
        signals["VIX_zscore"] = ((vix - mu) / sigma).clip(-3, 5)

    # NFCI
    if "FRED:NFCI" in panel.columns:
        nfci = panel["FRED:NFCI"].interpolate(limit=7)
        mu = nfci.expanding(TRADING_DAYS_PER_YEAR).mean()
        sigma = nfci.expanding(TRADING_DAYS_PER_YEAR).std().replace(0, 1)
        signals["NFCI_zscore"] = ((nfci - mu) / sigma).clip(-3, 5)

    # STLFSI4
    if "FRED:STLFSI4" in panel.columns:
        stlfsi = panel["FRED:STLFSI4"].interpolate(limit=7)
        mu = stlfsi.expanding(TRADING_DAYS_PER_YEAR).mean()
        sigma = stlfsi.expanding(TRADING_DAYS_PER_YEAR).std().replace(0, 1)
        signals["STLFSI4_zscore"] = ((stlfsi - mu) / sigma).clip(-3, 5)

    # BAA10YM (credit spread)
    if "FRED:BAA10YM" in panel.columns:
        baa10 = panel["FRED:BAA10YM"].interpolate(limit=5)
        mu = baa10.expanding(TRADING_DAYS_PER_YEAR).mean()
        sigma = baa10.expanding(TRADING_DAYS_PER_YEAR).std().replace(0, 1)
        signals["BAA10YM_zscore"] = ((baa10 - mu) / sigma).clip(-3, 5)

    # HY OAS (where available)
    if "FRED:BAMLH0A0HYM2" in panel.columns:
        hy = panel["FRED:BAMLH0A0HYM2"].interpolate(limit=5)
        mu = hy.expanding(TRADING_DAYS_PER_YEAR).mean()
        sigma = hy.expanding(TRADING_DAYS_PER_YEAR).std().replace(0, 1)
        signals["HYOAS_zscore"] = ((hy - mu) / sigma).clip(-3, 5)

    # TEDRATE (retired, but available pre-2022)
    if "FRED:TEDRATE" in panel.columns:
        ted = panel["FRED:TEDRATE"].interpolate(limit=5)
        mu = ted.expanding(TRADING_DAYS_PER_YEAR).mean()
        sigma = ted.expanding(TRADING_DAYS_PER_YEAR).std().replace(0, 1)
        signals["TEDRATE_zscore"] = ((ted - mu) / sigma).clip(-3, 5)

    # CP-Bill spread
    if "FRED:DCPF3M" in panel.columns and "FRED:DGS3MO" in panel.columns:
        cp_bill = panel["FRED:DCPF3M"] - panel["FRED:DGS3MO"]
        mu = cp_bill.expanding(TRADING_DAYS_PER_YEAR).mean()
        sigma = cp_bill.expanding(TRADING_DAYS_PER_YEAR).std().replace(0, 1)
        signals["CPBill_zscore"] = ((cp_bill - mu) / sigma).clip(-3, 5)

    # NFCI sub-indices
    for sub in ["NFCIRISK", "NFCILEVERAGE", "NFCICREDIT"]:
        col = f"FRED:{sub}"
        if col in panel.columns:
            s = panel[col].interpolate(limit=7)
            mu = s.expanding(TRADING_DAYS_PER_YEAR).mean()
            sigma = s.expanding(TRADING_DAYS_PER_YEAR).std().replace(0, 1)
            signals[f"{sub}_zscore"] = ((s - mu) / sigma).clip(-3, 5)

    return signals


# ── Event Analysis ───────────────────────────────────────────────────────────

@dataclass
class EventResult:
    event_id: str
    event_name: str
    peak_date: str
    category: str
    observed_path: list[dict] = field(default_factory=list)
    path_text: str = ""
    peak_regime: str = ""
    channel_at_peak: dict[str, float] = field(default_factory=dict)
    channel_coverage_at_peak: dict[str, float] = field(default_factory=dict)
    channel_confidence_at_peak: dict[str, str] = field(default_factory=dict)
    first_trigger_dates: dict[str, str] = field(default_factory=dict)
    benchmark_context: dict[str, float] = field(default_factory=dict)
    governance_flags: list[str] = field(default_factory=list)
    data_available: dict[str, bool] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def calibrate_path_thresholds(channels: pd.DataFrame) -> dict[str, dict[str, float]]:
    train = channels[(channels.index >= "2007-01-01") & (channels.index <= "2016-12-31")]
    if len(train.dropna(how="all")) < TRADING_DAYS_PER_YEAR:
        train = channels
    thresholds: dict[str, dict[str, float]] = {}
    for ch in CHANNELS:
        s = train[ch].dropna() if ch in train.columns else pd.Series(dtype=float)
        if len(s) < 30:
            thresholds[ch] = {"warning": 1.0, "critical": 1.5}
            continue
        thresholds[ch] = {
            "warning": float(s.quantile(0.90)),
            "critical": float(s.quantile(0.95)),
        }
    return thresholds


def classify_regime(row: pd.Series, thresholds: dict[str, dict[str, float]], confidence: dict[str, str]) -> str:
    # Level-based activation
    active = {ch: bool(row.get(ch, np.nan) >= thresholds[ch]["warning"]) for ch in CHANNELS}

    # Velocity-aware activation: rapid deterioration lowers threshold to 60%
    for ch in CHANNELS:
        vel_key = f"velocity_{ch}"
        vel = row.get(vel_key, np.nan)
        level = row.get(ch, np.nan)
        if vel is not None and not np.isnan(vel) and level is not None and not np.isnan(level):
            threshold = thresholds[ch]["warning"]
            if abs(vel) > 0.3 and abs(level) > threshold * 0.6:
                active[ch] = True

    return _classify_from_active(active, confidence, row)


def classify_regime_with_velocity(
    channels: pd.DataFrame, idx: int,
    thresholds: dict[str, dict[str, float]], confidence: dict[str, str],
) -> str:
    """Classify regime using both level and velocity at a specific index."""
    row = channels.iloc[idx]
    active = {ch: bool(row.get(ch, np.nan) >= thresholds[ch]["warning"]) for ch in CHANNELS}

    velocity_window = 5
    for ch in CHANNELS:
        if ch not in channels.columns or idx < velocity_window:
            continue
        vel = float(channels[ch].iloc[idx] - channels[ch].iloc[idx - velocity_window])
        level = float(row.get(ch, np.nan))
        threshold = thresholds[ch]["warning"]
        if not np.isnan(vel) and not np.isnan(level):
            if abs(vel) > 0.3 and abs(level) > threshold * 0.6:
                active[ch] = True

    return _classify_from_active(active, confidence, row)


def _classify_from_active(active: dict[str, bool], confidence: dict[str, str], row: pd.Series) -> str:
    """Classify regime from active channel map and row data."""
    implemented_channels = {"M", "D_contraction", "K", "X_agg"}
    # Only blind if an implemented channel has INVALID confidence AND has actual data
    blind = any(
        confidence.get(ch) == "INVALID"
        and row.get(ch) is not None
        and not np.isnan(row.get(ch, np.nan))
        for ch in implemented_channels
        if ch in confidence
    )
    if blind:
        return "Measurement Blind Spot"
    if active.get("X_REALIZED"):
        return "Forced Realization"
    if active.get("K") and active.get("D_contraction"):
        return "Curvature Break"
    if active.get("D_contraction"):
        return "Path Compression"
    if active.get("M"):
        return "Anchor Drift"
    if active.get("X_PRE"):
        return "Shadow Accumulation Trace"
    return "Normal / Untriggered"
    if blind:
        return "Measurement Blind Spot"
    if active.get("X_REALIZED"):
        return "Forced Realization"
    if active.get("K") and active.get("D_contraction"):
        return "Curvature Break"
    if active.get("D_contraction"):
        return "Path Compression"
    if active.get("M"):
        return "Anchor Drift"
    if active.get("X_PRE"):
        return "Shadow Accumulation Trace"
    return "Normal / Untriggered"


def analyze_event(
    ev: dict,
    benchmarks: pd.DataFrame,
    bundle: MeasurementBundle,
    thresholds: dict[str, dict[str, float]],
) -> EventResult:
    r = EventResult(
        event_id=ev["id"], event_name=ev["name"],
        peak_date=ev["peak"], category=ev["category"],
    )
    peak = pd.Timestamp(ev["peak"])
    event_start = pd.Timestamp(ev["start"])
    event_end = pd.Timestamp(ev["end"])
    pre_window_start = peak - pd.Timedelta(days=120)

    channels = bundle.channels
    coverage = bundle.coverage
    confidence = bundle.confidence
    if not channels.empty:
        idx = np.argmin(np.abs((channels.index - peak).total_seconds().values))
        row = channels.iloc[idx]
        cov_row = coverage.iloc[idx]
        conf_row = confidence.iloc[idx]
        r.channel_at_peak = {
            ch: float(row[ch]) for ch in CHANNELS if ch in row.index and pd.notna(row[ch])
        }
        r.channel_coverage_at_peak = {
            ch: float(cov_row[ch]) for ch in CHANNELS if ch in cov_row.index and pd.notna(cov_row[ch])
        }
        r.channel_confidence_at_peak = {
            ch: str(conf_row[ch]) for ch in CHANNELS if ch in conf_row.index
        }
        r.peak_regime = classify_regime_with_velocity(
            channels, idx, thresholds, r.channel_confidence_at_peak
        )

        for ch in CHANNELS:
            if ch not in channels.columns:
                r.data_available[ch] = False
                continue
            series = channels[ch].dropna()
            r.data_available[ch] = not series.empty
            window = series[(series.index >= pre_window_start) & (series.index <= event_end)]
            trigger = window[window >= thresholds[ch]["warning"]]
            if not trigger.empty:
                date = trigger.index[0]
                r.first_trigger_dates[ch] = date.date().isoformat()
                r.observed_path.append({
                    "channel": ch,
                    "date": date.date().isoformat(),
                    "days_before_peak": int((peak - date).days),
                    "value": float(trigger.iloc[0]),
                    "threshold": thresholds[ch]["warning"],
                })
        r.observed_path = sorted(r.observed_path, key=lambda x: x["date"])
        r.path_text = " -> ".join(item["channel"] for item in r.observed_path) or "no structural channel crossed warning threshold"

    for sig in ["VIX_zscore", "NFCI_zscore", "STLFSI4_zscore", "BAA10YM_zscore", "HYOAS_zscore", "CPBill_zscore"]:
        if sig not in benchmarks.columns:
            continue
        s = benchmarks[sig].dropna()
        win = s[(s.index >= event_start - pd.Timedelta(days=30)) & (s.index <= event_end)]
        if not win.empty:
            r.benchmark_context[sig] = float(win.max())

    r.governance_flags = list(bundle.audit.get("warnings", []))

    # Notes
    if peak > pd.Timestamp("2022-01-22"):
        r.notes.append("TEDRATE retired Jan 2022; retained only as historical benchmark where available.")
    if peak < pd.Timestamp("2023-05-01"):
        r.notes.append("Cached HY OAS starts in 2023; BAA10YM is the public credit-curve proxy for earlier windows.")
    if r.channel_confidence_at_peak.get("X_PRE") in ("INVALID", "DIAGNOSTIC_ONLY"):
        r.notes.append("X_PRE is weakly observed; do not interpret missing X_PRE movement as absence of hidden accumulation.")

    return r


def check_calm_contamination(results: list[EventResult], events: list[dict]) -> dict:
    event_dates = {e["id"]: (pd.Timestamp(e["start"]), pd.Timestamp(e["end"])) for e in events}
    contamination = {}
    for r in results:
        pre_start = pd.Timestamp(next(e["pre_start"] for e in events if e["id"] == r.event_id))
        calm_end = pre_start - pd.Timedelta(days=30)
        calm_start = calm_end - pd.Timedelta(days=90)
        for eid, (estart, eend) in event_dates.items():
            if eid == r.event_id:
                continue
            if calm_start <= eend and calm_end >= estart:
                contamination[r.event_id] = f"overlaps with '{eid}'"
                break
        else:
            contamination[r.event_id] = "clean"
    return contamination


# ── Report ───────────────────────────────────────────────────────────────────

def generate_report(
    results: list[EventResult],
    bundle: MeasurementBundle,
    thresholds: dict[str, dict[str, float]],
    calm_contamination: dict,
) -> str:
    lines = [
        "# Structural Deformation System — Path Replay v0.3",
        "",
        f"**Generated:** {pd.Timestamp.now().isoformat()}",
        f"**Events:** {len(results)}",
        "**Data:** Harvester official panel 2026-05-05-r1 (27 series, 236K rows)",
        "**Proxy:** audited M/D/K/X_PRE/X_REALIZED measurement layer",
        "**Interpretation rule:** outputs are path diagnostics, not optimized scalar targets.",
        "",
        "---",
        "",
        "## 1. Measurement Boundary",
        "",
        "- VIX, HY OAS, TEDRATE, STLFSI4, and NFCI composite remain benchmark/context signals; they do not define structural D/K/X channels.",
        "- `X_PRE` and `X_REALIZED` are separate. Official support usage is treated as forced realization, not hidden accumulation.",
        "- Thresholds are training-window path triggers used to describe channel sequence; they are not a reward target.",
        "",
        "### Path Trigger Thresholds",
        "",
        "| Channel | Warning Trigger | Critical Trigger |",
        "|---|---:|---:|",
    ]
    for ch in CHANNELS:
        lines.append(f"| {ch} | {thresholds[ch]['warning']:.3f} | {thresholds[ch]['critical']:.3f} |")

    lines += [
        "---",
        "",
        "## 2. Measurement Governance",
        "",
        f"**Max absolute channel correlation:** {bundle.audit['max_abs_channel_correlation']:.3f}",
        f"**PC1 variance share:** {bundle.audit['pc1_variance_share']:.3f}",
        "",
        "| Channel | Residual Uniqueness | VIF |",
        "|---|---:|---:|",
    ]
    for ch in CHANNELS:
        ru = bundle.audit["residual_uniqueness"].get(ch, 0.0)
        vif = bundle.audit["vif"].get(ch, 0.0)
        lines.append(f"| {ch} | {ru:.3f} | {vif:.2f} |")

    # v2: independence enforcement report
    raw_sharing = bundle.audit.get("core_raw_sharing", [])
    group_sharing = bundle.audit.get("independence_group_sharing", [])
    authorized = bundle.audit.get("authorized_shared_derivative", [])
    diagnostic_shared = bundle.audit.get("diagnostic_shared_source", [])
    contract_vios = bundle.audit.get("core_contract_violations", [])
    hard_errs = bundle.audit.get("hard_errors", [])

    lines += [
        "",
        "### v2 Core Isolation Enforcement",
        "",
        f"**HARD_ERROR count:** {len(hard_errs)}",
        f"**Core raw-series sharing violations:** {len(raw_sharing)}",
        f"**Independence-group crossings:** {len(group_sharing)}",
        f"**Authorized shared derivatives:** {len(authorized)}",
        f"**Diagnostic shared sources:** {len(diagnostic_shared)}",
        f"**Core contract violations:** {len(contract_vios)}",
    ]

    if raw_sharing:
        lines += ["", "#### Raw-series sharing (CORE tier)", ""]
        for item in raw_sharing:
            lines.append(f"- **{item['severity']}**: {item['raw_series']} → {item['channels']}")

    if group_sharing:
        lines += ["", "#### Independence-group crossings (CORE tier)", ""]
        for item in group_sharing:
            lines.append(f"- **{item['severity']}**: {item['independence_group']!r} → {item['channels']}")

    if authorized:
        lines += ["", "#### Authorized shared derivatives", ""]
        for item in authorized:
            lines.append(
                f"- {item['proxy']} ({item['tier']}): raw={item['raw_series']!r} "
                f"across {item['channels']}, reason={item['reason']}"
            )

    if diagnostic_shared:
        lines += ["", "#### Diagnostic shared sources", ""]
        for item in diagnostic_shared:
            lines.append(
                f"- {item['diagnostic_proxy']} ({item['diagnostic_channel']}): "
                f"raw={item['raw_series']!r} feeds {item['voting_channels']} voting"
            )

    if contract_vios:
        lines += ["", "#### Core contract violations", ""]
        for v in contract_vios:
            lines.append(
                f"- {v['proxy']} ({v['tier']}, group={v['independence_group']!r}): "
                f"{v['violation']} in {v['channel']}"
            )

    # Original governance flags
    if bundle.audit["warnings"]:
        lines += ["", "### Governance Flags", ""]
        for warning in bundle.audit["warnings"]:
            lines.append(f"- {warning}")
    else:
        lines += ["", "No channel-collapse governance flag was triggered."]

    lines += [
        "",
        "---",
        "",
        "## 3. Per-Event Path Diagnostics",
        "",
    ]

    for r in results:
        lines.append(f"### {r.event_name} (`{r.event_id}`)")
        lines.append(
            f"**Category:** {r.category} | **Peak:** {r.peak_date} | "
            f"**Peak regime:** {r.peak_regime}"
        )
        lines.append(f"**Observed path:** {r.path_text}")
        lines.append("")
        lines.append("| Channel | First Trigger | Days Before Peak | Value At Peak | Coverage | Confidence |")
        lines.append("|---|---|---:|---:|---:|---|")
        trigger_by_channel = {item["channel"]: item for item in r.observed_path}
        for ch in CHANNELS:
            item = trigger_by_channel.get(ch, {})
            lines.append(
                f"| {ch} | {item.get('date', 'not triggered')} | "
                f"{item.get('days_before_peak', '')} | "
                f"{r.channel_at_peak.get(ch, float('nan')):.3f} | "
                f"{r.channel_coverage_at_peak.get(ch, 0.0):.2f} | "
                f"{r.channel_confidence_at_peak.get(ch, 'INVALID')} |"
            )
        if r.benchmark_context:
            lines.append("")
            lines.append("Benchmark/context max inside event window:")
            parts = [f"{k}={v:.2f}" for k, v in sorted(r.benchmark_context.items())]
            lines.append(", ".join(parts))
        lines.append("")
        for note in r.notes:
            lines.append(f"> {note}")
        lines.append("")

    lines += [
        "---",
        "",
        "## 4. Path Summary",
        "",
        "| Event | Category | Peak Regime | Observed Path | Confidence Boundary | Calm Window Note |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        conf_boundary = ", ".join(
            f"{ch}:{label}" for ch, label in r.channel_confidence_at_peak.items()
            if label != "VALID_FULL"
        ) or "all full"
        fp_note = calm_contamination.get(r.event_id, "clean")
        lines.append(
            f"| {r.event_name} | {r.category} | {r.peak_regime} | "
            f"{r.path_text} | {conf_boundary} | {fp_note} |"
        )

    # Calm contamination
    contaminated = {k: v for k, v in calm_contamination.items() if v != "clean"}
    if contaminated:
        lines += ["", "---", "", "## 5. Calm-Period Contamination", ""]
        for eid, note in contaminated.items():
            name = next((r.event_name for r in results if r.event_id == eid), eid)
            lines.append(f"- **{name}** ({eid}): {note}")

    # Governance
    lines += [
        "",
        "---",
        "",
        "## 6. Proxy Registry",
        "",
        "| Component | Channel | Role | Mechanism | Available | Raw Series |",
        "|---|---|---|---|---|---|",
    ]
    for row in bundle.registry:
        raw = ", ".join(row["raw_series"])
        lines.append(
            f"| {row['name']} | {row['channel']} | {row['role']} | "
            f"{row['mechanism']} | {row['available']} | {raw} |"
        )

    # Caveats
    lines += [
        "",
        "---",
        "",
        "## 7. Caveats",
        "",
        "1. **No scalar success target:** This replay reports paths and boundaries. It intentionally avoids strong/good/weak model evaluation.",
        "2. **HY OAS gap:** BAMLH0A0HYM2/BAMLC0A0CM/BAMLC0A4CBBB only available from 2023-05 in this cache. Pre-2023 credit-curve deformation uses BAA10YM.",
        "3. **TEDRATE retired:** TEDRATE is benchmark-only and not a current structural proxy.",
        "4. **MOVE limited:** yfinance only provides ~1 year of MOVE history.",
        "5. **X_PRE weak observability:** Public data still captures traces, not the hidden stock itself.",
        "6. **Rolling normalization:** Early events can have lower channel coverage because rolling z-scores require a warm-up window.",
        "7. **No OOS validation:** This is a historical replay, not a walk-forward backtest.",
        "8. **Data vintage:** All series use latest-vintage data, not real-time vintages available at each event date.",
        "",
        "---",
        "",
        "## Actionable Verdict",
        "- Verdict: ACTION_REQUIRED",
        "- Severity: MEDIUM",
        "- Owner: governance",
        "- Required Action: Treat proxy outputs according to attached semantic metadata and promotion routing gate.",
        "- Closure Condition: Reports pass verdict gate, proxy registry carries semantic metadata, and promotion decision is explicit.",
        "",
    ]

    return "\n".join(lines)


# ── Main ─────────────────────────────────────────────────────────────────────

def main(cfg: DictConfig | None = None) -> None:
    # Resolve paths from cfg, then write config_snapshot.json BEFORE any work
    # begins. This closes the governance gap recorded for 2026-04-22_WEEKLY:
    # the snapshot now reflects the resolved config at run start, not a
    # backfill.
    if cfg is None:
        cfg = load_cfg()
    output_dir = Path(cfg.output.dir)
    event_dir = output_dir / cfg.output.event_subdir
    panel_path = Path(cfg.panel.path)
    ensure_dir(output_dir)
    ensure_dir(event_dir)
    snapshot = OmegaConf.to_container(cfg, resolve=True)
    (output_dir / "config_snapshot.json").write_text(
        json.dumps(snapshot, indent=2, default=str)
    )

    print("=" * 70)
    print("Structural Deformation System — Path Replay v0.3")
    print(f"  release={cfg.panel.release_id}  tag={cfg.run.tag}")
    print(f"  output={output_dir}")
    print("=" * 70)

    # 1. Load data
    print("\n[1/4] Loading official Harvester panel...")
    panel = load_official_panel(panel_path)

    # ── as-of date enforcement ───────────────────────────────────────────
    # Prevent future data leakage: truncate panel to as_of_date if specified.
    as_of = cfg.run.get("as_of_date", "")
    if as_of:
        as_of_ts = pd.Timestamp(as_of)
        panel = panel.loc[:as_of_ts]
        assert panel.index.max() <= as_of_ts, (
            f"as-of violation: panel has data beyond as_of_date={as_of} "
            f"(max={panel.index.max().date()})"
        )
        print(f"  as-of cutoff: {as_of} (panel truncated)")
    else:
        print("  as-of cutoff: NONE (using full panel range)")
    # ── end as-of enforcement ────────────────────────────────────────────

    print(f"  Panel: {panel.shape[1]} series, {len(panel)} days")
    print(f"  Range: {panel.index.min().date()} -> {panel.index.max().date()}")
    present = [c.replace('FRED:', '').replace('H41:', '').replace('TREASURY:', '').replace('YFINANCE:', '') for c in panel.columns]
    print(f"  Series: {', '.join(sorted(present))}")

    # 2. Build audited measurement layer
    print("\n[2/4] Building audited M/D/K/X_PRE/X_REALIZED measurement layer...")
    bundle = build_measurement_bundle(panel)
    channels = bundle.channels

    # v2: check hard_errors before proceeding
    hard_errors = bundle.audit.get("hard_errors", [])
    if hard_errors:
        print("\n  *** HARD_ERROR — core measurement isolation violated ***")
        for err in hard_errors:
            print(f"    {err}")
        print("  Aborting. Fix raw-series or independence_group sharing before re-running.")
        sys.exit(1)

    thresholds = calibrate_path_thresholds(channels)
    # Phase 4: realized-activation audit needs thresholds, computed after the
    # main audit pass, then merged into bundle.audit so downstream report code
    # can reference it.
    bundle.audit["realized_activation_quality"] = compute_realized_activation_quality(
        channels, bundle.components, bundle.registry, STRESS_EVENTS, thresholds
    )
    print(f"  Channels: {', '.join(CHANNELS)}")
    # Show coverage stats
    for ch in CHANNELS:
        valid = channels[ch].notna().sum()
        median_cov = bundle.coverage[ch].median()
        print(f"  {ch}: {valid}/{len(channels)} valid days, median coverage={median_cov:.2f}")
    if bundle.audit["warnings"]:
        print("  Governance flags:")
        for warning in bundle.audit["warnings"]:
            print(f"    - {warning}")
    # Cross-reference family-monoculture warnings to known data gaps so the
    # operator can immediately see which warnings require Harvester-side
    # data acquisition vs. which can be resolved at the measurement layer.
    gap_by_channel = {g["channel"]: g for g in bundle.audit.get("known_data_gaps", [])}
    monoculture_channels = []
    for w in bundle.audit.get("warnings", []):
        if w.startswith("FAMILY_MONOCULTURE"):
            for ch in CHANNELS:
                if f": {ch} " in w:
                    monoculture_channels.append(ch)
                    break
    if monoculture_channels:
        print("  Known data gaps (Harvester-side, see audit.known_data_gaps):")
        for ch in monoculture_channels:
            gap = gap_by_channel.get(ch)
            if not gap:
                continue
            print(f"    - {ch}: owner={gap['owner']}; unblock = {gap['unblock']}")
    raq = bundle.audit.get("realized_activation_quality", {})
    if raq:
        print(
            f"  X_REALIZED activation: recall={raq.get('activation_recall', 0):.2f} "
            f"({raq.get('events_activated', 0)}/{raq.get('events_with_data', 0)} events @ warning), "
            f"false_rate(critical)={raq.get('false_activation_rate_at_critical', 0):.4f} "
            f"({raq.get('calm_activated_at_critical', 0)}/{raq.get('calm_days', 0)} calm days), "
            f"false_rate(warning)={raq.get('false_activation_rate_at_warning', 0):.4f} "
            f"(includes minor events not on STRESS_EVENTS list)"
        )

    # 3. Save channel paths and benchmark controls. No scalar success target is emitted.
    print("\n[3/4] Saving channel paths + benchmark controls...")
    benchmarks = build_benchmark_signals(panel)
    # ── Compute channel velocity and acceleration ────────────────────────
    # Velocity = 5-day change in channel value (how fast is it moving?)
    # Acceleration = 5-day change in velocity (is the movement speeding up?)
    # These capture signal dynamics that absolute levels miss.
    velocity_window = 5
    channel_velocity = pd.DataFrame(index=channels.index)
    channel_acceleration = pd.DataFrame(index=channels.index)
    for ch in channels.columns:
        v = channels[ch].diff(velocity_window)
        channel_velocity[ch] = v
        channel_acceleration[ch] = v.diff(velocity_window)

    # Include velocity/acceleration in the signals output
    all_signals = pd.concat(
        [
            channels.add_prefix("channel_"),
            channel_velocity.add_prefix("velocity_"),
            channel_acceleration.add_prefix("acceleration_"),
            bundle.coverage.add_prefix("coverage_"),
            benchmarks,
        ],
        axis=1,
    )
    all_signals.to_parquet(output_dir / "all_signals.parquet")
    bundle.components.to_parquet(output_dir / "proxy_components.parquet")
    bundle.coverage.to_parquet(output_dir / "channel_coverage.parquet")
    # Map the replay's internal channel names to the canonical Σ channel names
    # (the bundle uses "D_contraction"; the canonical Σ vector uses "D"). Only
    # channels with real data are passed; build_sigma_vector treats the rest as
    # NOT_IMPLEMENTED (absent ≠ a 0.0 vote) so the four channels stay co-equal.
    _SIGMA_CHANNEL_NAMES = {"M": "M", "D_contraction": "D", "K": "K", "X_agg": "X_agg"}
    latest_scores = {
        canonical: float(bundle.channels[internal].dropna().iloc[-1])
        for internal, canonical in _SIGMA_CHANNEL_NAMES.items()
        if internal in bundle.channels and not bundle.channels[internal].dropna().empty
    }
    latest_scores["operator_penalty"] = float(bundle.audit.get("pc1_variance_share", 0.0))

    # Include velocity and acceleration in sigma_vector
    latest_velocity = {}
    latest_acceleration = {}
    for internal, canonical in _SIGMA_CHANNEL_NAMES.items():
        if internal in channel_velocity and not channel_velocity[internal].dropna().empty:
            latest_velocity[canonical] = round(float(channel_velocity[internal].dropna().iloc[-1]), 4)
        if internal in channel_acceleration and not channel_acceleration[internal].dropna().empty:
            latest_acceleration[canonical] = round(float(channel_acceleration[internal].dropna().iloc[-1]), 4)

    semantic = SemanticRegistry(SEMANTIC_REGISTRY_PATH)
    sigma_vector = build_sigma_vector(latest_scores, semantic)
    # Provenance: stamp the full 10-field block so downstream consumers (bridge)
    # can reject stale/previous-run sigma_vector. The bundle run_id is published
    # by the daily-run executor via ZCODE_BUNDLE_RUN_ID; fall back to the run
    # tag when invoked standalone (outside a bundle).
    from scripts._artifact_provenance import build_provenance

    bundle_run_id = os.environ.get("ZCODE_BUNDLE_RUN_ID") or str(cfg.run.tag)
    sigma_output = {
        "run_id": bundle_run_id,
        "as_of": str(cfg.run.get("as_of_date", "")),
        "generated_at": datetime.now(UTC).isoformat(),
        "sigma_scalar": None,
        "sigma_vector": sigma_vector,
        "channel_velocity": latest_velocity,
        "channel_acceleration": latest_acceleration,
        "velocity_window": velocity_window,
        "interpretation_scope": "scalar summary only; structural interpretation requires sigma_vector",
        "provenance": build_provenance(
            producer_step="structural_replay",
            source_release_id=str(cfg.panel.release_id),
            as_of_date=str(cfg.run.get("as_of_date", "")),
            input_paths=[str(panel_path)],
        ),
    }
    (output_dir / "proxy_registry.json").write_text(json.dumps(bundle.registry, indent=2))
    (output_dir / "sigma_vector.json").write_text(json.dumps(sigma_output, indent=2))
    (output_dir / "measurement_audit.json").write_text(json.dumps(bundle.audit, indent=2, default=str))
    print(f"  Signals: {all_signals.shape[1]} columns")

    # 4. Analyze
    print("\n[4/4] Analyzing stress events...")
    results = []
    for ev in STRESS_EVENTS:
        peak = pd.Timestamp(ev["peak"])
        if peak < panel.index.min() + pd.Timedelta(days=cfg.run.pre_event_warmup_days):
            print(f"  SKIP {ev['name']}: insufficient pre-peak data")
            continue
        r = analyze_event(ev, benchmarks, bundle, thresholds)
        results.append(r)

        # Save event window data
        pre = pd.Timestamp(ev["pre_start"])
        post = pd.Timestamp(ev["post_end"])
        ev_data = all_signals[(all_signals.index >= pre) & (all_signals.index <= post)]
        ev_data.to_csv(event_dir / f"{ev['id']}_signals.csv")

        print(f"  {ev['name']}: regime={r.peak_regime}, path={r.path_text}")

    contamination = check_calm_contamination(results, STRESS_EVENTS)

    for r in results:
        if contamination.get(r.event_id, "clean") != "clean":
            r.notes.append(f"Calm window {contamination[r.event_id]}")

    report = generate_report(results, bundle, thresholds, contamination)
    report_path = output_dir / "evaluation_report.md"
    report_path.write_text(report, encoding="utf-8")
    validate_report_verdict(report_path)

    # JSON results
    json_results = []
    for r in results:
        json_results.append({
            "event_id": r.event_id, "event_name": r.event_name,
            "peak_date": r.peak_date, "category": r.category,
            "peak_regime": r.peak_regime,
            "observed_path": r.observed_path,
            "path_text": r.path_text,
            "channel_at_peak": r.channel_at_peak,
            "channel_coverage_at_peak": r.channel_coverage_at_peak,
            "channel_confidence_at_peak": r.channel_confidence_at_peak,
            "benchmark_context": r.benchmark_context,
            "governance_flags": r.governance_flags,
            "notes": r.notes,
        })
    (output_dir / "results.json").write_text(json.dumps(json_results, indent=2, default=str))

    print(f"\n{'='*70}")
    print(f"Evaluation complete. {len(results)} events analyzed.")
    print("  Output mode: path diagnostics, no scalar evaluation target.")
    print(f"  Report: {output_dir / 'evaluation_report.md'}")
    print(f"{'='*70}")


if __name__ == "__main__":
    main(load_cfg())
