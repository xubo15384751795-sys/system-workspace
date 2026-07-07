"""Scoring and audit functions — pure computation, no I/O.

Extracted from scripts/structural_replay_v2.py.
These functions take DataFrames/dicts and return results.
They do not read files, write files, or call external services.

Phase 1 of structural_replay_v2.py module split.

Backward compatibility: the main script imports these functions and passes
CHANNELS/VARIABLES from its module scope.  Callers outside the main script
should import directly from replay.scoring.

Reconstructed from bytecode (2026-06-20) after source file was lost during
submodule consolidation.
"""
from __future__ import annotations

import collections as _coll
from typing import Any

import numpy as np
import pandas as pd

# Canonical channels (Finance-2.tex §4.1 + §7.2)
CHANNELS: list[str] = ['M', 'D_contraction', 'K', 'X_agg', 'X_PRE', 'X_REALIZED', 'Pi_t']


def compute_family_concentration(voting_rows: list[dict]) -> dict[str, dict[str, float]]:
    """Per-variable share of (core+aux) proxies coming from each raw_family."""
    out: dict[str, dict[str, float]] = {}
    for ch in CHANNELS:
        counters: dict[str, float] = {}
        for row in voting_rows:
            if row.get('target_variable') == ch:
                fam = row.get('raw_family', 'UNKNOWN')
                counters[fam] = counters.get(fam, 0) + 1
        total = sum(counters.values())
        out[ch] = {fam: round(count / total, 4) if total > 0 else 0.0
                    for fam, count in counters.items()}
    return out


def compute_derivative_contamination(channels: pd.DataFrame) -> list[dict]:
    """Check whether one channel is ≈ a finite-difference derivative of another."""
    findings: list[dict] = []
    for ch1 in CHANNELS:
        for ch2 in CHANNELS:
            if ch1 >= ch2:
                continue
            if ch1 not in channels.columns or ch2 not in channels.columns:
                continue
            for order in (1, 2):
                s1 = channels[ch1].dropna()
                s2 = channels[ch2].dropna()
                if len(s1) < 10 or len(s2) < 10:
                    continue
                diff_s2 = s2.diff(order).dropna()
                if len(diff_s2) < 5:
                    continue
                aligned = pd.concat([s1, diff_s2], axis=1).dropna()
                if len(aligned) < 5:
                    continue
                corr = float(aligned.iloc[:, 0].corr(aligned.iloc[:, 1]))
                if abs(corr) > 0.45:
                    findings.append({
                        'channel': ch1,
                        'source': ch2,
                        'order': order,
                        'correlation': round(corr, 4),
                    })
    return findings


def compute_sparsity_flags(channels: pd.DataFrame, registry_rows: list[dict]) -> dict[str, dict]:
    """Flag channels whose statistical independence is sparsity-driven."""
    out: dict[str, dict] = {}
    for ch in CHANNELS:
        if ch not in channels.columns:
            continue
        s = channels[ch]
        covered = [r for r in registry_rows if r.get('target_variable') == ch]
        total = len(covered)
        non_zero = int((s.notna() & (s.abs() > 0.0)).sum())
        non_zero_cov = round(non_zero / max(len(s.dropna()), 1), 4)
        out[ch] = {
            'non_zero_coverage': non_zero_cov,
            'false_independence': non_zero_cov < 0.1,
            'covered_days': total,
        }
        if non_zero_cov < 0.2:
            out[ch]['false_independence'] = True
    return out


def compute_horizon_consistency(registry_rows: list[dict], variables: dict[str, Any]) -> dict:
    """Per-variable horizon distribution + warning if mixed-frequency aggregation."""
    out: dict[str, dict] = {}
    for ch in CHANNELS:
        voting = [r for r in registry_rows if r.get('target_variable') == ch]
        freq_counter: dict[str, int] = {}
        for r in voting:
            for tier in ('core', 'auxiliary'):
                if r.get('tier') == tier and r.get('available'):
                    freq = r.get('freq', 'unknown')
                    freq_counter[freq] = freq_counter.get(freq, 0) + 1
        n_classes = len(freq_counter)
        var = variables.get(ch)
        if var is not None:
            expected = getattr(var, 'expected_freq', None) or (var.get('expected_freq') if isinstance(var, dict) else None)
            legitimately_mixed = getattr(var, 'legitimately_mixed', False) if not isinstance(var, dict) else var.get('legitimately_mixed', False)
            accepted = getattr(var, 'accepted_fallback_freqs', set()) if not isinstance(var, dict) else var.get('accepted_fallback_freqs', set())
        else:
            expected = None
            legitimately_mixed = False
            accepted = set()
        expected_str = expected if isinstance(expected, str) else (getattr(expected, 'value', str(expected)) if expected else None)
        observed = set(freq_counter.keys())
        within_contract = True
        warn = False
        if expected_str and not legitimately_mixed:
            if not observed.issubset(accepted if accepted else {expected_str}):
                within_contract = False
                warn = True
        out[ch] = {
            'horizons': dict(freq_counter),
            'n_freq_classes': n_classes,
            'warning': warn,
            'mixed': n_classes > 1,
            'expected_freq': expected_str,
            'legitimately_mixed': legitimately_mixed,
            'within_fallback_contract': within_contract,
        }
    return out


def compute_realized_activation_quality(
    channels: pd.DataFrame,
    components: pd.DataFrame,
    registry_rows: list[dict],
    events: list[dict],
    thresholds: dict[str, dict[str, float]],
) -> dict:
    """Activation-quality audit for X_REALIZED."""
    if 'X_REALIZED' not in channels.columns:
        return {'warning': True, 'critical': True, 'per_event': []}

    x = channels['X_REALIZED'].dropna()
    if x.empty:
        return {'warning': True, 'critical': True, 'per_event': []}

    warn_thresh = thresholds.get('X_REALIZED', {}).get('warning', 1.0)
    crit_thresh = thresholds.get('X_REALIZED', {}).get('critical', 1.5)

    per_event: list[dict] = []
    for ev in events:
        peak = ev.get('peak')
        if peak is None:
            per_event.append({'event_id': ev.get('id', ''), 'activated': False, 'reason': 'no_data'})
            continue
        peak_ts = pd.Timestamp(peak)
        win_start = peak_ts - pd.Timedelta(days=30)
        win_end = peak_ts + pd.Timedelta(days=30)
        window = x.loc[win_start:win_end]
        valid_window = window.dropna()
        triggered = bool((valid_window.abs() > warn_thresh).any())
        activated = triggered
        first_lead = None
        peak_val = float(valid_window.max()) if len(valid_window) > 0 else 0.0
        if triggered:
            first_idx = valid_window[valid_window.abs() > warn_thresh].index[0]
            first_lead = int((peak_ts - first_idx).days)
        per_event.append({
            'event_id': ev.get('id', ''),
            'event_name': ev.get('name', ''),
            'activated': activated,
            'first_trigger_lead_days': first_lead,
            'peak_window_max': round(peak_val, 4),
        })

    n_with_data = sum(1 for r in per_event if r.get('reason') != 'no_data')
    n_activated = sum(1 for r in per_event if r.get('activated'))
    recall = n_activated / max(n_with_data, 1)

    # False activation rate during calm periods
    calm_activated_warn = 0
    calm_activated_crit = 0
    calm_days = 0
    for ev in events:
        e_start = pd.Timestamp(ev.get('pre_start', ev.get('peak', '')))
        e_end = pd.Timestamp(ev.get('post_end', ev.get('peak', '')))
        if pd.isna(e_start) or pd.isna(e_end):
            continue
        in_event = (x.index >= e_start) & (x.index <= e_end)
        calm_idx = x.index[~in_event]
        calm_days += len(calm_idx)
        calm_vals = x.loc[calm_idx]
        calm_activated_warn += int((calm_vals.abs() > warn_thresh).sum())
        calm_activated_crit += int((calm_vals.abs() > crit_thresh).sum())

    false_rate_warn = calm_activated_warn / max(calm_days, 1)
    false_rate_crit = calm_activated_crit / max(calm_days, 1)

    # Sub-family split
    family_for_spec: dict[str, str] = {}
    for r in registry_rows:
        if r.get('target_variable') == 'X_REALIZED':
            family_for_spec[r.get('name', '')] = r.get('raw_family', 'UNKNOWN')

    sub_aggregates: dict[str, dict] = {}
    for fam in set(family_for_spec.values()):
        cols = [k for k, v in family_for_spec.items() if v == fam and k in channels.columns]
        if not cols:
            continue
        sub = channels[cols]
        valid_count = int(sub.notna().any(axis=1).sum())
        active_count = int((sub.abs() > 0.0).any(axis=1).sum())
        in_event_mask = pd.Series(False, index=channels.index)
        for ev in events:
            e_start = pd.Timestamp(ev.get('pre_start', ev.get('peak', '')))
            e_end = pd.Timestamp(ev.get('post_end', ev.get('peak', '')))
            if pd.isna(e_start) or pd.isna(e_end):
                continue
            in_event_mask |= (channels.index >= e_start) & (channels.index <= e_end)
        active_in_event = int((sub.abs() > 0.0).loc[in_event_mask].any(axis=1).sum())
        active_calm = int((sub.abs() > 0.0).loc[~in_event_mask].any(axis=1).sum())
        sub_aggregates[fam] = {
            'n_voting_proxies': len(cols),
            'voting_proxies': cols,
            'valid_days': valid_count,
            'active_days_total': active_count,
            'active_days_in_event_window': active_in_event,
            'active_days_calm': active_calm,
        }

    return {
        'warning_threshold': warn_thresh,
        'critical_threshold': crit_thresh,
        'events_with_data': n_with_data,
        'events_activated': n_activated,
        'activation_recall': round(recall, 4),
        'false_activation_rate': round(false_rate_warn, 6),
        'false_activation_rate_at_warning': round(false_rate_warn, 6),
        'false_activation_rate_at_critical': round(false_rate_crit, 6),
        'calm_days': calm_days,
        'calm_activated_days': calm_activated_warn,
        'calm_activated_at_warning': calm_activated_warn,
        'calm_activated_at_critical': calm_activated_crit,
        'per_event': per_event,
        'sub_family_split': sub_aggregates,
    }


def compute_contract_violations(registry_rows: list[dict], variables: dict[str, Any]) -> list[dict]:
    """Compare each available core proxy's freq to its variable's expected_freq."""
    rank = {'daily': 0, 'weekly': 1, 'monthly': 2, 'sparse': 3, 'mixed': 4}
    violations: list[dict] = []
    for row in registry_rows:
        if not row.get('available') or row.get('tier') != 'core':
            continue
        var = row.get('target_variable', '')
        var_obj = variables.get(var)
        if var_obj is None:
            continue
        expected = getattr(var_obj, 'expected_freq', None) or (var_obj.get('expected_freq') if isinstance(var_obj, dict) else None)
        actual = row.get('freq')
        if expected and actual:
            expected_str = expected if isinstance(expected, str) else getattr(expected, 'value', str(expected))
            ok = rank.get(actual, -1) <= rank.get(expected_str, -1)
            if not ok:
                violations.append({
                    'variable': var,
                    'expected_freq': expected_str,
                    'proxy': row.get('name', ''),
                    'actual_freq': actual,
                })
    return violations


def compute_pc1_variance(channels: pd.DataFrame) -> float:
    """First principal component variance ratio."""
    clean = channels[CHANNELS].dropna()
    if len(clean) < 2 or clean.shape[1] < 2:
        return 0.0
    x = clean.to_numpy()
    x = x - x.mean(axis=0)
    cov = np.cov(x, rowvar=False)
    eigvals = np.linalg.eigvalsh(cov)
    total = float(eigvals.sum())
    if total <= 0:
        return 0.0
    return float(eigvals.max() / total)


def compute_vif(channels: pd.DataFrame) -> dict[str, float]:
    """Variance Inflation Factor per channel."""
    active_channels = [ch for ch in CHANNELS if ch in channels.columns]
    clean = channels[active_channels].dropna()
    if len(clean) < 3:
        return {ch: 0.0 for ch in active_channels}

    result: dict[str, float] = {}
    for ch in active_channels:
        y = clean[ch].to_numpy()
        others = [c for c in active_channels if c != ch]
        if not others:
            result[ch] = 1.0
            continue
        x = np.column_stack([clean[c].to_numpy() for c in others] + [np.ones(len(clean))])
        beta, _, _, _ = np.linalg.lstsq(x, y, rcond=None)
        pred = x @ beta
        ss_res = float(np.sum((y - pred) ** 2))
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
        vif = 1.0 / (1.0 - r2) if r2 < 0.999 else 999.0
        result[ch] = round(vif, 4)
    return result


def compute_residual_uniqueness(channels: pd.DataFrame, panel: pd.DataFrame) -> dict[str, float]:
    """Residual uniqueness after controlling for VIX.

    NOTE: This function depends on _series and _rolling_zscore from the main
    script.  For standalone use, pass a panel with pre-computed VIX control.
    """
    try:
        from scripts.structural_replay_v2 import _series, _rolling_zscore
    except ImportError:
        _series = None
        _rolling_zscore = None

    active_channels = [ch for ch in CHANNELS if ch in channels.columns]
    data = channels[active_channels].copy()

    # Add VIX control if available
    vix = None
    if panel is not None and 'FRED:VIXCLS' in panel.columns:
        vix_col = panel['FRED:VIXCLS']
        if _rolling_zscore is not None:
            vix = _rolling_zscore(vix_col)
        else:
            vix = (vix_col - vix_col.rolling(60).mean()) / vix_col.rolling(60).std()

    if vix is not None:
        data['VIX_control'] = vix

    clean = data.dropna()
    if len(clean) < 3:
        return {ch: 0.0 for ch in active_channels}

    result: dict[str, float] = {}
    controls = ['VIX_control'] if 'VIX_control' in clean.columns else []
    for ch in active_channels:
        y = clean[ch].to_numpy()
        c_cols = [c for c in active_channels if c != ch] + controls
        if not c_cols:
            result[ch] = 1.0
            continue
        x = np.column_stack([clean[c].to_numpy() for c in c_cols] + [np.ones(len(clean))])
        beta, _, _, _ = np.linalg.lstsq(x, y, rcond=None)
        pred = x @ beta
        ss_res = float(np.sum((y - pred) ** 2))
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
        result[ch] = round(r2, 4)
    return result
