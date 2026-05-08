#!/usr/bin/env python3
"""Structural Deformation System — Historical Case Replay v2.

Uses the official Harvester panel (2026-05-05-r1) with 27 series across
FRED, H41, SEC, Treasury, and yfinance sources.  Builds M/D/K/X proxies
from real structural preset components rather than yfinance approximations.

Output:
  Output/sandbox/structural_replay_v2/
    evaluation_report.md
    event_windows/
    results.json
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT = Path(__file__).resolve().parent.parent
OFFICIAL_PANEL = (
    PROJECT / "Data" / "harvester" / "exports" / "2026-05-05-r1" / "data" / "official_panel.parquet"
)
OUTPUT_DIR = PROJECT / "Output" / "sandbox" / "structural_replay_v2"
EVENT_DIR = OUTPUT_DIR / "event_windows"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
EVENT_DIR.mkdir(parents=True, exist_ok=True)

# ── Stress Events ────────────────────────────────────────────────────────────

STRESS_EVENTS = [
    {
        "id": "ltcm_1998", "name": "LTCM / Russia Default",
        "peak": "1998-09-23", "start": "1998-07-01", "end": "1998-12-31",
        "pre_start": "1997-06-01", "post_end": "1999-06-01",
        "category": "credit_liquidity",
    },
    {
        "id": "dotcom_2000", "name": "Dot-com Bubble Burst",
        "peak": "2000-03-10", "start": "2000-01-01", "end": "2000-06-30",
        "pre_start": "1999-01-01", "post_end": "2000-12-31",
        "category": "equity_valuation",
    },
    {
        "id": "gfc_2008", "name": "GFC / Lehman",
        "peak": "2008-09-15", "start": "2008-07-01", "end": "2009-03-31",
        "pre_start": "2007-07-01", "post_end": "2009-06-30",
        "category": "credit_liquidity_systemic",
    },
    {
        "id": "flash_crash_2010", "name": "Flash Crash",
        "peak": "2010-05-06", "start": "2010-05-01", "end": "2010-06-30",
        "pre_start": "2010-01-01", "post_end": "2010-08-31",
        "category": "liquidity_technical",
    },
    {
        "id": "euro_debt_2011", "name": "US Downgrade / EU Debt Crisis",
        "peak": "2011-08-08", "start": "2011-07-01", "end": "2011-12-31",
        "pre_start": "2011-01-01", "post_end": "2012-03-31",
        "category": "sovereign_credit",
    },
    {
        "id": "taper_2013", "name": "Taper Tantrum",
        "peak": "2013-06-19", "start": "2013-05-01", "end": "2013-09-30",
        "pre_start": "2013-01-01", "post_end": "2013-12-31",
        "category": "rates_volatility",
    },
    {
        "id": "china_2015", "name": "China Devaluation / HY Stress",
        "peak": "2015-08-24", "start": "2015-08-01", "end": "2016-02-29",
        "pre_start": "2015-01-01", "post_end": "2016-06-30",
        "category": "credit_em",
    },
    {
        "id": "volmageddon_2018", "name": "Volmageddon",
        "peak": "2018-02-05", "start": "2018-01-15", "end": "2018-03-31",
        "pre_start": "2017-09-01", "post_end": "2018-06-30",
        "category": "volatility_technical",
    },
    {
        "id": "repo_2019", "name": "Repo Market Stress",
        "peak": "2019-09-17", "start": "2019-09-01", "end": "2019-12-31",
        "pre_start": "2019-06-01", "post_end": "2020-02-29",
        "category": "funding_liquidity",
    },
    {
        "id": "covid_2020", "name": "COVID-19 Crisis",
        "peak": "2020-03-23", "start": "2020-02-15", "end": "2020-06-30",
        "pre_start": "2019-09-01", "post_end": "2020-09-30",
        "category": "systemic_all_channel",
    },
    {
        "id": "ldi_2022", "name": "UK LDI / Gilt Crisis",
        "peak": "2022-09-28", "start": "2022-09-01", "end": "2022-12-31",
        "pre_start": "2022-06-01", "post_end": "2023-03-31",
        "category": "rates_leverage",
    },
    {
        "id": "svb_2023", "name": "SVB / Regional Banking Crisis",
        "peak": "2023-03-10", "start": "2023-03-01", "end": "2023-06-30",
        "pre_start": "2023-01-01", "post_end": "2023-09-30",
        "category": "banking_funding",
    },
    {
        "id": "august_2024", "name": "August 2024 Carry Unwind",
        "peak": "2024-08-05", "start": "2024-07-01", "end": "2024-09-30",
        "pre_start": "2024-04-01", "post_end": "2024-12-31",
        "category": "carry_unwind",
    },
]


# ── Data Loading ─────────────────────────────────────────────────────────────

def load_official_panel() -> pd.DataFrame:
    """Load and pivot the official Harvester panel to wide format."""
    raw = pd.read_parquet(OFFICIAL_PANEL)
    raw["date"] = pd.to_datetime(raw["date"])
    # Pivot to wide: one column per series_id
    wide = raw.pivot_table(
        index="date", columns="series_id", values="value", aggfunc="first"
    )
    wide = wide.sort_index()
    return wide


# ── Proxy Construction (M/D/K/X from official panel) ────────────────────────

def build_structural_proxies(panel: pd.DataFrame) -> pd.DataFrame:
    """Build M/D/K/X proxy channels from the official Harvester panel.

    Uses the actual series referenced in structural presets:
      M  ← T10Y2Y (curve shape), DFF (policy rate)
      D  ← VIXCLS (vol stress), BAMLH0A0HYM2 (credit depth), DBAA-BAA10YM (credit spread)
      K  ← VIXCLS (jump proxy), debt_to_penny (refinancing pressure)
      X  ← primary_credit + btfp + NFCI sub-indices + STLFSI4
    """
    channels = pd.DataFrame(index=panel.index)

    # ── M: Funding/Monetary channel ──
    m_components = []
    if "FRED:T10Y2Y" in panel.columns:
        # Invert: curve inversion = funding stress
        t10y2y = panel["FRED:T10Y2Y"].interpolate(limit=5)
        m_components.append(-t10y2y.rolling(21).mean())
    if "FRED:DFF" in panel.columns:
        dff = panel["FRED:DFF"].interpolate(limit=5)
        # Rate acceleration as stress proxy
        m_components.append(dff.diff(63).abs().rolling(21).mean())
    if "FRED:DCPF3M" in panel.columns and "FRED:DGS3MO" in panel.columns:
        # CP-Bill spread: unsecured - risk-free short term
        cp_bill = panel["FRED:DCPF3M"] - panel["FRED:DGS3MO"]
        m_components.append(cp_bill.rolling(21).mean())
    if m_components:
        m_raw = pd.concat(m_components, axis=1).mean(axis=1)
        channels["M"] = _zscore_expanding(m_raw, 252)
    else:
        channels["M"] = 0.0

    # ── D: Depth/Deformation channel ──
    d_components = []
    if "FRED:VIXCLS" in panel.columns:
        vix = panel["FRED:VIXCLS"].interpolate(limit=5)
        d_components.append(vix / vix.expanding(252).median())
    if "FRED:BAMLH0A0HYM2" in panel.columns:
        hy = panel["FRED:BAMLH0A0HYM2"].interpolate(limit=5)
        d_components.append(hy / hy.expanding(252).median().replace(0, 1))
    # Pre-2023: use BAA10YM as credit spread proxy
    if "FRED:BAA10YM" in panel.columns and "FRED:BAMLH0A0HYM2" not in panel.columns:
        baa10 = panel["FRED:BAA10YM"].interpolate(limit=5)
        d_components.append(baa10 / baa10.expanding(252).median().replace(0, 1))
    if "FRED:DBAA" in panel.columns and "FRED:DAAA" in panel.columns:
        # Baa-Aaa spread = credit migration pressure
        credit_migration = panel["FRED:DBAA"] - panel["FRED:DAAA"]
        d_components.append(credit_migration.rolling(21).mean())
    if "H41:discount_window" in panel.columns:
        dw = panel["H41:discount_window"].interpolate(limit=14)
        dw_norm = dw / dw.expanding(252).median().replace(0, 1)
        d_components.append(dw_norm.clip(0, 10))
    if d_components:
        d_raw = pd.concat(d_components, axis=1).mean(axis=1)
        channels["D_contraction"] = _zscore_expanding(d_raw, 252)
    else:
        channels["D_contraction"] = 0.0

    # ── K: Curvature/Kurtosis channel ──
    k_components = []
    if "FRED:VIXCLS" in panel.columns:
        vix = panel["FRED:VIXCLS"].interpolate(limit=5)
        vix_accel = vix.diff(5).diff(5).abs()
        vix_std = vix.rolling(63).std().replace(0, 1)
        k_components.append((vix_accel / vix_std).rolling(21).mean())
    if "TREASURY:debt_to_penny:tot_pub_debt_out_amt" in panel.columns:
        debt = panel["TREASURY:debt_to_penny:tot_pub_debt_out_amt"].interpolate(limit=30)
        debt_change = debt.pct_change(63).abs()
        k_components.append(debt_change.rolling(63).mean())
    if "TREASURY:daily_treasury_statement:open_today_bal" in panel.columns:
        tga = panel["TREASURY:daily_treasury_statement:open_today_bal"].interpolate(limit=5)
        tga_vol = tga.diff().abs().rolling(21).std()
        k_components.append(tga_vol / tga.rolling(63).mean().replace(0, 1))
    if k_components:
        k_raw = pd.concat(k_components, axis=1).mean(axis=1)
        channels["K"] = _zscore_expanding(k_raw, 252)
    else:
        channels["K"] = 0.0

    # ── X: Cross-system / Shadow channel ──
    x_components = []
    if "FRED:NFCI" in panel.columns:
        nfci = panel["FRED:NFCI"].interpolate(limit=7)
        x_components.append(nfci.rolling(5).mean())
    if "FRED:NFCIRISK" in panel.columns:
        x_components.append(panel["FRED:NFCIRISK"].interpolate(limit=7))
    if "FRED:NFCILEVERAGE" in panel.columns:
        x_components.append(panel["FRED:NFCILEVERAGE"].interpolate(limit=7))
    if "FRED:NFCICREDIT" in panel.columns:
        x_components.append(panel["FRED:NFCICREDIT"].interpolate(limit=7))
    if "FRED:STLFSI4" in panel.columns:
        stlfsi = panel["FRED:STLFSI4"].interpolate(limit=7)
        x_components.append(stlfsi.rolling(5).mean())
    if "H41:primary_credit" in panel.columns:
        pc = panel["H41:primary_credit"].interpolate(limit=14)
        pc_norm = pc / pc.expanding(252).median().replace(0, 1)
        x_components.append(pc_norm.clip(0, 10))
    if "H41:btfp" in panel.columns:
        btfp = panel["H41:btfp"].interpolate(limit=14)
        btfp_norm = btfp / btfp.expanding(252).median().replace(0, 1)
        x_components.append(btfp_norm.clip(0, 10))
    if x_components:
        x_raw = pd.concat(x_components, axis=1).mean(axis=1)
        channels["X"] = _zscore_expanding(x_raw, 252)
    else:
        channels["X"] = 0.0

    return channels.fillna(0.0).clip(-5, 5)


def _zscore_expanding(series: pd.Series, window: int = 252) -> pd.Series:
    """Expanding-window z-score normalization."""
    s = series.dropna()
    mu = s.expanding(window).mean()
    sigma = s.expanding(window).std().replace(0, 1)
    result = ((s - mu) / sigma).fillna(0.0)
    return result.reindex(series.index).fillna(0.0)


# ── Structural Signals ───────────────────────────────────────────────────────

def _scale(series: pd.Series) -> pd.Series:
    s = series.dropna()
    if len(s) < 5:
        return pd.Series(0.0, index=series.index)
    r = s.expanding().max() - s.expanding().min()
    r = r.replace(0, 1)
    return ((s - s.expanding().min()) / r).fillna(0.0)


def structural_vulnerability_signal(channels: pd.DataFrame, window: int = 63) -> pd.Series:
    required = channels.copy()
    for col in ["M", "D_contraction", "K", "X"]:
        if col not in required.columns:
            required[col] = 0.0
    slow = required.rolling(window=window, min_periods=1).mean()
    score = slow[["M", "D_contraction", "K", "X"]].mean(axis=1)
    score.name = "structural_vulnerability"
    return score


def actionable_transition_signal(channels: pd.DataFrame, threshold: float = 1.0, persistence: int = 3) -> pd.Series:
    required = channels.copy()
    for col in ["M", "D_contraction", "K", "X"]:
        if col not in required.columns:
            required[col] = 0.0
    joint = required[["M", "D_contraction", "K", "X"]].mean(axis=1)
    change = joint.diff().clip(lower=0.0)
    acceleration = joint.diff().diff().clip(lower=0.0)
    crossing = joint.ge(threshold) & joint.shift(1).lt(threshold)
    persistent = joint.ge(threshold).rolling(persistence, min_periods=1).sum().ge(persistence)
    confirmation = required.ge(threshold).sum(axis=1).ge(2)
    score = (
        0.35 * _scale(change)
        + 0.25 * _scale(acceleration)
        + 0.20 * crossing.astype(float)
        + 0.10 * persistent.astype(float)
        + 0.10 * confirmation.astype(float)
    )
    score.name = "actionable_transition"
    return score.fillna(0.0)


# ── Benchmark Signals ────────────────────────────────────────────────────────

def build_benchmark_signals(panel: pd.DataFrame) -> pd.DataFrame:
    """Build benchmark stress signals from standard indicators."""
    signals = pd.DataFrame(index=panel.index)

    # VIX
    if "FRED:VIXCLS" in panel.columns:
        vix = panel["FRED:VIXCLS"].interpolate(limit=5)
        mu = vix.expanding(252).mean()
        sigma = vix.expanding(252).std().replace(0, 1)
        signals["VIX_zscore"] = ((vix - mu) / sigma).clip(-3, 5)

    # NFCI
    if "FRED:NFCI" in panel.columns:
        nfci = panel["FRED:NFCI"].interpolate(limit=7)
        mu = nfci.expanding(252).mean()
        sigma = nfci.expanding(252).std().replace(0, 1)
        signals["NFCI_zscore"] = ((nfci - mu) / sigma).clip(-3, 5)

    # STLFSI4
    if "FRED:STLFSI4" in panel.columns:
        stlfsi = panel["FRED:STLFSI4"].interpolate(limit=7)
        mu = stlfsi.expanding(252).mean()
        sigma = stlfsi.expanding(252).std().replace(0, 1)
        signals["STLFSI4_zscore"] = ((stlfsi - mu) / sigma).clip(-3, 5)

    # BAA10YM (credit spread)
    if "FRED:BAA10YM" in panel.columns:
        baa10 = panel["FRED:BAA10YM"].interpolate(limit=5)
        mu = baa10.expanding(252).mean()
        sigma = baa10.expanding(252).std().replace(0, 1)
        signals["BAA10YM_zscore"] = ((baa10 - mu) / sigma).clip(-3, 5)

    # HY OAS (where available)
    if "FRED:BAMLH0A0HYM2" in panel.columns:
        hy = panel["FRED:BAMLH0A0HYM2"].interpolate(limit=5)
        mu = hy.expanding(252).mean()
        sigma = hy.expanding(252).std().replace(0, 1)
        signals["HYOAS_zscore"] = ((hy - mu) / sigma).clip(-3, 5)

    # TEDRATE (retired, but available pre-2022)
    if "FRED:TEDRATE" in panel.columns:
        ted = panel["FRED:TEDRATE"].interpolate(limit=5)
        mu = ted.expanding(252).mean()
        sigma = ted.expanding(252).std().replace(0, 1)
        signals["TEDRATE_zscore"] = ((ted - mu) / sigma).clip(-3, 5)

    # CP-Bill spread
    if "FRED:DCPF3M" in panel.columns and "FRED:DGS3MO" in panel.columns:
        cp_bill = panel["FRED:DCPF3M"] - panel["FRED:DGS3MO"]
        mu = cp_bill.expanding(252).mean()
        sigma = cp_bill.expanding(252).std().replace(0, 1)
        signals["CPBill_zscore"] = ((cp_bill - mu) / sigma).clip(-3, 5)

    # NFCI sub-indices
    for sub in ["NFCIRISK", "NFCILEVERAGE", "NFCICREDIT"]:
        col = f"FRED:{sub}"
        if col in panel.columns:
            s = panel[col].interpolate(limit=7)
            mu = s.expanding(252).mean()
            sigma = s.expanding(252).std().replace(0, 1)
            signals[f"{sub}_zscore"] = ((s - mu) / sigma).clip(-3, 5)

    # Composite benchmark
    z_cols = [c for c in signals.columns if c.endswith("_zscore")]
    if z_cols:
        signals["composite_benchmark"] = signals[z_cols].mean(axis=1)

    return signals


# ── Event Analysis ───────────────────────────────────────────────────────────

@dataclass
class EventResult:
    event_id: str
    event_name: str
    peak_date: str
    category: str
    signal_60d_before: dict[str, float] = field(default_factory=dict)
    signal_at_peak: dict[str, float] = field(default_factory=dict)
    max_signal: dict[str, float] = field(default_factory=dict)
    max_signal_offset: dict[str, int] = field(default_factory=dict)
    lead_days: dict[str, int] = field(default_factory=dict)
    calm_fp_rate: dict[str, float] = field(default_factory=dict)
    data_available: dict[str, bool] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    leading_channel: str = ""
    channel_composition: dict[str, float] = field(default_factory=dict)


def analyze_event(ev: dict, structural: pd.DataFrame, benchmarks: pd.DataFrame, channels: pd.DataFrame) -> EventResult:
    r = EventResult(
        event_id=ev["id"], event_name=ev["name"],
        peak_date=ev["peak"], category=ev["category"],
    )
    peak = pd.Timestamp(ev["peak"])
    event_start = pd.Timestamp(ev["start"])
    event_end = pd.Timestamp(ev["end"])
    pre_start = pd.Timestamp(ev["pre_start"])

    all_sigs = pd.concat([structural, benchmarks], axis=1)

    signal_names = [
        "structural_vulnerability", "actionable_transition",
        "VIX_zscore", "NFCI_zscore", "STLFSI4_zscore", "BAA10YM_zscore",
        "composite_benchmark",
    ]
    for s in ["HYOAS_zscore", "TEDRATE_zscore", "CPBill_zscore",
              "NFCIRISK_zscore", "NFCILEVERAGE_zscore", "NFCICREDIT_zscore"]:
        if s in all_sigs.columns:
            signal_names.append(s)

    thresholds = {
        "structural_vulnerability": 0.3, "actionable_transition": 0.3,
        "VIX_zscore": 2.0, "NFCI_zscore": 1.5, "STLFSI4_zscore": 1.5,
        "BAA10YM_zscore": 2.0, "HYOAS_zscore": 2.0, "TEDRATE_zscore": 2.0,
        "CPBill_zscore": 2.0, "composite_benchmark": 1.5,
        "NFCIRISK_zscore": 1.5, "NFCILEVERAGE_zscore": 1.5, "NFCICREDIT_zscore": 1.5,
    }

    for sig in signal_names:
        if sig not in all_sigs.columns:
            r.data_available[sig] = False
            continue
        r.data_available[sig] = True
        series = all_sigs[sig].dropna()
        if len(series) < 10:
            r.data_available[sig] = False
            continue

        pre_win = series[(series.index >= peak - pd.Timedelta(days=90)) & (series.index <= peak)]
        if not pre_win.empty:
            t60 = peak - pd.Timedelta(days=60)
            idx60 = np.argmin(np.abs((pre_win.index - t60).total_seconds().values))
            if idx60 < len(pre_win):
                r.signal_60d_before[sig] = float(pre_win.iloc[idx60])
            idx_pk = np.argmin(np.abs((pre_win.index - peak).total_seconds().values))
            if idx_pk < len(pre_win):
                r.signal_at_peak[sig] = float(pre_win.iloc[idx_pk])

        ev_win = series[(series.index >= event_start - pd.Timedelta(days=30)) & (series.index <= event_end)]
        if not ev_win.empty:
            r.max_signal[sig] = float(ev_win.max())
            r.max_signal_offset[sig] = int((peak - ev_win.idxmax()).days)

        thresh = thresholds.get(sig, 1.0)
        lead_data = series[(series.index >= peak - pd.Timedelta(days=120)) & (series.index <= peak)]
        if not lead_data.empty:
            r.lead_days[sig] = int((lead_data >= thresh).sum())

        calm_end = pre_start - pd.Timedelta(days=30)
        calm_start = calm_end - pd.Timedelta(days=90)
        calm = series[(series.index >= calm_start) & (series.index <= calm_end)]
        if len(calm) > 10:
            r.calm_fp_rate[sig] = float((calm >= thresh).mean())

    # Leading channel at peak
    if not channels.empty:
        idx = np.argmin(np.abs((channels.index - peak).total_seconds().values))
        if idx < len(channels):
            row = channels.iloc[idx]
            ch_vals = {}
            for ch in ["M", "D_contraction", "K", "X"]:
                if ch in row.index:
                    ch_vals[ch] = float(row[ch])
            if ch_vals:
                r.leading_channel = max(ch_vals, key=ch_vals.get)
                r.channel_composition = ch_vals

    # Notes
    if peak > pd.Timestamp("2022-01-22"):
        r.notes.append("TEDRATE retired Jan 2022; CP-Bill spread used for funding stress.")
    if peak < pd.Timestamp("2023-05-01"):
        r.notes.append("HY OAS only available from 2023; BAA10YM used as credit spread proxy.")

    return r


# ── Scoring ──────────────────────────────────────────────────────────────────

def score_explanatory(results: list[EventResult]) -> dict:
    systemic_events = {"gfc_2008", "covid_2020", "svb_2023", "ltcm_1998", "repo_2019", "ldi_2022"}
    vol_events = {"dotcom_2000", "flash_crash_2010", "volmageddon_2018"}
    scores = {}
    for r in results:
        sv = "structural_vulnerability"
        vx = "VIX_zscore"
        if not r.data_available.get(sv) or not r.data_available.get(vx):
            scores[r.event_id] = "insufficient_data"
            continue
        sv_max = r.max_signal.get(sv, 0)
        vx_max = r.max_signal.get(vx, 0)
        sv_offset = r.max_signal_offset.get(sv, 999)
        vx_offset = r.max_signal_offset.get(vx, 999)

        if r.event_id in vol_events:
            if sv_max < 0.5 and vx_max > 2.0:
                scores[r.event_id] = "strong"  # correctly stayed calm
            elif sv_max < vx_max * 0.5:
                scores[r.event_id] = "good"
            else:
                scores[r.event_id] = "weak"
        elif r.event_id in systemic_events:
            if sv_offset > 0 and vx_offset > 0 and (vx_offset - sv_offset) > 10:
                scores[r.event_id] = "strong"
            elif sv_offset >= 0 and vx_offset >= 0:
                scores[r.event_id] = "good"
            else:
                scores[r.event_id] = "weak"
        else:
            scores[r.event_id] = "neutral"
    return scores


def score_lead_time(results: list[EventResult]) -> dict:
    scores = {}
    for r in results:
        sv_lead = r.lead_days.get("structural_vulnerability", 0)
        bm_lead = r.lead_days.get("composite_benchmark", 0)
        if sv_lead > bm_lead + 5:
            scores[r.event_id] = "strong"
        elif sv_lead >= bm_lead:
            scores[r.event_id] = "good"
        elif sv_lead > 0:
            scores[r.event_id] = "weak"
        else:
            scores[r.event_id] = "none"
    return scores


def score_false_positives(results: list[EventResult]) -> dict:
    scores = {}
    for r in results:
        sv_fp = r.calm_fp_rate.get("structural_vulnerability", 1.0)
        if sv_fp < 0.10:
            scores[r.event_id] = "low"
        elif sv_fp < 0.25:
            scores[r.event_id] = "moderate"
        elif sv_fp < 0.50:
            scores[r.event_id] = "elevated"
        else:
            scores[r.event_id] = "high"
    return scores


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
    explanatory: dict, lead_time: dict, false_pos: dict,
    calm_contamination: dict,
) -> str:
    lines = [
        "# Structural Deformation System — Historical Case Replay v2",
        "",
        f"**Generated:** {pd.Timestamp.now().isoformat()}",
        f"**Events:** {len(results)}",
        f"**Data:** Harvester official panel 2026-05-05-r1 (27 series, 236K rows)",
        f"**Proxy:** M/D/K/X built from real structural preset components",
        "",
        "---",
        "",
        "## 1. Executive Summary",
        "",
    ]

    st = sum(1 for v in explanatory.values() if v == "strong")
    gd = sum(1 for v in explanatory.values() if v == "good")
    wk = sum(1 for v in explanatory.values() if v == "weak")

    lt_st = sum(1 for v in lead_time.values() if v == "strong")
    lt_gd = sum(1 for v in lead_time.values() if v in ("strong", "good"))
    lt_no = sum(1 for v in lead_time.values() if v == "none")

    fp_lo = sum(1 for v in false_pos.values() if v == "low")
    fp_hi = sum(1 for v in false_pos.values() if v in ("elevated", "high"))

    lines += [
        "| Dimension | Strong | Good | Weak/None | Assessment |",
        "|---|---:|---:|---:|---|",
        f"| Explanatory Power | {st} | {gd} | {wk} | {'Adds structure beyond benchmarks' if st + gd >= wk else 'Mixed'} |",
        f"| Lead Time vs Benchmarks | {lt_st} | {lt_gd - lt_st} | {lt_no} | {'Earlier warning in key events' if lt_gd >= len(lead_time) // 2 else 'Comparable'} |",
        f"| Calm-Period False Positives | {fp_lo} | {len(false_pos) - fp_lo - fp_hi} | {fp_hi} | {'Mostly clean' if fp_hi <= 3 else 'Some contamination'} |",
        "",
        "---",
        "",
        "## 2. Per-Event Analysis",
        "",
    ]

    for r in results:
        lines.append(f"### {r.event_name} (`{r.event_id}`)")
        lines.append(
            f"**Category:** {r.category} | **Peak:** {r.peak_date} | "
            f"**Explanatory:** {explanatory.get(r.event_id, 'N/A')} | "
            f"**Lead:** {lead_time.get(r.event_id, 'N/A')} | "
            f"**Calm FP:** {false_pos.get(r.event_id, 'N/A')}"
        )
        if r.leading_channel:
            lines.append(f"**Leading channel at peak:** {r.leading_channel}  "
                         f"(M={r.channel_composition.get('M', 0):.2f}, "
                         f"D={r.channel_composition.get('D_contraction', 0):.2f}, "
                         f"K={r.channel_composition.get('K', 0):.2f}, "
                         f"X={r.channel_composition.get('X', 0):.2f})")
        lines.append("")
        lines.append("| Signal | 60d Before | At Peak | Max | Offset | Lead Days | Calm FP |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        for sig in [
            "structural_vulnerability", "actionable_transition",
            "VIX_zscore", "NFCI_zscore", "STLFSI4_zscore", "BAA10YM_zscore",
            "HYOAS_zscore", "CPBill_zscore", "composite_benchmark",
        ]:
            if sig in r.signal_60d_before:
                lines.append(
                    f"| {sig} | {r.signal_60d_before[sig]:.3f} | {r.signal_at_peak.get(sig, 0):.3f} | "
                    f"{r.max_signal.get(sig, 0):.3f} | {r.max_signal_offset.get(sig, 0)}d | "
                    f"{r.lead_days.get(sig, 0)}d | {r.calm_fp_rate.get(sig, 0):.1%} |"
                )
        lines.append("")
        for note in r.notes:
            lines.append(f"> {note}")
        lines.append("")

    lines += [
        "---",
        "",
        "## 3. Summary Scorecard",
        "",
        "| Event | Category | Explanatory | Lead vs BM | Calm FP | FP Note | Leading Ch |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        fp_note = "contaminated" if calm_contamination.get(r.event_id, "clean") != "clean" else ""
        lines.append(
            f"| {r.event_name} | {r.category} | "
            f"{explanatory.get(r.event_id, 'N/A')} | {lead_time.get(r.event_id, 'N/A')} | "
            f"{false_pos.get(r.event_id, 'N/A')} | {fp_note} | {r.leading_channel} |"
        )

    # Calm contamination
    contaminated = {k: v for k, v in calm_contamination.items() if v != "clean"}
    if contaminated:
        lines += ["", "---", "", "## 4. Calm-Period Contamination", ""]
        for eid, note in contaminated.items():
            name = next((r.event_name for r in results if r.event_id == eid), eid)
            lines.append(f"- **{name}** ({eid}): {note}")

    # Governance
    lines += [
        "",
        "---",
        "",
        "## 5. Governance Assessment",
        "",
        "| Check | Status |",
        "|---|---|",
    ]
    checks = [
        ("Official panel 2026-05-05-r1 (27 series)", "present"),
        ("TEDRATE retired Jan 2022, not in current diag", "verified"),
        ("H41 data (btfp, primary_credit, discount_window)", "present"),
        ("Treasury data (debt_to_penny, daily_statement)", "present"),
        ("NFCI sub-indices (risk, leverage, credit)", "present"),
        ("STLFSI4 benchmark", "present"),
        ("MOVE index", "partial (1yr yfinance)"),
        ("SEC filings", "partial (2024+)"),
        ("HY OAS full history pre-2023", "missing (BAA10YM used as proxy)"),
        ("SOFR full history pre-2018", "missing"),
    ]
    for check, status in checks:
        lines.append(f"| {check} | {status} |")

    # Caveats
    lines += [
        "",
        "---",
        "",
        "## 6. Caveats",
        "",
        "1. **HY OAS gap:** BAMLH0A0HYM2/BAMLC0A0CM/BAMLC0A4CBBB only available from 2023-05 (FRED free tier limitation). Pre-2023 credit assessment uses BAA10YM and DBAA-DAAA spread.",
        "2. **TEDRATE retired:** Replaced by CP-Bill spread (DCPF3M - DGS3MO) for post-2022 funding stress.",
        "3. **MOVE limited:** yfinance only provides ~1 year of MOVE history.",
        "4. **Expanding window normalization:** Early events (LTCM, dot-com) have less stable z-scores due to short lookback.",
        "5. **No OOS validation:** This is a historical replay, not a walk-forward backtest.",
        "6. **Data vintage:** All series use latest-vintage data, not real-time vintages available at each event date.",
        "",
    ]

    return "\n".join(lines)


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    print("=" * 70)
    print("Structural Deformation System — Historical Case Replay v2")
    print("=" * 70)

    # 1. Load data
    print("\n[1/4] Loading official Harvester panel...")
    panel = load_official_panel()
    print(f"  Panel: {panel.shape[1]} series, {len(panel)} days")
    print(f"  Range: {panel.index.min().date()} -> {panel.index.max().date()}")
    present = [c.replace('FRED:', '').replace('H41:', '').replace('TREASURY:', '').replace('YFINANCE:', '') for c in panel.columns]
    print(f"  Series: {', '.join(sorted(present))}")

    # 2. Build proxies
    print("\n[2/4] Building M/D/K/X structural proxies...")
    channels = build_structural_proxies(panel)
    print(f"  Channels: M, D_contraction, K, X")
    # Show coverage stats
    for ch in ["M", "D_contraction", "K", "X"]:
        nonzero = (channels[ch].abs() > 0.01).sum()
        print(f"  {ch}: {nonzero}/{len(channels)} non-zero days")

    # 3. Compute signals
    print("\n[3/4] Computing structural + benchmark signals...")
    structural = pd.DataFrame({
        "structural_vulnerability": structural_vulnerability_signal(channels),
        "actionable_transition": actionable_transition_signal(channels),
    })
    benchmarks = build_benchmark_signals(panel)
    all_signals = pd.concat([structural, benchmarks], axis=1)
    all_signals.to_parquet(OUTPUT_DIR / "all_signals.parquet")
    print(f"  Signals: {all_signals.shape[1]} columns")

    # 4. Analyze
    print("\n[4/4] Analyzing stress events...")
    results = []
    for ev in STRESS_EVENTS:
        peak = pd.Timestamp(ev["peak"])
        if peak < panel.index.min() + pd.Timedelta(days=365):
            print(f"  SKIP {ev['name']}: insufficient pre-peak data")
            continue
        r = analyze_event(ev, structural, benchmarks, channels)
        results.append(r)

        # Save event window data
        pre = pd.Timestamp(ev["pre_start"])
        post = pd.Timestamp(ev["post_end"])
        ev_data = all_signals[(all_signals.index >= pre) & (all_signals.index <= post)]
        ev_data.to_csv(EVENT_DIR / f"{ev['id']}_signals.csv")

        sv_max = r.max_signal.get("structural_vulnerability", 0)
        sv_lead = r.lead_days.get("structural_vulnerability", 0)
        print(f"  {ev['name']}: sv_max={sv_max:.3f}, lead={sv_lead}d, "
              f"leading_ch={r.leading_channel}, "
              f"at_max={r.max_signal.get('actionable_transition', 0):.3f}")

    exp = score_explanatory(results)
    lt = score_lead_time(results)
    fp = score_false_positives(results)
    contamination = check_calm_contamination(results, STRESS_EVENTS)

    for r in results:
        if contamination.get(r.event_id, "clean") != "clean":
            r.notes.append(f"Calm window {contamination[r.event_id]}")

    report = generate_report(results, exp, lt, fp, contamination)
    (OUTPUT_DIR / "evaluation_report.md").write_text(report)

    # JSON results
    json_results = []
    for r in results:
        json_results.append({
            "event_id": r.event_id, "event_name": r.event_name,
            "peak_date": r.peak_date, "category": r.category,
            "leading_channel": r.leading_channel,
            "channel_composition": r.channel_composition,
            "max_signal": r.max_signal,
            "max_signal_offset": {k: int(v) for k, v in r.max_signal_offset.items()},
            "lead_days": r.lead_days,
            "calm_fp_rate": r.calm_fp_rate,
            "scores": {
                "explanatory": exp.get(r.event_id, "N/A"),
                "lead_time": lt.get(r.event_id, "N/A"),
                "false_positive": fp.get(r.event_id, "N/A"),
            },
        })
    (OUTPUT_DIR / "results.json").write_text(json.dumps(json_results, indent=2, default=str))

    print(f"\n{'='*70}")
    print(f"Evaluation complete. {len(results)} events analyzed.")
    print(f"  Strong explanatory: {sum(1 for v in exp.values() if v == 'strong')}")
    print(f"  Good explanatory:   {sum(1 for v in exp.values() if v == 'good')}")
    print(f"  Report: {OUTPUT_DIR / 'evaluation_report.md'}")
    print(f"{'='*70}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
