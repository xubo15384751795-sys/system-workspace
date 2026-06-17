#!/usr/bin/env python3
"""K Curvature State Machine.

Restructures K from standalone trigger to curvature state descriptor
for market-space description and M/D/X state modification.

States:
  K0_NORMAL              — no curvature pressure
  K1_COMPRESSION         — low vol complacency (K_core negative)
  K2_CORE_PRESSURE       — vol surface distortion (K_core elevated)
  K3_CROSS_CONFIRMATION  — cross-asset stress confirms K_core
  K4_CURVATURE_BREAK     — both K_core and K_cross elevated
  K5_REPAIR              — K_core declining from elevated

Output: Output/k_state_machine/
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "Output" / "k_state_machine"
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


def get_etf(etf: pd.DataFrame, sym: str) -> pd.Series:
    s = etf[etf["symbol"] == sym].sort_values("date").set_index("date")["close"]
    return s


def build_k_components(bp: pd.DataFrame, etf: pd.DataFrame) -> pd.DataFrame:
    """Build K_core, K_cross, and derived metrics."""
    skew = rolling_z(get_series(bp, "CBOE:SKEW"))
    vvix = rolling_z(get_series(bp, "CBOE:VVIX"))
    vix9d = rolling_z(get_series(bp, "CBOE:VIX9D"))
    vix3m = rolling_z(get_series(bp, "CBOE:VIX3M"))
    butterfly = rolling_z(vix9d - vix3m)

    k_core = pd.concat([skew, vvix, butterfly], axis=1).mean(axis=1, skipna=True)

    spy = get_etf(etf, "SPY")
    tlt = get_etf(etf, "TLT")
    hyg = get_etf(etf, "HYG")
    gld = get_etf(etf, "GLD")
    slv = get_etf(etf, "SLV")
    kre = get_etf(etf, "KRE")

    corr_spy_tlt = spy.pct_change().rolling(60).corr(tlt.pct_change())
    sectors = {sym: get_etf(etf, sym) for sym in ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]}
    sector_rets = pd.DataFrame({sym: s.pct_change() for sym, s in sectors.items()})
    sector_disp = sector_rets.rolling(20).std().mean(axis=1) * np.sqrt(252)
    spy_dd = (spy - spy.cummax()) / spy.cummax()
    dd_vel_5 = spy_dd.rolling(5).min()
    ratio_hyg_tlt = hyg / tlt

    k_cross = pd.DataFrame({
        "corr_breakdown": -corr_spy_tlt,
        "sector_divergence": rolling_z(sector_disp),
        "drawdown_speed": dd_vel_5,
        "credit_stress": -rolling_z(ratio_hyg_tlt),
    }).mean(axis=1, skipna=True)

    # K_selective = mean of all components
    k_selective = pd.concat([k_core.rename("core"), k_cross.rename("cross")], axis=1).mean(axis=1, skipna=True)

    # Rate of change (5d)
    k_core_delta = k_core.diff(5)

    df = pd.DataFrame({
        "k_core": k_core,
        "k_cross": k_cross,
        "k_selective": k_selective,
        "k_core_delta": k_core_delta,
    }).dropna(subset=["k_core"])

    return df


def classify_state(row: pd.Series) -> dict:
    """Classify K state from component values."""
    core = row["k_core"]
    cross = row["k_cross"]
    delta = row.get("k_core_delta", 0)

    # State machine
    if core < -0.5:
        state = "K1_COMPRESSION"
        reason = "low vol complacency"
        confidence = "high"
        allowed = "market-space descriptor: complacent regime"
        forbidden = "strategy input, directional claim"
    elif cross >= 1.0 and core >= 1.0:
        state = "K4_CURVATURE_BREAK"
        reason = "core + cross-asset stress confirmed"
        confidence = "high"
        allowed = "early warning: curvature geometry breaking"
        forbidden = "strategy input without M/D/X confirmation"
    elif cross >= 0.5 and core >= 0.5:
        state = "K3_CROSS_CONFIRMATION"
        reason = "cross-asset stress confirming core pressure"
        confidence = "medium"
        allowed = "confirmation signal for M/D/X stress"
        forbidden = "standalone trigger"
    elif core >= 1.0:
        if delta < -0.3:
            state = "K5_REPAIR"
            reason = "core elevated but declining"
            confidence = "medium"
            allowed = "market-space descriptor: repair phase"
            forbidden = "strategy input, new position initiation"
        else:
            state = "K2_CORE_PRESSURE"
            reason = "vol surface distorted"
            confidence = "medium"
            allowed = "early watch: curvature pressure building"
            forbidden = "standalone trigger, strategy input"
    else:
        state = "K0_NORMAL"
        reason = "no curvature pressure"
        confidence = "high"
        allowed = "baseline market-space descriptor"
        forbidden = "none"

    return {
        "state": state,
        "active_components": _active_components(core, cross),
        "reason_code": reason,
        "confidence": confidence,
        "allowed_use": allowed,
        "forbidden_use": forbidden,
    }


def _active_components(core: float, cross: float) -> list[str]:
    active = []
    if abs(core) > 0.5:
        active.append("K_core")
    if abs(cross) > 0.3:
        active.append("K_cross")
    return active or ["none"]


def build_state_history(df: pd.DataFrame) -> pd.DataFrame:
    """Build full state history."""
    records = []
    for idx, row in df.iterrows():
        cls = classify_state(row)
        records.append({
            "date": idx,
            "k_core": round(row["k_core"], 4),
            "k_cross": round(row["k_cross"], 4),
            "k_selective": round(row["k_selective"], 4),
            "k_core_delta": round(row.get("k_core_delta", 0), 4),
            **{k: v for k, v in cls.items()},
        })
    return pd.DataFrame(records)


def characterize_events(history: pd.DataFrame) -> list[dict]:
    """Characterize each event with K state path."""
    results = []
    for name, (start, end) in EVENTS.items():
        window = history[(history["date"] >= start) & (history["date"] <= end)]
        if window.empty:
            results.append({"event": name, "state_path": ["NO_DATA"], "dominant_state": "NO_DATA"})
            continue

        states = window["state"].tolist()
        # Get dominant state (most frequent)
        from collections import Counter
        state_counts = Counter(states)
        dominant = state_counts.most_common(1)[0][0]

        # Get state transitions
        transitions = [states[0]]
        for s in states[1:]:
            if s != transitions[-1]:
                transitions.append(s)

        results.append({
            "event": name,
            "start": start,
            "end": end,
            "dominant_state": dominant,
            "state_path": transitions,
            "total_days": len(window),
            "state_distribution": dict(state_counts),
            "max_k_core": round(window["k_core"].max(), 3),
            "max_k_cross": round(window["k_cross"].max(), 3),
        })

    return results


def interaction_analysis(history: pd.DataFrame, bp: pd.DataFrame) -> pd.DataFrame:
    """Analyze how K state interacts with M/D/X."""
    # Load M/D/X from benchmark panel
    # M ≈ DFF-T10Y2Y gap, D ≈ NFCI, X ≈ bank credit growth
    dff = rolling_z(get_series(bp, "FRED:DFF"))
    t10y2y = rolling_z(get_series(bp, "FRED:T10Y2Y"))
    m_proxy = rolling_z(dff - t10y2y)

    nfci = rolling_z(get_series(bp, "FRED:NFCI"))

    totbkcr = rolling_z(get_series(bp, "FRED:TOTBKCR"))

    interactions = pd.DataFrame({
        "M_proxy": m_proxy,
        "D_proxy": nfci,
        "X_proxy": totbkcr,
        "k_state": history.set_index("date")["state"],
        "k_core": history.set_index("date")["k_core"],
        "k_cross": history.set_index("date")["k_cross"],
    }).dropna()

    # Compute average M/D/X values by K state
    matrix = interactions.groupby("k_state").agg({
        "M_proxy": ["mean", "std", "count"],
        "D_proxy": ["mean", "std", "count"],
        "X_proxy": ["mean", "std", "count"],
        "k_core": "mean",
        "k_cross": "mean",
    }).round(3)

    return matrix


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)

    print("Loading data...")
    bp = pd.read_parquet(BP_PATH)
    bp["date"] = pd.to_datetime(bp["date"])
    etf = pd.read_parquet(ETF_PATH)
    etf["date"] = pd.to_datetime(etf["date"])

    print("Building K components...")
    k_df = build_k_components(bp, etf)
    print(f"  {len(k_df)} observations")

    print("Building state history...")
    history = build_state_history(k_df)
    print(f"  {len(history)} states classified")

    print("Characterizing events...")
    event_paths = characterize_events(history)

    print("Running interaction analysis...")
    interaction = interaction_analysis(history, bp)

    # Write state history
    history.to_csv(OUTPUT / "k_state_history.csv", index=False)
    print(f"Wrote: {OUTPUT / 'k_state_history.csv'}")

    # Write event paths
    with (OUTPUT / "k_event_state_paths.json").open("w") as f:
        json.dump(event_paths, f, indent=2, default=str)
    print(f"Wrote: {OUTPUT / 'k_event_state_paths.json'}")

    # Write interaction matrix
    interaction.to_csv(OUTPUT / "k_interaction_matrix.csv")
    print(f"Wrote: {OUTPUT / 'k_interaction_matrix.csv'}")

    # Generate reports
    generate_registry_update(history, k_df)
    generate_state_machine_report(history, event_paths, interaction, k_df)

    print("\nDone.")


def generate_registry_update(history: pd.DataFrame, k_df: pd.DataFrame) -> None:
    """Generate K registry update report."""
    # Current state
    last = history.iloc[-1]

    lines = [
        "# K Registry Update",
        "",
        f"**Generated:** {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "---",
        "",
        "## Component Status",
        "",
        "| Component | Status | Strategy Input | Market Space Descriptor | Reason |",
        "|---|---|---|---|---|",
        "| K_selective | STATE_DESCRIPTOR_ONLY | ❌ Forbidden | ✅ Allowed | Unique info 82.5%, but forward return failed (excess -0.21%) |",
        "| K_core | BROAD_CURVATURE_PRESSURE | ❌ Forbidden standalone | ✅ Allowed | High trigger count, not standalone signal |",
        "| K_cross | CROSS_ASSET_CONFIRMATION | ❌ Forbidden standalone | ✅ Allowed | Low sensitivity, confirmation only |",
        "",
        "## Current State",
        "",
        f"- **State:** {last['state']}",
        f"- **K_core:** {last['k_core']:.3f}",
        f"- **K_cross:** {last['k_cross']:.3f}",
        f"- **Reason:** {last['reason_code']}",
        f"- **Confidence:** {last['confidence']}",
        f"- **Allowed:** {last['allowed_use']}",
        f"- **Forbidden:** {last['forbidden_use']}",
        "",
        "## Why K_selective Cannot Be Strategy Input",
        "",
        "1. **Forward return failed:** K_core≥2.0 trigger vs quiet: excess -0.21%",
        "2. **High trigger count:** 56 triggers at z≥2.0, many non-crisis periods",
        "3. **K_cross too insensitive:** Only fires during GFC/COVID, misses Volmageddon/SVB",
        "4. **Differentiation ≠ signal:** 82.5% unique info, but that info doesn't predict returns",
        "",
        "## K_core vs K_cross Usage",
        "",
        "| Component | Use | Not Use |",
        "|---|---|---|",
        "| K_core | Early watch: vol surface distortion building | Standalone trigger, strategy input |",
        "| K_cross | Confirmation: cross-asset stress aligning with core | Standalone trigger, low-sensitivity detector |",
        "| K_selective | Market-space descriptor: overall curvature state | Strategy input, directional claim |",
        "",
        "## K State Descriptions",
        "",
        "| State | Meaning | Early Watch? | Confirmation? |",
        "|---|---|---|---|",
        "| K0_NORMAL | No curvature pressure | — | — |",
        "| K1_COMPRESSION | Low vol complacency | ✅ | — |",
        "| K2_CORE_PRESSURE | Vol surface distorted | ✅ | — |",
        "| K3_CROSS_CONFIRMATION | Cross-asset stress confirming | ✅ | ✅ |",
        "| K4_CURVATURE_BREAK | Core + cross both elevated | ✅ | ✅ |",
        "| K5_REPAIR | Core elevated but declining | — | ✅ |",
        "",
    ]

    (OUTPUT / "K_REGISTRY_UPDATE.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote: {OUTPUT / 'K_REGISTRY_UPDATE.md'}")


def generate_state_machine_report(
    history: pd.DataFrame,
    event_paths: list[dict],
    interaction: pd.DataFrame,
    k_df: pd.DataFrame,
) -> None:
    """Generate the main state machine report."""
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    last = history.iloc[-1]

    # State distribution
    state_dist = history["state"].value_counts()

    lines = [
        "# K Curvature State Machine Report",
        "",
        f"**Generated:** {now}",
        f"**Observations:** {len(history)}",
        f"**Current state:** {last['state']}",
        "",
        "---",
        "",
        "## 1. State Distribution",
        "",
        "| State | Count | Pct |",
        "|---|---:|---:|",
    ]
    for state, count in state_dist.items():
        pct = count / len(history) * 100
        lines.append(f"| {state} | {count} | {pct:.1f}% |")

    lines += [
        "",
        "## 2. Event Characterization",
        "",
        "| Event | Dominant State | Path | Max K_core | Max K_cross |",
        "|---|---|---|---:|---:|",
    ]
    for ev in event_paths:
        path_str = " → ".join(ev["state_path"][:5])
        if len(ev["state_path"]) > 5:
            path_str += " → ..."
        lines.append(
            f"| {ev['event']} | {ev['dominant_state']} | {path_str} | "
            f"{ev.get('max_k_core', '?')} | {ev.get('max_k_cross', '?')} |"
        )

    lines += [
        "",
        "## 3. Event Details",
        "",
    ]
    for ev in event_paths:
        lines += [
            f"### {ev['event']}",
            f"- Dominant: {ev['dominant_state']}",
            f"- Path: {' → '.join(ev['state_path'])}",
            f"- Max K_core: {ev.get('max_k_core', '?')}, Max K_cross: {ev.get('max_k_cross', '?')}",
            f"- Distribution: {ev.get('state_distribution', {})}",
            "",
        ]

    lines += [
        "## 4. Interaction Matrix",
        "",
        "How K state relates to M/D/X:",
        "",
    ]

    if not interaction.empty:
        # Flatten multi-index
        flat = interaction.copy()
        flat.columns = [f"{c[0]}_{c[1]}" if c[1] else c[0] for c in flat.columns]
        lines += [
            "| K State | M mean | M std | D mean | D std | X mean | X std | K_core mean | K_cross mean | Count |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for state in sorted(flat.index):
            r = flat.loc[state]
            lines.append(
                f"| {state} | {r.get('M_proxy_mean', 0):.2f} | {r.get('M_proxy_std', 0):.2f} | "
                f"{r.get('D_proxy_mean', 0):.2f} | {r.get('D_proxy_std', 0):.2f} | "
                f"{r.get('X_proxy_mean', 0):.2f} | {r.get('X_proxy_std', 0):.2f} | "
                f"{r.get('k_core_mean', 0):.2f} | {r.get('k_cross_mean', 0):.2f} | "
                f"{int(r.get('M_proxy_count', 0))} |"
            )

    lines += [
        "",
        "## 5. How K Modifies M/D/X",
        "",
        "| M/D/X State | K State | Modification |",
        "|---|---|---|",
        "| M high (anchor drift) | K2/K3/K4 | Anchor drift WITH curvature stress → higher watch priority |",
        "| D high (credit stress) | K3/K4 | Credit stress WITH cross-asset confirmation → more credible |",
        "| X high (leverage) | K4 | Leverage accumulation WITH curvature break → structural risk |",
        "| M/D/X normal | K1 | Complacency → monitor for hidden accumulation |",
        "| M/D/X normal | K0 | Normal — no modification needed |",
        "",
        "## 6. K's Role in Daily Brief",
        "",
        "K is displayed as:",
        "- **K Curvature State:** (current state name)",
        "- **NOT a strategy input**",
        "- **Use:** market-space descriptor / qualifier for M/D/X",
        "- **K should NOT appear in primary readout**",
        "- **K should appear in 'What to watch' section**",
        "",
        "## 7. Answers",
        "",
        "**Why can't K_selective be a strategy input?**",
        "Forward return excess is -0.21%. 82.5% unique info doesn't predict returns.",
        "",
        "**What are K_core and K_cross used for?**",
        "K_core = early watch (vol surface distortion). K_cross = confirmation (cross-asset stress).",
        "",
        "**Which states are early watch vs confirmation?**",
        "Early watch: K1, K2. Confirmation: K3, K4, K5.",
        "",
        "**How does K modify M/D/X?**",
        "K acts as a state qualifier. M high + K pressure = more urgent. D stress + K confirmation = more credible.",
        "",
        "**Should K return to primary readout?**",
        "No. K should be secondary — it describes the curvature space, not the primary deformation signal.",
    ]

    (OUTPUT / "K_STATE_MACHINE_REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote: {OUTPUT / 'K_STATE_MACHINE_REPORT.md'}")


if __name__ == "__main__":
    main()
