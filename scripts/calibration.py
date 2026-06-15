#!/usr/bin/env python3
"""Calibration — Phase 3 of Empirical Validation.

Estimates model parameters for K/D/M state machines:
1. State threshold estimation
2. Transition probability estimation
3. State distribution fitting

Output: Output/calibration/
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "Output" / "calibration"


def load_states():
    """Load all state histories."""
    k_states = pd.read_csv(ROOT / "Output" / "k_state_machine" / "k_state_history.csv", index_col="date", parse_dates=True)
    m_states = pd.read_csv(ROOT / "Output" / "m_proxy_daily" / "m_state_history.csv", index_col="date", parse_dates=True)
    d_states = pd.read_csv(ROOT / "Output" / "d_proxy_daily" / "d_state_history.csv", index_col="date", parse_dates=True)
    return k_states, m_states, d_states


def estimate_transition_matrix(states_series):
    """Estimate transition probability matrix from state series."""
    states = states_series.values
    unique_states = sorted(set(states))
    n_states = len(unique_states)
    state_to_idx = {s: i for i, s in enumerate(unique_states)}
    
    # Count transitions
    counts = np.zeros((n_states, n_states))
    for i in range(len(states) - 1):
        from_idx = state_to_idx[states[i]]
        to_idx = state_to_idx[states[i + 1]]
        counts[from_idx, to_idx] += 1
    
    # Normalize
    row_sums = counts.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1
    trans_matrix = counts / row_sums
    
    return {
        "states": unique_states,
        "matrix": trans_matrix.tolist(),
        "counts": counts.tolist(),
        "row_sums": row_sums.flatten().tolist(),
    }


def estimate_state_durations(states_series):
    """Estimate average duration of each state."""
    states = states_series.values
    unique_states = sorted(set(states))
    
    durations = {}
    for state in unique_states:
        # Find runs of this state
        is_state = (states == state).astype(int)
        runs = []
        current_run = 0
        for v in is_state:
            if v == 1:
                current_run += 1
            else:
                if current_run > 0:
                    runs.append(current_run)
                current_run = 0
        if current_run > 0:
            runs.append(current_run)
        
        if runs:
            durations[state] = {
                "mean": round(np.mean(runs), 2),
                "median": round(np.median(runs), 2),
                "std": round(np.std(runs), 2),
                "min": int(np.min(runs)),
                "max": int(np.max(runs)),
                "n_runs": len(runs),
            }
    
    return durations


def estimate_state_returns(k_states, spy_ret_20d):
    """Estimate average returns by K state."""
    common = k_states.index.intersection(spy_ret_20d.dropna().index)
    
    results = {}
    for state in sorted(k_states["state"].unique()):
        mask = k_states.loc[common, "state"] == state
        returns = spy_ret_20d.loc[common][mask].dropna()
        if len(returns) > 10:
            results[state] = {
                "n": len(returns),
                "mean": round(returns.mean(), 6),
                "std": round(returns.std(), 6),
                "sharpe": round(returns.mean() / returns.std(), 4) if returns.std() > 0 else 0,
                "median": round(returns.median(), 6),
                "min": round(returns.min(), 6),
                "max": round(returns.max(), 6),
            }
    
    return results


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    
    print("Loading data...")
    k_states, m_states, d_states = load_states()
    
    # Load SPY for return analysis
    etf = pd.read_parquet(ROOT / "Data" / "panels" / "cross_asset_daily_panel.parquet")
    spy = etf[etf["symbol"] == "SPY"].drop_duplicates(subset="date", keep="last")
    spy["date"] = pd.to_datetime(spy["date"])
    spy = spy.set_index("date")["close"].sort_index()
    spy = spy[~spy.index.duplicated(keep="last")]
    spy_ret_20d = spy.pct_change(20)
    
    print(f"  K: {len(k_states)}d, M: {len(m_states)}d, D: {len(d_states)}d")
    print(f"  SPY: {len(spy)}d\n")
    
    all_results = {}
    
    # K state calibration
    print("=== K State Calibration ===\n")
    
    print("State distribution:")
    k_dist = k_states["state"].value_counts()
    for state, count in k_dist.items():
        print(f"  {state}: {count} ({count/len(k_states)*100:.1f}%)")
    
    print("\nTransition matrix:")
    k_trans = estimate_transition_matrix(k_states["state"])
    all_results["k_transition"] = k_trans
    
    # Print matrix
    states = k_trans["states"]
    matrix = k_trans["matrix"]
    print(f"  {'':>25}", end="")
    for s in states:
        print(f" {s[:8]:>8}", end="")
    print()
    for i, from_state in enumerate(states):
        print(f"  {from_state:>25}", end="")
        for j, to_state in enumerate(states):
            print(f" {matrix[i][j]:>8.3f}", end="")
        print()
    
    print("\nState durations:")
    k_dur = estimate_state_durations(k_states["state"])
    all_results["k_durations"] = k_dur
    for state, dur in k_dur.items():
        print(f"  {state}: mean={dur['mean']:.1f}d, median={dur['median']:.1f}d, max={dur['max']}d")
    
    print("\nState returns (SPY 20d forward):")
    k_returns = estimate_state_returns(k_states, spy_ret_20d)
    all_results["k_returns"] = k_returns
    for state, ret in k_returns.items():
        print(f"  {state}: mean={ret['mean']:+.4f}, sharpe={ret['sharpe']:.3f}, n={ret['n']}")
    
    # M state calibration
    print("\n=== M State Calibration ===\n")
    
    print("State distribution:")
    m_dist = m_states["state"].value_counts()
    for state, count in list(m_dist.items())[:8]:
        print(f"  {state}: {count} ({count/len(m_states)*100:.1f}%)")
    
    print("\nState durations:")
    m_dur = estimate_state_durations(m_states["state"])
    all_results["m_durations"] = m_dur
    for state, dur in list(m_dur.items())[:6]:
        print(f"  {state}: mean={dur['mean']:.1f}d, median={dur['median']:.1f}d, max={dur['max']}d")
    
    # D state calibration
    print("\n=== D State Calibration ===\n")
    
    print("State distribution:")
    d_dist = d_states["state"].value_counts()
    for state, count in list(d_dist.items())[:8]:
        print(f"  {state}: {count} ({count/len(d_states)*100:.1f}%)")
    
    print("\nState durations:")
    d_dur = estimate_state_durations(d_states["state"])
    all_results["d_durations"] = d_dur
    for state, dur in list(d_dur.items())[:6]:
        print(f"  {state}: mean={dur['mean']:.1f}d, median={dur['median']:.1f}d, max={dur['max']}d")
    
    # Save results
    out_data = {
        "generated": datetime.now(UTC).isoformat(),
        **all_results,
    }
    
    out_path = OUTPUT / "calibration_results.json"
    with open(out_path, "w") as f:
        json.dump(out_data, f, indent=2, default=str)
    print(f"\nSaved to {out_path}")
    print("\nDone.")


if __name__ == "__main__":
    main()
