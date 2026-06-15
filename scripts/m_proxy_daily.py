#!/usr/bin/env python3
"""M Anchor Geometry — Daily Proxy.

Computes M from policy-market anchor gap components.

M captures the disconnect between:
  - Policy stance (short rates, yield curve)
  - Market pricing (inflation expectations, term premium)
  - Actor interpretation (curve shape, real rates)

Components:
  M_curve:      T10Y2Y (yield curve slope) — z-scored
  M_inflation:  T10YIE (10Y inflation expectations) — z-scored
  M_short_rate: DGS3MO (3M Treasury) — z-scored
  M_real_rate:  DGS3MO - T10YIE (real short rate proxy) — z-scored
  M_prime:      DPRIME (prime rate spread) — z-scored

M_anchor = mean of available components (z-scored)

States:
  M0_ANCHORED       — M_anchor near zero, no drift
  M1_MILD_DRIFT     — M_anchor |0.5| to |1.0|, mild anchor pressure
  M2_ANCHOR_STRESS  — M_anchor |1.0| to |1.5|, significant drift
  M3_ANCHOR_BREAK   — M_anchor > |1.5|, anchor breaking

Output: Output/m_proxy_daily/
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "Output" / "m_proxy_daily"
BP_PATH = ROOT / "Data" / "harvester" / "exports" / "latest" / "data" / "benchmark_panel.parquet"
ETF_PATH = ROOT / "Data" / "panels" / "cross_asset_daily_panel.parquet"

EVENTS = {
    "GFC 2008": ("2008-06-01", "2009-03-01"),
    "Flash Crash 2010": ("2010-04-01", "2010-07-01"),
    "Taper Tantrum 2013": ("2013-05-01", "2013-09-01"),
    "China Deval 2015": ("2015-07-01", "2015-10-01"),
    "Volmageddon 2018": ("2018-01-01", "2018-04-01"),
    "COVID 2020": ("2020-02-01", "2020-05-01"),
    "SVB 2023": ("2023-02-01", "2023-05-01"),
    "Carry Unwind 2024": ("2024-07-01", "2024-09-01"),
}


def rolling_z(s: pd.Series, w: int = 252) -> pd.Series:
    mu = s.rolling(w, min_periods=60).mean()
    sig = s.rolling(w, min_periods=60).std().replace(0, np.nan)
    return ((s - mu) / sig).clip(-5, 5)


def get_series(bp: pd.DataFrame, sid: str) -> pd.Series:
    s = bp[bp["series_id"] == sid].sort_values("date").drop_duplicates("date").set_index("date")["value"]
    return s


def build_m_components(bp: pd.DataFrame) -> pd.DataFrame:
    """Build M components from benchmark panel.
    
    Optimized M proxy using:
    - T10YIE change (inflation expectation dynamics)
    - Real rate change (policy vs inflation gap dynamics)
    - T10YIE (inflation expectations level)
    - T5YIE (5Y inflation expectations)
    """
    # Get raw series
    t10y2y_raw = get_series(bp, "FRED:T10Y2Y")
    t10yie_raw = get_series(bp, "FRED:T10YIE")
    t5yie_raw = get_series(bp, "FRED:T5YIE")
    dgs3mo_raw = get_series(bp, "FRED:DGS3MO")
    
    # Compute derived series
    real_rate_raw = dgs3mo_raw - t10yie_raw
    
    # Z-score all components
    t10y2y = rolling_z(t10y2y_raw)
    t10yie = rolling_z(t10yie_raw)
    t5yie = rolling_z(t5yie_raw)
    dgs3mo = rolling_z(dgs3mo_raw)
    real_rate = rolling_z(real_rate_raw)
    
    # Change components (20-day)
    t10yie_change = rolling_z(t10yie_raw.diff(20))
    real_rate_change = rolling_z(real_rate_raw.diff(20))
    
    # Optimized M proxy (OLS weights from optimization)
    # Best combination: T10YIE change + Real rate change
    m_anchor = 0.7 * t10yie_change + 0.3 * (-real_rate_change)
    
    # Rate of change (5d)
    m_anchor_delta = m_anchor.diff(5)
    
    df = pd.DataFrame({
        "m_anchor": m_anchor,
        "m_anchor_delta": m_anchor_delta,
        "m_t10y2y": t10y2y,
        "m_t10yie": t10yie,
        "m_t5yie": t5yie,
        "m_dgs3mo": dgs3mo,
        "m_real_rate": real_rate,
        "m_t10yie_change": t10yie_change,
        "m_real_rate_change": real_rate_change,
    }).dropna(subset=["m_anchor"])
    
    return df


def classify_state(row: pd.Series) -> dict:
    """Classify M state from component values."""
    anchor = row["m_anchor"]
    delta = row.get("m_anchor_delta", 0)
    
    # State machine
    if abs(anchor) < 0.5:
        state = "M0_ANCHORED"
        reason = "no anchor pressure"
        confidence = "high"
        allowed = "baseline market-space descriptor"
        forbidden = "none"
    elif abs(anchor) < 1.0:
        if delta > 0.3:
            state = "M1_MILD_DRIFT_UP"
            reason = "anchor drifting upward"
            confidence = "medium"
            allowed = "early watch: anchor pressure building"
            forbidden = "standalone trigger"
        elif delta < -0.3:
            state = "M1_MILD_DRIFT_DOWN"
            reason = "anchor drifting downward"
            confidence = "medium"
            allowed = "early watch: anchor pressure building"
            forbidden = "standalone trigger"
        else:
            state = "M1_MILD_DRIFT"
            reason = "mild anchor drift"
            confidence = "medium"
            allowed = "early watch: anchor pressure building"
            forbidden = "standalone trigger"
    elif abs(anchor) < 1.5:
        if anchor > 0:
            state = "M2_ANCHOR_STRESS_UP"
            reason = "significant anchor drift upward"
            confidence = "medium"
            allowed = "confirmation signal for D/K/X stress"
            forbidden = "standalone trigger"
        else:
            state = "M2_ANCHOR_STRESS_DOWN"
            reason = "significant anchor drift downward"
            confidence = "medium"
            allowed = "confirmation signal for D/K/X stress"
            forbidden = "standalone trigger"
    else:
        if anchor > 0:
            state = "M3_ANCHOR_BREAK_UP"
            reason = "anchor breaking upward"
            confidence = "high"
            allowed = "early warning: anchor geometry breaking"
            forbidden = "strategy input without D/K/X confirmation"
        else:
            state = "M3_ANCHOR_BREAK_DOWN"
            reason = "anchor breaking downward"
            confidence = "high"
            allowed = "early warning: anchor geometry breaking"
            forbidden = "strategy input without D/K/X confirmation"
    
    return {
        "state": state,
        "reason": reason,
        "confidence": confidence,
        "allowed": allowed,
        "forbidden": forbidden,
    }


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    
    print("Loading benchmark panel...")
    bp = pd.read_parquet(BP_PATH)
    bp["date"] = pd.to_datetime(bp["date"])
    print(f"  {len(bp):,} rows, {bp['series_id'].nunique()} series")
    
    print("Building M components...")
    df = build_m_components(bp)
    print(f"  {len(df)} observations, {df.index.min().strftime('%Y-%m-%d')} to {df.index.max().strftime('%Y-%m-%d')}")
    
    print("Classifying states...")
    states = []
    for idx, row in df.iterrows():
        state_info = classify_state(row)
        state_info["date"] = idx
        state_info["m_anchor"] = row["m_anchor"]
        state_info["m_anchor_delta"] = row.get("m_anchor_delta", np.nan)
        state_info["active_components"] = ",".join([
            c for c in ["m_curve", "m_inflation", "m_short_rate", "m_real_rate", "m_prime"]
            if not pd.isna(row.get(c))
        ])
        states.append(state_info)
    
    state_df = pd.DataFrame(states).set_index("date")
    
    # Save outputs
    print("\nSaving outputs...")
    
    # State history
    state_path = OUTPUT / "m_state_history.csv"
    state_df.to_csv(state_path)
    print(f"  {state_path}")
    
    # Component series
    comp_path = OUTPUT / "m_component_series.csv"
    df.to_csv(comp_path)
    print(f"  {comp_path}")
    
    # Generate report
    report_lines = ["# M Anchor Geometry — Daily Proxy Report\n"]
    report_lines.append(f"**Generated:** {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}\n")
    report_lines.append(f"**Observations:** {len(df)}\n")
    report_lines.append(f"**Date range:** {df.index.min().strftime('%Y-%m-%d')} to {df.index.max().strftime('%Y-%m-%d')}\n")
    report_lines.append(f"**Current state:** {state_df.iloc[-1]['state']}\n")
    report_lines.append(f"**Current M_anchor:** {state_df.iloc[-1]['m_anchor']:.4f}\n")
    report_lines.append("\n---\n\n")
    
    # State distribution
    report_lines.append("## 1. State Distribution\n\n")
    report_lines.append("| State | Count | Pct |\n")
    report_lines.append("|---|---:|---:|\n")
    state_counts = state_df["state"].value_counts()
    for state, count in state_counts.items():
        pct = count / len(state_df) * 100
        report_lines.append(f"| {state} | {count} | {pct:.1f}% |\n")
    
    report_lines.append("\n## 2. Event Characterization\n\n")
    report_lines.append("| Event | Dominant State | Max |M_anchor| |\n")
    report_lines.append("|---|---|---:|\n")
    for event_name, (start, end) in EVENTS.items():
        mask = (state_df.index >= start) & (state_df.index <= end)
        event_states = state_df[mask]
        if len(event_states) > 0:
            dominant = event_states["state"].mode().iloc[0] if len(event_states["state"].mode()) > 0 else "N/A"
            max_abs = event_states["m_anchor"].abs().max()
            report_lines.append(f"| {event_name} | {dominant} | {max_abs:.3f} |\n")
    
    report_lines.append("\n## 3. Recent State History (last 30 days)\n\n")
    report_lines.append("```")
    recent = state_df.iloc[-30:][["state", "m_anchor", "m_anchor_delta"]]
    report_lines.append(recent.to_string())
    report_lines.append("```\n")
    
    report_path = OUTPUT / "M_PROXY_REPORT.md"
    with open(report_path, "w") as f:
        f.write("\n".join(report_lines))
    print(f"  {report_path}")
    
    # Event state paths
    event_paths = {}
    for event_name, (start, end) in EVENTS.items():
        mask = (state_df.index >= start) & (state_df.index <= end)
        event_states = state_df[mask]
        if len(event_states) > 0:
            event_paths[event_name] = {
                "dominant_state": event_states["state"].mode().iloc[0] if len(event_states["state"].mode()) > 0 else "N/A",
                "path": " → ".join(event_states["state"].tolist()),
                "max_m_anchor": float(event_states["m_anchor"].abs().max()),
                "distribution": event_states["state"].value_counts().to_dict(),
            }
    
    event_path = OUTPUT / "m_event_state_paths.json"
    with open(event_path, "w") as f:
        json.dump(event_paths, f, indent=2, default=str)
    print(f"  {event_path}")
    
    # Summary stats
    print("\n=== Summary ===")
    print(f"Current state: {state_df.iloc[-1]['state']}")
    print(f"Current M_anchor: {state_df.iloc[-1]['m_anchor']:.4f}")
    print(f"State distribution:")
    for state, count in state_counts.items():
        print(f"  {state}: {count} ({count/len(state_df)*100:.1f}%)")
    
    print("\nDone.")


if __name__ == "__main__":
    main()
