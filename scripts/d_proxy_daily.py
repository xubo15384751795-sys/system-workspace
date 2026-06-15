#!/usr/bin/env python3
"""D Path Geometry — Daily Proxy.

Computes D from funding/credit path feasibility components.

D captures the disconnect between:
  - Funding access (SOFR-IORB spread, prime rate)
  - Credit conditions (NFCI, credit spreads)
  - Liquidation path feasibility (bank credit, leverage)

Components:
  D_funding:    SOFR-IORB spread (funding stress) — z-scored
  D_credit:     NFCI (financial conditions) — z-scored
  D_leverage:   NFCI Leverage sub-index — z-scored
  D_spread_hy:  BAMLH0A0HYM2 (HY spread) — z-scored
  D_spread_ig:  BAMLC0A4CBBB (IG spread) — z-scored
  D_bank:       TOTBKCR (bank credit growth) — z-scored, inverted

D_path = mean of available components (z-scored)

States:
  D0_CLEAR         — D_path near zero, clear path
  D1_MILD_STRESS   — D_path |0.5| to |1.0|, mild path stress
  D2_PATH_STRESS   — D_path |1.0| to |1.5|, significant stress
  D3_PATH_BLOCKED  — D_path > |1.5|, path blocked

Output: Output/d_proxy_daily/
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "Output" / "d_proxy_daily"
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


def build_d_components(bp: pd.DataFrame) -> pd.DataFrame:
    """Build D components from benchmark panel."""
    # Funding stress (SOFR-IORB spread)
    sofr_iorb = rolling_z(get_series(bp, "DERIVED:SOFR_IORB_SPREAD"))
    
    # Financial conditions (NFCI)
    nfci = rolling_z(get_series(bp, "FRED:NFCI"))
    
    # Leverage sub-index
    nfci_leverage = rolling_z(get_series(bp, "FRED:NFCILEVERAGE"))
    
    # Credit spreads (only available from 2023)
    hy_spread = rolling_z(get_series(bp, "FRED:BAMLH0A0HYM2"))
    ig_spread = rolling_z(get_series(bp, "FRED:BAMLC0A4CBBB"))
    
    # Bank credit growth (inverted — high growth = loose conditions)
    totbkcr = get_series(bp, "FRED:TOTBKCR")
    totbkcr_growth = totbkcr.pct_change(20)  # 20-day growth rate
    totbkcr_z = rolling_z(totbkcr_growth)
    
    # Combine components
    d_components = pd.DataFrame({
        "d_funding": sofr_iorb,
        "d_credit": nfci,
        "d_leverage": nfci_leverage,
        "d_spread_hy": hy_spread,
        "d_spread_ig": ig_spread,
        "d_bank": totbkcr_z,
    })
    
    # D_path = mean of available components
    d_path = d_components.mean(axis=1, skipna=True)
    
    # Rate of change (5d)
    d_path_delta = d_path.diff(5)
    
    df = pd.DataFrame({
        "d_path": d_path,
        "d_path_delta": d_path_delta,
        "d_funding": sofr_iorb,
        "d_credit": nfci,
        "d_leverage": nfci_leverage,
        "d_spread_hy": hy_spread,
        "d_spread_ig": ig_spread,
        "d_bank": totbkcr_z,
    }).dropna(subset=["d_path"])
    
    return df


def classify_state(row: pd.Series) -> dict:
    """Classify D state from component values."""
    path = row["d_path"]
    delta = row.get("d_path_delta", 0)
    
    # State machine
    if abs(path) < 0.5:
        state = "D0_CLEAR"
        reason = "no path stress"
        confidence = "high"
        allowed = "baseline market-space descriptor"
        forbidden = "none"
    elif abs(path) < 1.0:
        if delta > 0.3:
            state = "D1_MILD_STRESS_UP"
            reason = "path stress building"
            confidence = "medium"
            allowed = "early watch: path pressure building"
            forbidden = "standalone trigger"
        elif delta < -0.3:
            state = "D1_MILD_STRESS_DOWN"
            reason = "path stress easing"
            confidence = "medium"
            allowed = "early watch: path pressure easing"
            forbidden = "standalone trigger"
        else:
            state = "D1_MILD_STRESS"
            reason = "mild path stress"
            confidence = "medium"
            allowed = "early watch: path pressure building"
            forbidden = "standalone trigger"
    elif abs(path) < 1.5:
        if path > 0:
            state = "D2_PATH_STRESS_UP"
            reason = "significant path stress (tightening)"
            confidence = "medium"
            allowed = "confirmation signal for M/K/X stress"
            forbidden = "standalone trigger"
        else:
            state = "D2_PATH_STRESS_DOWN"
            reason = "significant path stress (easing)"
            confidence = "medium"
            allowed = "confirmation signal for M/K/X stress"
            forbidden = "standalone trigger"
    else:
        if path > 0:
            state = "D3_PATH_BLOCKED_UP"
            reason = "path blocked (severe tightening)"
            confidence = "high"
            allowed = "early warning: path geometry breaking"
            forbidden = "strategy input without M/K/X confirmation"
        else:
            state = "D3_PATH_BLOCKED_DOWN"
            reason = "path blocked (severe easing)"
            confidence = "high"
            allowed = "early warning: path geometry breaking"
            forbidden = "strategy input without M/K/X confirmation"
    
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
    
    print("Building D components...")
    df = build_d_components(bp)
    print(f"  {len(df)} observations, {df.index.min().strftime('%Y-%m-%d')} to {df.index.max().strftime('%Y-%m-%d')}")
    
    print("Classifying states...")
    states = []
    for idx, row in df.iterrows():
        state_info = classify_state(row)
        state_info["date"] = idx
        state_info["d_path"] = row["d_path"]
        state_info["d_path_delta"] = row.get("d_path_delta", np.nan)
        state_info["active_components"] = ",".join([
            c for c in ["d_funding", "d_credit", "d_leverage", "d_spread_hy", "d_spread_ig", "d_bank"]
            if not pd.isna(row.get(c))
        ])
        states.append(state_info)
    
    state_df = pd.DataFrame(states).set_index("date")
    
    # Save outputs
    print("\nSaving outputs...")
    
    # State history
    state_path = OUTPUT / "d_state_history.csv"
    state_df.to_csv(state_path)
    print(f"  {state_path}")
    
    # Component series
    comp_path = OUTPUT / "d_component_series.csv"
    df.to_csv(comp_path)
    print(f"  {comp_path}")
    
    # Generate report
    report_lines = ["# D Path Geometry — Daily Proxy Report\n"]
    report_lines.append(f"**Generated:** {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}\n")
    report_lines.append(f"**Observations:** {len(df)}\n")
    report_lines.append(f"**Date range:** {df.index.min().strftime('%Y-%m-%d')} to {df.index.max().strftime('%Y-%m-%d')}\n")
    report_lines.append(f"**Current state:** {state_df.iloc[-1]['state']}\n")
    report_lines.append(f"**Current D_path:** {state_df.iloc[-1]['d_path']:.4f}\n")
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
    report_lines.append("| Event | Dominant State | Max |D_path| |\n")
    report_lines.append("|---|---|---:|\n")
    for event_name, (start, end) in EVENTS.items():
        mask = (state_df.index >= start) & (state_df.index <= end)
        event_states = state_df[mask]
        if len(event_states) > 0:
            dominant = event_states["state"].mode().iloc[0] if len(event_states["state"].mode()) > 0 else "N/A"
            max_abs = event_states["d_path"].abs().max()
            report_lines.append(f"| {event_name} | {dominant} | {max_abs:.3f} |\n")
    
    report_lines.append("\n## 3. Recent State History (last 30 days)\n\n")
    report_lines.append("```")
    recent = state_df.iloc[-30:][["state", "d_path", "d_path_delta"]]
    report_lines.append(recent.to_string())
    report_lines.append("```\n")
    
    report_path = OUTPUT / "D_PROXY_REPORT.md"
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
                "max_d_path": float(event_states["d_path"].abs().max()),
                "distribution": event_states["state"].value_counts().to_dict(),
            }
    
    event_path = OUTPUT / "d_event_state_paths.json"
    with open(event_path, "w") as f:
        json.dump(event_paths, f, indent=2, default=str)
    print(f"  {event_path}")
    
    # Summary stats
    print("\n=== Summary ===")
    print(f"Current state: {state_df.iloc[-1]['state']}")
    print(f"Current D_path: {state_df.iloc[-1]['d_path']:.4f}")
    print(f"State distribution:")
    for state, count in state_counts.items():
        print(f"  {state}: {count} ({count/len(state_df)*100:.1f}%)")
    
    print("\nDone.")


if __name__ == "__main__":
    main()
