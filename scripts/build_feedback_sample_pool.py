"""Build the Feedback Sample Pool.

Stratified sampling of historical dates into replay-ready manifest entries.
Each entry records: as_of_date, sample_type, why_selected, allowed_lookback.

Output: Data/feedback_samples/sample_manifest.jsonl
Policy: governance/feedback_sampling_policy.yaml
Schema: protocols/feedback_sample.schema.json

Usage:
    python3 scripts/build_feedback_sample_pool.py --n 300
    python3 scripts/build_feedback_sample_pool.py --n 500 --seed 42
    python3 scripts/build_feedback_sample_pool.py --n 300 --dry-run
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
from _workspace_imports import add_scripts
add_scripts()
from _runtime_io import ensure_dir, load_yaml, utc_now, write_json  # noqa: E402

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PANEL_PATH = ROOT / "Data" / "panels" / "cross_asset_daily_panel.parquet"
POLICY_PATH = ROOT / "governance" / "feedback_sampling_policy.yaml"
MANIFEST_PATH = ROOT / "Data" / "feedback_samples" / "sample_manifest.jsonl"

# ---------------------------------------------------------------------------
# Stress / turning / false-alarm / quiet windows from policy
# ---------------------------------------------------------------------------

def _load_policy() -> dict:
    policy = load_yaml(POLICY_PATH)
    if not policy:
        print("[WARN] Could not load policy; using built-in defaults")
        return _default_policy()
    return policy


def _default_policy() -> dict:
    return {
        "stratification": {
            "stress_window": 0.30,
            "turning_point": 0.20,
            "quiet_window": 0.20,
            "false_alarm": 0.15,
            "random": 0.15,
            "stress_periods": [
                {"start": "2008-09-01", "end": "2009-03-31", "label": "gfc_2008"},
                {"start": "2011-07-01", "end": "2011-10-31", "label": "debt_ceiling_2011"},
                {"start": "2015-08-01", "end": "2016-02-29", "label": "cny_oil_credit_2015"},
                {"start": "2018-10-01", "end": "2018-12-31", "label": "q4_2018"},
                {"start": "2020-02-15", "end": "2020-04-30", "label": "covid_2020"},
                {"start": "2022-01-01", "end": "2022-10-31", "label": "rate_hikes_2022"},
                {"start": "2023-03-01", "end": "2023-05-31", "label": "bank_crisis_2023"},
            ],
            "turning_point_periods": [
                {"start": "2009-03-01", "end": "2009-06-30", "label": "gfc_bottom"},
                {"start": "2016-02-15", "end": "2016-04-30", "label": "post_cny_recovery"},
                {"start": "2018-12-24", "end": "2019-02-28", "label": "dec2018_bottom"},
                {"start": "2020-03-23", "end": "2020-06-30", "label": "covid_recovery"},
                {"start": "2022-10-15", "end": "2023-01-31", "label": "inflation_peak"},
            ],
            "false_alarm_periods": [
                {"start": "2010-05-01", "end": "2010-07-31", "label": "flash_crash_2010"},
                {"start": "2012-05-01", "end": "2012-07-31", "label": "eu_summit_fade"},
                {"start": "2014-10-01", "end": "2014-12-31", "label": "ebola_scare"},
                {"start": "2015-08-24", "end": "2015-09-30", "label": "aug2015_flash"},
                {"start": "2019-08-01", "end": "2019-10-31", "label": "repo_spike_2019"},
            ],
        }
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _short_hash(as_of_date: str, sample_type: str) -> str:
    raw = f"{as_of_date}_{sample_type}"
    return hashlib.sha256(raw.encode()).hexdigest()[:8]


def _dates_in_range(all_dates: list[str], start: str, end: str) -> list[str]:
    """Return sorted dates within [start, end] from all_dates."""
    return [d for d in all_dates if start <= d <= end]


def _sample_dates(dates: list[str], n: int, rng) -> list[str]:
    """Sample up to n dates from the list, without replacement."""
    if len(dates) <= n:
        return sorted(dates)
    indices = sorted(rng.sample(range(len(dates)), n))
    return [dates[i] for i in indices]


# ---------------------------------------------------------------------------
# Main pool builder
# ---------------------------------------------------------------------------

def build_pool(n: int, seed: int = 42, dry_run: bool = False) -> list[dict]:
    """Build a stratified sample pool of n entries."""
    import random

    rng = random.Random(seed)

    # Load available trading dates from the panel
    print(f"[INFO] Loading panel from {PANEL_PATH}")
    df = pd.read_parquet(PANEL_PATH, columns=["date", "symbol"])
    # Get unique dates where SPY exists (liquid market proxy)
    spy_dates = sorted(df[df["symbol"] == "SPY"]["date"].unique())
    all_dates = [pd.Timestamp(d).strftime("%Y-%m-%d") for d in spy_dates]

    # Require at least 63 trading days of history before sampling
    # (to allow lookback) and at least 63 trading days after (to compute 3m forward)
    min_date = all_dates[63] if len(all_dates) > 126 else all_dates[0]
    max_date = all_dates[-63] if len(all_dates) > 126 else all_dates[-1]
    eligible_dates = [d for d in all_dates if min_date <= d <= max_date]

    print(f"[INFO] {len(all_dates)} total trading dates, {len(eligible_dates)} eligible for sampling")
    print(f"[INFO] Eligible range: {min_date} to {max_date}")

    policy = _load_policy()
    strat = policy.get("stratification", {})

    # Compute per-category counts
    ratios = {
        "stress_window": strat.get("stress_window", 0.30),
        "turning_point": strat.get("turning_point", 0.20),
        "quiet_window": strat.get("quiet_window", 0.20),
        "false_alarm": strat.get("false_alarm", 0.15),
        "random": strat.get("random", 0.15),
    }
    counts = {}
    remaining = n
    for cat, ratio in ratios.items():
        c = int(n * ratio)
        counts[cat] = c
        remaining -= c
    # Distribute remainder to the largest category
    counts[max(counts, key=counts.get)] += remaining

    # Build date pools for each category
    pool: list[dict] = []

    # --- Stress windows ---
    stress_periods = strat.get("stress_periods", [])
    stress_dates = []
    for period in stress_periods:
        dates_in = _dates_in_range(eligible_dates, period["start"], period["end"])
        for d in dates_in:
            stress_dates.append((d, period["label"]))
    sampled_stress = _sample_dates(
        [d for d, _ in stress_dates], counts["stress_window"], rng
    )
    stress_label_map = {d: lbl for d, lbl in stress_dates}
    for d in sampled_stress:
        pool.append({
            "as_of_date": d,
            "sample_type": "stress_window",
            "why_selected": f"Stress period: {stress_label_map.get(d, 'unknown')}",
            "allowed_lookback": _lookback_date(all_dates, d, 63),
        })

    # --- Turning points ---
    tp_periods = strat.get("turning_point_periods", [])
    tp_dates = []
    for period in tp_periods:
        dates_in = _dates_in_range(eligible_dates, period["start"], period["end"])
        for d in dates_in:
            tp_dates.append((d, period["label"]))
    sampled_tp = _sample_dates(
        [d for d, _ in tp_dates], counts["turning_point"], rng
    )
    tp_label_map = {d: lbl for d, lbl in tp_dates}
    for d in sampled_tp:
        pool.append({
            "as_of_date": d,
            "sample_type": "turning_point",
            "why_selected": f"Turning point: {tp_label_map.get(d, 'unknown')}",
            "allowed_lookback": _lookback_date(all_dates, d, 63),
        })

    # --- False alarms ---
    fa_periods = strat.get("false_alarm_periods", [])
    fa_dates = []
    for period in fa_periods:
        dates_in = _dates_in_range(eligible_dates, period["start"], period["end"])
        for d in dates_in:
            fa_dates.append((d, period["label"]))
    sampled_fa = _sample_dates(
        [d for d, _ in fa_dates], counts["false_alarm"], rng
    )
    fa_label_map = {d: lbl for d, lbl in fa_dates}
    for d in sampled_fa:
        pool.append({
            "as_of_date": d,
            "sample_type": "false_alarm",
            "why_selected": f"False alarm: {fa_label_map.get(d, 'unknown')}",
            "allowed_lookback": _lookback_date(all_dates, d, 63),
        })

    # --- Quiet windows ---
    # Quiet = dates NOT in any stress/tp/fa period
    used_dates = set(sampled_stress) | set(sampled_tp) | set(sampled_fa)
    period_dates = set()
    for periods in [stress_periods, tp_periods, fa_periods]:
        for period in periods:
            period_dates.update(_dates_in_range(eligible_dates, period["start"], period["end"]))
    quiet_candidates = [d for d in eligible_dates if d not in period_dates and d not in used_dates]
    sampled_quiet = _sample_dates(quiet_candidates, counts["quiet_window"], rng)
    for d in sampled_quiet:
        pool.append({
            "as_of_date": d,
            "sample_type": "quiet_window",
            "why_selected": "Quiet window — no known stress/turning/false-alarm event",
            "allowed_lookback": _lookback_date(all_dates, d, 63),
        })

    # --- Random ---
    all_used = set(e["as_of_date"] for e in pool)
    random_candidates = [d for d in eligible_dates if d not in all_used]
    sampled_random = _sample_dates(random_candidates, counts["random"], rng)
    for d in sampled_random:
        pool.append({
            "as_of_date": d,
            "sample_type": "random",
            "why_selected": "Random sample from eligible date range",
            "allowed_lookback": _lookback_date(all_dates, d, 63),
        })

    # Add schema_version and sample_id
    now_iso = utc_now().isoformat()
    for entry in pool:
        entry["schema_version"] = "feedback_sample.v1"
        entry["sample_id"] = f"{entry['as_of_date']}_{entry['sample_type']}_{_short_hash(entry['as_of_date'], entry['sample_type'])}"
        entry["generated_at"] = now_iso

    # Sort by date
    pool.sort(key=lambda e: e["as_of_date"])

    print(f"[INFO] Built pool of {len(pool)} samples:")
    for cat in ratios:
        count = sum(1 for e in pool if e["sample_type"] == cat)
        print(f"  {cat}: {count}")

    # Preserve existing real_judgment entries from any prior manifest
    preserved = []
    if MANIFEST_PATH.exists():
        from _runtime_io import load_jsonl as _load_jsonl
        for entry in _load_jsonl(MANIFEST_PATH):
            if entry.get("sample_type") == "real_judgment":
                preserved.append(entry)
    if preserved:
        print(f"[INFO] Preserving {len(preserved)} existing real_judgment entries")

    # Write manifest (replay samples + preserved real judgments)
    if not dry_run:
        ensure_dir(MANIFEST_PATH.parent)
        with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
            for entry in pool:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            for entry in preserved:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        total = len(pool) + len(preserved)
        print(f"[OK] Wrote {total} entries to {MANIFEST_PATH} ({len(pool)} replay + {len(preserved)} real)")
    else:
        total = len(pool) + len(preserved)
        print(f"[DRY-RUN] Would write {total} entries to {MANIFEST_PATH}")

    return pool


def _lookback_date(all_dates: list[str], target: str, lookback_days: int) -> str:
    """Find the date that is ~lookback_days trading days before target."""
    try:
        idx = all_dates.index(target)
        lookback_idx = max(0, idx - lookback_days)
        return all_dates[lookback_idx]
    except ValueError:
        # Fallback: subtract calendar days
        dt = datetime.strptime(target, "%Y-%m-%d") - timedelta(days=int(lookback_days * 1.5))
        return dt.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the Feedback Sample Pool for calibration replay"
    )
    parser.add_argument(
        "--n", type=int, default=300,
        help="Total number of samples to generate (default: 300)"
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for reproducibility (default: 42)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be generated without writing files"
    )
    args = parser.parse_args()
    build_pool(n=args.n, seed=args.seed, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
