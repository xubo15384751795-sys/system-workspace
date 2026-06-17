#!/usr/bin/env python3
"""Blind Replay Practicality Test.

Samples 20 historical dates, generates "frozen" system snapshots showing
only what was visible at that time, and prepares human interpretation
templates.  Forward returns are stored separately for later revelation.

Usage:
    python3 scripts/blind_replay_test.py              # generate all 20
    python3 scripts/blind_replay_test.py --reveal      # reveal forward returns
"""
from __future__ import annotations

import argparse
import json
import random
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "Output" / "practicality_trial" / "blind_replay"
PANEL_PATH = ROOT / "Data" / "harvester" / "exports" / "latest" / "data" / "benchmark_panel.parquet"
ETF_PANEL = ROOT / "Data" / "panels" / "cross_asset_daily_panel.parquet"
RESULTS_PATH = ROOT / "Output" / "sandbox" / "structural_replay_v2" / "results.json"

# ── Known event windows (for mix of signal-rich and quiet dates) ────────

EVENT_WINDOWS = [
    # (event_id, peak_date, approximate_start)
    ("asian_1997", "1997-10-27", "1997-07-01"),
    ("ltcm_1998", "1998-09-23", "1998-07-01"),
    ("gfc_2008", "2008-09-15", "2008-06-01"),
    ("flash_2010", "2010-05-06", "2010-03-01"),
    ("debt_ceiling_2011", "2011-08-08", "2011-05-01"),
    ("taper_tantrum_2013", "2013-06-20", "2013-04-01"),
    ("oil_shock_2014", "2014-12-16", "2014-09-01"),
    ("china_deval_2015", "2015-08-24", "2015-06-01"),
    ("volmageddon_2018", "2018-05-29", "2018-01-01"),
    ("covid_2020", "2020-03-23", "2020-01-01"),
    ("archegos_2021", "2021-03-26", "2021-01-01"),
    ("svb_2023", "2023-03-10", "2023-01-01"),
    ("carry_unwind_2024", "2024-08-05", "2024-06-01"),
]

# Quiet periods (no major events)
QUIET_PERIODS = [
    ("2005-06-15", "2005-09-15"),
    ("2006-03-01", "2006-06-01"),
    ("2012-03-01", "2012-06-01"),
    ("2017-05-01", "2017-08-01"),
    ("2019-05-01", "2019-08-01"),
    ("2021-09-01", "2021-12-01"),
    ("2024-01-15", "2024-04-15"),
]


def load_panel() -> pd.DataFrame:
    """Load the benchmark panel."""
    df = pd.read_parquet(PANEL_PATH)
    df["date"] = pd.to_datetime(df["date"])
    return df


def load_etf_panel() -> pd.DataFrame:
    """Load the cross-asset ETF panel for forward returns."""
    df = pd.read_parquet(ETF_PANEL)
    df["date"] = pd.to_datetime(df["date"])
    return df


def compute_channel_snapshot(panel: pd.DataFrame, as_of: str) -> dict:
    """Compute a simplified M/D/K/X-like snapshot from available series.
    
    Since we can't run the full framework retroactively, we use the
    existing replay results as the source of truth for known events,
    and compute basic statistics for random dates.
    """
    as_of_dt = pd.Timestamp(as_of)
    # Get data up to as_of
    hist = panel[panel["date"] <= as_of_dt].copy()
    if hist.empty:
        return {"error": "no data available"}

    # Compute basic stats per series
    recent = hist[hist["date"] >= as_of_dt - pd.Timedelta(days=90)]
    stats = {}
    for sid in recent["series_id"].unique():
        s = recent[recent["series_id"] == sid]["value"].dropna()
        if len(s) > 5:
            stats[sid] = {
                "mean": round(float(s.mean()), 4),
                "std": round(float(s.std()), 4),
                "last": round(float(s.iloc[-1]), 4),
                "z_score": round(float((s.iloc[-1] - s.mean()) / max(s.std(), 0.001)), 2),
            }

    return stats


def compute_forward_returns(etf_panel: pd.DataFrame, date_str: str, spx_only: bool = True) -> dict:
    """Compute forward returns for SPY/SPX from the given date."""
    dt = pd.Timestamp(date_str)
    # Find the nearest trading day on or after dt
    future = etf_panel[etf_panel["date"] >= dt].copy()
    if future.empty:
        return {"error": "no future data"}

    # Get the "close" column for SPY or first available
    symbols = future["symbol"].unique()
    target = None
    for candidate in ["SPY", "SPX", "QQQ", "IWM"]:
        if candidate in symbols:
            target = candidate
            break
    if target is None:
        target = symbols[0]

    sdf = future[future["symbol"] == target].sort_values("date")
    if sdf.empty:
        return {"error": f"no data for {target}"}

    base_price = sdf.iloc[0]["close"]
    results = {"symbol": target, "base_date": date_str, "base_price": round(float(base_price), 2)}

    for horizon in [5, 20, 60, 120]:
        if len(sdf) > horizon:
            fwd_price = sdf.iloc[horizon]["close"]
            ret = (fwd_price / base_price - 1) * 100
            results[f"return_{horizon}d"] = round(float(ret), 2)
        else:
            results[f"return_{horizon}d"] = None

    return results


def get_replay_snapshot(event_id: str) -> dict | None:
    """Get the replay result for a known event."""
    if not RESULTS_PATH.exists():
        return None
    results = json.load(open(RESULTS_PATH))
    for r in results:
        if r.get("event_id") == event_id:
            return r
    return None


def sample_dates(n_events: int = 10, n_quiet: int = 10) -> list[dict]:
    """Sample a mix of event-window and quiet-period dates."""
    samples = []

    # Sample from event windows
    selected_events = random.sample(EVENT_WINDOWS, min(n_events, len(EVENT_WINDOWS)))
    for event_id, peak, start in selected_events:
        # Pick a random date in the 3 months before peak
        start_dt = datetime.strptime(start, "%Y-%m-%d")
        peak_dt = datetime.strptime(peak, "%Y-%m-%d")
        delta = (peak_dt - start_dt).days
        random_day = random.randint(0, delta)
        sample_date = start_dt + pd.Timedelta(days=random_day)
        samples.append({
            "date": sample_date.strftime("%Y-%m-%d"),
            "type": "event_window",
            "event_hint": event_id,
            "peak_date": peak,
        })

    # Sample from quiet periods
    selected_quiet = random.sample(QUIET_PERIODS, min(n_quiet, len(QUIET_PERIODS)))
    for start, end in selected_quiet:
        start_dt = datetime.strptime(start, "%Y-%m-%d")
        end_dt = datetime.strptime(end, "%Y-%m-%d")
        delta = (end_dt - start_dt).days
        random_day = random.randint(0, delta)
        sample_date = start_dt + pd.Timedelta(days=random_day)
        samples.append({
            "date": sample_date.strftime("%Y-%m-%d"),
            "type": "quiet_period",
            "event_hint": None,
            "peak_date": None,
        })

    random.shuffle(samples)
    return samples


def generate_blind_snapshot(sample: dict, panel: pd.DataFrame, etf_panel: pd.DataFrame) -> dict:
    """Generate a blind snapshot for a sample date."""
    date_str = sample["date"]

    # Get channel snapshot
    channel_stats = compute_channel_snapshot(panel, date_str)

    # Get forward returns (stored separately, not shown to user)
    fwd_returns = compute_forward_returns(etf_panel, date_str)

    # Check if we have replay data for this event
    replay = None
    if sample.get("event_hint"):
        replay = get_replay_snapshot(sample["event_hint"])

    snapshot = {
        "id": f"blind_{samples.index(sample)+1:02d}" if sample in samples else "blind_??",
        "date_hidden": True,
        "snapshot_as_of": date_str,
        "type": sample["type"],
        "channel_stats_summary": _summarize_channels(channel_stats),
        "available_series_count": len(channel_stats),
        "replay_regime": replay.get("peak_regime") if replay else None,
        "replay_path": [
            {"channel": p["channel"], "days_before": p.get("days_before_peak", "?")}
            for p in (replay.get("observed_path", [])[:5] if replay else [])
        ],
    }

    return snapshot, fwd_returns


def _summarize_channels(stats: dict) -> dict:
    """Summarize channel stats into high/medium/low pressure indicators."""
    summary = {}
    for sid, s in stats.items():
        z = abs(s.get("z_score", 0))
        if z > 2.0:
            level = "HIGH"
        elif z > 1.0:
            level = "ELEVATED"
        else:
            level = "NORMAL"
        summary[sid] = {"level": level, "z_score": s["z_score"], "last": s["last"]}
    return summary


def generate_blind_template(idx: int, snapshot: dict) -> str:
    """Generate a blind interpretation template for one sample."""
    # Build a status sheet
    lines = [
        f"# Blind Replay #{idx+1:02d}",
        "",
        "**Date: [HIDDEN]** — you will be told the date after writing your interpretation.",
        "",
        "## System Snapshot (as of hidden date)",
        "",
        f"- Available series: {snapshot['available_series_count']}",
        f"- Type: {snapshot['type']}",
    ]

    if snapshot.get("replay_regime"):
        lines.append(f"- Replay regime (hidden): _redacted_")

    lines += [
        "",
        "### Channel Pressure Levels",
        "",
        "| Series | Pressure Level | Z-Score |",
        "|---|---|---:|",
    ]

    for sid, info in sorted(snapshot.get("channel_stats_summary", {}).items()):
        lines.append(f"| {sid} | {info['level']} | {info['z_score']:+.2f} |")

    lines += [
        "",
        "### Replay Path (if available)",
        "",
        "| Channel | Days Before Peak |",
        "|---|---:|",
    ]
    for p in snapshot.get("replay_path", []):
        lines.append(f"| {p['channel']} | {p['days_before']} |")

    if not snapshot.get("replay_path"):
        lines.append("| _no replay path available_ | — |")

    lines += [
        "",
        "---",
        "",
        "## Your Interpretation (fill BEFORE reveal)",
        "",
        "### Structural State",
        "What do you think the structural state is?",
        "",
        "```",
        "",
        "```",
        "",
        "### Pressure Assessment",
        "Is pressure accumulating, releasing, or stable?",
        "",
        "```",
        "",
        "```",
        "",
        "### Regime Classification",
        "Pick one: STABLE_LOCAL / ELEVATED_ACCUMULATION / ACTIVE_STRESS / RESOLUTION / MEASUREMENT_BLIND_SPOT / NOISE",
        "",
        "```",
        "",
        "```",
        "",
        "### Confidence",
        "How confident are you? (1-5, where 5 = very confident)",
        "",
        "```",
        "",
        "```",
        "",
        "### Would You Watch or Act?",
        "",
        "```",
        "",
        "```",
        "",
        "---",
        "",
        "## Post-Reveal (fill AFTER date and forward returns are shown)",
        "",
        "### Date Revealed: _to be filled_",
        "### Event Context: _to be filled_",
        "",
        "### Forward Returns",
        "| Horizon | Return |",
        "|---|---:|",
        "| 5d | _reveal_ |",
        "| 20d | _reveal_ |",
        "| 60d | _reveal_ |",
        "| 120d | _reveal_ |",
        "",
        "### Was Your Assessment Correct?",
        "",
        "```",
        "",
        "```",
        "",
        "### Did Hermes Help?",
        "Would you have made a better/worse/same judgment without the system snapshot?",
        "",
        "```",
        "",
        "```",
    ]

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Blind Replay Practicality Test")
    parser.add_argument("--reveal", action="store_true", help="Reveal forward returns")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--n-events", type=int, default=10)
    parser.add_argument("--n-quiet", type=int, default=10)
    args = parser.parse_args()

    OUTPUT.mkdir(parents=True, exist_ok=True)

    if args.reveal:
        reveal_forward_returns()
        return

    random.seed(args.seed)

    print("Loading data...")
    panel = load_panel()
    etf_panel = load_etf_panel()

    print("Sampling dates...")
    global samples
    samples = sample_dates(args.n_events, args.n_quiet)

    all_forward_returns = []
    all_snapshots = []

    print(f"Generating {len(samples)} blind snapshots...")
    for i, sample in enumerate(samples):
        snapshot, fwd = generate_blind_snapshot(sample, panel, etf_panel)
        snapshot["id"] = f"blind_{i+1:02d}"
        all_snapshots.append(snapshot)
        all_forward_returns.append({
            "id": f"blind_{i+1:02d}",
            "date": sample["date"],
            "type": sample["type"],
            "event_hint": sample.get("event_hint"),
            "forward_returns": fwd,
        })

        # Generate template
        template = generate_blind_template(i, snapshot)
        template_path = OUTPUT / f"blind_{i+1:02d}_template.md"
        template_path.write_text(template, encoding="utf-8")

    # Save forward returns (hidden file)
    fwd_path = OUTPUT / "_forward_returns_HIDDEN.json"
    fwd_path.write_text(json.dumps(all_forward_returns, indent=2, default=str), encoding="utf-8")
    print(f"Forward returns saved: {fwd_path}")

    # Save snapshots index
    idx_path = OUTPUT / "blind_index.json"
    idx_path.write_text(json.dumps(all_snapshots, indent=2, default=str), encoding="utf-8")
    print(f"Index saved: {idx_path}")

    # Print summary
    print(f"\n=== Blind Replay Test Generated ===")
    print(f"Total samples: {len(samples)}")
    print(f"Event-window samples: {sum(1 for s in samples if s['type'] == 'event_window')}")
    print(f"Quiet-period samples: {sum(1 for s in samples if s['type'] == 'quiet_period')}")
    print(f"\nFiles:")
    for i in range(len(samples)):
        print(f"  blind_{i+1:02d}_template.md")
    print(f"\nForward returns are HIDDEN in: _forward_returns_HIDDEN.json")
    print(f"Run with --reveal to generate the reveal document.")


def reveal_forward_returns() -> None:
    """Generate a reveal document with forward returns."""
    fwd_path = OUTPUT / "_forward_returns_HIDDEN.json"
    if not fwd_path.exists():
        print("ERROR: No forward returns file found. Run without --reveal first.")
        return

    data = json.loads(fwd_path.read_text())

    lines = [
        "# Blind Replay — Forward Returns Reveal",
        "",
        "| ID | Date | Type | Event | 5d | 20d | 60d | 120d |",
        "|---|---|---|---|---:|---:|---:|---:|",
    ]

    for item in data:
        fwd = item.get("forward_returns", {})
        lines.append(
            f"| {item['id']} | {item['date']} | {item['type']} | {item.get('event_hint', '—')} "
            f"| {fwd.get('return_5d', '?')}% | {fwd.get('return_20d', '?')}% "
            f"| {fwd.get('return_60d', '?')}% | {fwd.get('return_120d', '?')}% |"
        )

    reveal_text = "\n".join(lines)
    reveal_path = OUTPUT / "REVEAL_forward_returns.md"
    reveal_path.write_text(reveal_text, encoding="utf-8")
    print(f"Reveal document: {reveal_path}")
    print("\n" + reveal_text)


if __name__ == "__main__":
    main()
