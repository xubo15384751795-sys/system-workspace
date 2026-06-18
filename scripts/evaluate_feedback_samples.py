"""Evaluate Feedback Samples.

For each replay output:
1. Compute forward outcomes (SPY/HYG/TLT/GLD/VIX at 1d/1w/1m/3m)
2. Auto-label based on judgment vs realized outcome
3. Update the sample record with forward_outcome and review_label

Then generate:
- calibration_summary.json (statistics by category, confidence, decision)
- evaluation_report.md (human-readable findings)
- failure_cases.md (cases that need human review)

Usage:
    python3 scripts/evaluate_feedback_samples.py
    python3 scripts/evaluate_feedback_samples.py --top 50
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
from _workspace_imports import add_scripts
add_scripts()
from _runtime_io import (
    ensure_dir,
    load_json,
    load_jsonl,
    load_yaml,
    utc_now,
    write_json,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPLAY_DIR = ROOT / "Output" / "feedback_samples" / "replay_runs"
PANEL_PATH = ROOT / "Data" / "panels" / "cross_asset_daily_panel.parquet"
VIX_PATH = ROOT / "Data" / "structural_lab" / "runtime" / "fred_cache" / "VIXCLS.csv"
POLICY_PATH = ROOT / "governance" / "feedback_sampling_policy.yaml"
REPORT_PATH = ROOT / "Output" / "feedback_samples" / "evaluation_report.md"
SUMMARY_PATH = ROOT / "Output" / "feedback_samples" / "calibration_summary.json"
FAILURE_PATH = ROOT / "Output" / "feedback_samples" / "failure_cases.md"
REVIEW_QUEUE_PATH = ROOT / "Output" / "feedback_samples" / "review_queue.jsonl"

# ---------------------------------------------------------------------------
# Forward outcome computation
# ---------------------------------------------------------------------------

def _load_market_data() -> tuple[pd.DataFrame, pd.Series | None]:
    """Load close price matrix and VIX series."""
    panel = pd.read_parquet(PANEL_PATH)
    panel["date"] = pd.to_datetime(panel["date"])
    # Build per-symbol Series to avoid groupby/unstack index corruption
    symbols = sorted(panel["symbol"].unique())
    series_map = {}
    for sym in symbols:
        sub = panel[panel["symbol"] == sym][["date", "close"]].set_index("date")["close"]
        series_map[sym] = sub
    close_matrix = pd.DataFrame(series_map).sort_index()

    vix_series = None
    if VIX_PATH.exists():
        try:
            vix_df = pd.read_csv(VIX_PATH, parse_dates=["DATE"], index_col="DATE")
            vix_series = pd.to_numeric(vix_df.iloc[:, 0], errors="coerce").dropna()
            vix_series.index = pd.to_datetime(vix_series.index)
        except Exception:
            pass

    return close_matrix, vix_series


def _pct_change(close_series: pd.Series, as_of: pd.Timestamp, days: int) -> float | None:
    """Compute percentage change over the next `days` trading days after as_of."""
    future_start = as_of
    future_end = as_of + pd.Timedelta(days=int(days * 1.6))  # calendar days buffer

    window = close_series.loc[future_start:future_end].dropna()
    if len(window) < 2:
        return None

    # Use the first available price as baseline
    base_price = window.iloc[0]
    # Find the price closest to the target horizon
    target_date = as_of + pd.Timedelta(days=days)
    # Get the closest available date
    available = window.loc[future_start:target_date]
    if len(available) < 2:
        available = window

    end_price = available.iloc[-1]
    if base_price == 0:
        return None

    return round(float((end_price / base_price) - 1), 6)


def _level_at(close_series: pd.Series, as_of: pd.Timestamp) -> float | None:
    """Get the value at or just after as_of."""
    window = close_series.loc[as_of:].dropna()
    if len(window) == 0:
        return None
    return round(float(window.iloc[0]), 4)


def _max_drawdown(close_series: pd.Series, as_of: pd.Timestamp, days: int) -> float | None:
    """Compute max drawdown over the next `days` calendar days."""
    future_end = as_of + pd.Timedelta(days=days)
    window = close_series.loc[as_of:future_end].dropna()
    if len(window) < 5:
        return None

    running_max = window.expanding().max()
    drawdown = (window / running_max) - 1
    return round(float(drawdown.min()), 6)


def compute_forward_outcome(
    sample: dict,
    close_matrix: pd.DataFrame,
    vix_series: pd.Series | None,
) -> dict:
    """Compute forward outcomes for all tracked assets."""
    as_of = pd.Timestamp(sample["as_of_date"])

    outcome = {
        "computed_at": utc_now().isoformat(),
    }

    # Asset forward returns
    for ticker in ["SPY", "HYG", "TLT", "GLD"]:
        if ticker in close_matrix.columns:
            series = close_matrix[ticker]
            outcome[ticker.lower()] = {
                "pct_1d": _pct_change(series, as_of, 1),
                "pct_1w": _pct_change(series, as_of, 5),
                "pct_1m": _pct_change(series, as_of, 21),
                "pct_3m": _pct_change(series, as_of, 63),
            }
        else:
            outcome[ticker.lower()] = {
                "pct_1d": None, "pct_1w": None, "pct_1m": None, "pct_3m": None,
            }

    # VIX
    if vix_series is not None:
        vix_at = _level_at(vix_series, as_of)
        vix_1d = _level_at(vix_series, as_of + pd.Timedelta(days=1))
        vix_1w = _level_at(vix_series, as_of + pd.Timedelta(days=7))
        vix_1m = _level_at(vix_series, as_of + pd.Timedelta(days=30))
        outcome["vix"] = {
            "level_at": vix_at,
            "change_1d": round(vix_1d - vix_at, 2) if vix_at is not None and vix_1d is not None else None,
            "change_1w": round(vix_1w - vix_at, 2) if vix_at is not None and vix_1w is not None else None,
            "change_1m": round(vix_1m - vix_at, 2) if vix_at is not None and vix_1m is not None else None,
        }
    else:
        outcome["vix"] = {"level_at": None, "change_1d": None, "change_1w": None, "change_1m": None}

    # MOVE not in panel — placeholder
    outcome["move"] = {"level_at": None, "change_1w": None, "change_1m": None}

    # SPY max drawdown over 1 month
    if "SPY" in close_matrix.columns:
        outcome["max_drawdown_1m"] = _max_drawdown(close_matrix["SPY"], as_of, 30)
    else:
        outcome["max_drawdown_1m"] = None

    # Stress event flag
    spy_1w = outcome.get("spy", {}).get("pct_1w")
    spy_1m = outcome.get("spy", {}).get("pct_1m")
    vix_change_1w = outcome.get("vix", {}).get("change_1w")
    mdd = outcome.get("max_drawdown_1m")

    stress = False
    if spy_1w is not None and spy_1w < -0.03:
        stress = True
    if spy_1m is not None and spy_1m < -0.05:
        stress = True
    if vix_change_1w is not None and vix_change_1w > 5:
        stress = True
    if mdd is not None and mdd < -0.05:
        stress = True
    outcome["stress_event_happened"] = stress

    return outcome


# ---------------------------------------------------------------------------
# Auto-labeling
# ---------------------------------------------------------------------------

def auto_label(sample: dict, outcome: dict) -> tuple[str, str]:
    """Assign a review_label and reason based on judgment vs outcome.

    Returns (label, reason).
    """
    judgment = sample.get("system_judgment", {})
    decision = judgment.get("decision", "NO_TRADE")
    confidence = judgment.get("confidence", "low")
    claim_tier = judgment.get("claim_tier", 0)

    stress = outcome.get("stress_event_happened", False)
    spy_1w = outcome.get("spy", {}).get("pct_1w")
    spy_1m = outcome.get("spy", {}).get("pct_1m")
    mdd = outcome.get("max_drawdown_1m")
    m_val = sample.get("system_state", {}).get("m_value")

    # Decision was WATCH/RESEARCH_REVIEW and stress materialized
    if decision in ("WATCH", "RESEARCH_REVIEW") and stress:
        return "useful", f"System flagged ({decision}/{confidence}) and stress materialized (SPY 1w={spy_1w}, 1m={spy_1m})"

    # Decision was WATCH/RESEARCH_REVIEW but no stress
    if decision in ("WATCH", "RESEARCH_REVIEW") and not stress:
        if mdd is not None and mdd > -0.02:
            return "false_positive", f"System flagged ({decision}) but no significant drawdown (MDD={mdd})"
        return "correct_but_low_value", f"System flagged ({decision}) but market was calm"

    # Decision was NO_TRADE and stress happened
    if decision == "NO_TRADE" and stress:
        if mdd is not None and mdd < -0.05:
            return "missed_stress", f"System said NO_TRADE ({confidence}) but stress hit (MDD={mdd})"
        if spy_1w is not None and spy_1w < -0.03:
            return "missed_stress", f"System said NO_TRADE but SPY dropped {spy_1w:.1%} in 1w"

    # Decision was NO_TRADE and no stress — correct
    if decision == "NO_TRADE" and not stress:
        return "useful", f"Correct NO_TRADE — market was calm (SPY 1w={spy_1w})"

    # Mechanism hypothesis direction check
    mech = judgment.get("mechanism_hypothesis", "").lower()
    if "stress" in mech and spy_1m is not None and spy_1m > 0.03:
        return "misleading", f"Mechanism suggested stress but SPY rallied {spy_1m:.1%} in 1m"
    if "relief" in mech and spy_1m is not None and spy_1m < -0.03:
        return "misleading", f"Mechanism suggested relief but SPY dropped {spy_1m:.1%} in 1m"

    return "needs_review", "Auto-labeler could not determine — needs human review"


# ---------------------------------------------------------------------------
# Evaluation engine
# ---------------------------------------------------------------------------

def evaluate_all(force: bool = False) -> list[dict]:
    """Evaluate all replay outputs: add forward outcomes and labels."""
    replay_files = sorted(REPLAY_DIR.glob("*.json"))
    if not replay_files:
        print(f"[ERROR] No replay outputs found in {REPLAY_DIR}")
        print("        Run run_feedback_replay_batch.py first.")
        return []

    print(f"[INFO] Found {len(replay_files)} replay outputs")

    # Load market data once
    print("[INFO] Loading market data for forward outcome computation...")
    close_matrix, vix_series = _load_market_data()
    print("[INFO] Market data loaded")

    evaluated = []
    updated = 0

    for i, fpath in enumerate(replay_files):
        sample = load_json(fpath)
        if not sample:
            continue

        # Skip if already evaluated (unless --force)
        fo = sample.get("forward_outcome", {})
        if fo.get("computed_at") and not force:
            evaluated.append(sample)
            continue

        # Compute forward outcomes
        outcome = compute_forward_outcome(sample, close_matrix, vix_series)
        sample["forward_outcome"] = outcome

        # Auto-label
        label, reason = auto_label(sample, outcome)
        sample["review_label"] = label
        sample["auto_label_reason"] = reason

        # Write back
        write_json(fpath, sample)
        evaluated.append(sample)
        updated += 1

        if updated % 100 == 0:
            print(f"  [{updated}] evaluated")

    print(f"[INFO] Updated {updated} samples, {len(evaluated)} total")
    return evaluated


# ---------------------------------------------------------------------------
# Statistics and reporting
# ---------------------------------------------------------------------------

def _group_stats(samples: list[dict], group_key: str) -> dict:
    """Compute label distribution and outcome stats grouped by group_key."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for s in samples:
        key = s.get(group_key) or s.get("system_judgment", {}).get(group_key, "unknown")
        groups[str(key)].append(s)

    stats = {}
    for key, group in groups.items():
        labels = [s.get("review_label", "needs_review") for s in group]
        label_counts = {}
        for lbl in labels:
            label_counts[lbl] = label_counts.get(lbl, 0) + 1

        stress_hits = sum(1 for s in group if s.get("forward_outcome", {}).get("stress_event_happened"))
        spy_1w_vals = [
            s["forward_outcome"]["spy"]["pct_1w"]
            for s in group
            if s.get("forward_outcome", {}).get("spy", {}).get("pct_1w") is not None
        ]
        mdd_vals = [
            s["forward_outcome"]["max_drawdown_1m"]
            for s in group
            if s.get("forward_outcome", {}).get("max_drawdown_1m") is not None
        ]

        useful_count = label_counts.get("useful", 0)
        total = len(group)
        useful_rate = useful_count / total if total > 0 else 0

        stats[key] = {
            "count": total,
            "label_counts": label_counts,
            "useful_rate": round(useful_rate, 3),
            "stress_hit_rate": round(stress_hits / total, 3) if total > 0 else 0,
            "avg_spy_1w": round(float(np.mean(spy_1w_vals)), 4) if spy_1w_vals else None,
            "avg_max_drawdown_1m": round(float(np.mean(mdd_vals)), 4) if mdd_vals else None,
        }

    return stats


def generate_summary(samples: list[dict]) -> dict:
    """Generate calibration_summary.json."""
    total = len(samples)
    labels = [s.get("review_label", "needs_review") for s in samples]
    label_dist = {}
    for lbl in labels:
        label_dist[lbl] = label_dist.get(lbl, 0) + 1

    summary = {
        "generated_at": utc_now().isoformat(),
        "total_samples": total,
        "label_distribution": label_dist,
        "by_sample_type": _group_stats(samples, "sample_type"),
        "by_decision": {},  # filled below
        "by_confidence": {},  # filled below
        "by_claim_tier": {},
    }

    # Group by decision, confidence, and claim_tier (all nested in system_judgment)
    decision_groups: dict[str, list[dict]] = defaultdict(list)
    conf_groups: dict[str, list[dict]] = defaultdict(list)
    tier_groups: dict[str, list[dict]] = defaultdict(list)
    for s in samples:
        j = s.get("system_judgment", {})
        decision_groups[str(j.get("decision", "unknown"))].append(s)
        conf_groups[str(j.get("confidence", "unknown"))].append(s)
        tier_groups[str(j.get("claim_tier", "unknown"))].append(s)

    for key, group in decision_groups.items():
        labels_g = [s.get("review_label", "needs_review") for s in group]
        useful = sum(1 for l in labels_g if l == "useful")
        total_g = len(group)
        stress_hits = sum(1 for s in group if s.get("forward_outcome", {}).get("stress_event_happened"))
        summary["by_decision"][key] = {
            "count": total_g,
            "useful_rate": round(useful / total_g, 3) if total_g > 0 else 0,
            "stress_hit_rate": round(stress_hits / total_g, 3) if total_g > 0 else 0,
            "label_counts": {l: labels_g.count(l) for l in set(labels_g)},
        }

    for key, group in conf_groups.items():
        labels_g = [s.get("review_label", "needs_review") for s in group]
        useful = sum(1 for l in labels_g if l == "useful")
        total_g = len(group)
        summary["by_confidence"][key] = {
            "count": total_g,
            "useful_rate": round(useful / total_g, 3) if total_g > 0 else 0,
            "label_counts": {l: labels_g.count(l) for l in set(labels_g)},
        }

    for key, group in tier_groups.items():
        labels_g = [s.get("review_label", "needs_review") for s in group]
        useful = sum(1 for l in labels_g if l == "useful")
        total_g = len(group)
        summary["by_claim_tier"][key] = {
            "count": total_g,
            "useful_rate": round(useful / total_g, 3) if total_g > 0 else 0,
            "label_counts": {l: labels_g.count(l) for l in set(labels_g)},
        }

    # Confidence calibration check
    conf_calibration = {}
    for conf_level in ["low", "medium", "high"]:
        group = conf_groups.get(conf_level, [])
        if not group:
            continue
        stress_rates = []
        for s in group:
            fo = s.get("forward_outcome", {})
            spy_1w = fo.get("spy", {}).get("pct_1w")
            if spy_1w is not None:
                stress_rates.append(abs(spy_1w))
        conf_calibration[conf_level] = {
            "count": len(group),
            "avg_abs_spy_1w": round(float(np.mean(stress_rates)), 4) if stress_rates else None,
        }
    summary["confidence_calibration"] = conf_calibration

    return summary


def generate_report(summary: dict, samples: list[dict]) -> str:
    """Generate evaluation_report.md."""
    lines = [
        "# Feedback Sample Evaluation Report",
        "",
        f"**Generated:** {summary['generated_at']}",
        f"**Total samples:** {summary['total_samples']}",
        "",
        "---",
        "",
        "## Label Distribution",
        "",
        "| Label | Count | Pct |",
        "|-------|------:|----:|",
    ]

    total = summary["total_samples"]
    for label, count in sorted(summary["label_distribution"].items(), key=lambda x: -x[1]):
        pct = count / total * 100 if total > 0 else 0
        lines.append(f"| {label} | {count} | {pct:.1f}% |")

    lines += [
        "",
        "## By Sample Type",
        "",
        "| Type | N | Useful Rate | Stress Hit Rate | Avg SPY 1w | Avg MDD 1m |",
        "|------|--:|------------:|----------------:|-----------:|-----------:|",
    ]
    for stype, stats in sorted(summary["by_sample_type"].items()):
        lines.append(
            f"| {stype} | {stats['count']} | {stats['useful_rate']:.1%} | "
            f"{stats['stress_hit_rate']:.1%} | "
            f"{stats.get('avg_spy_1w', 'N/A')} | "
            f"{stats.get('avg_max_drawdown_1m', 'N/A')} |"
        )

    lines += [
        "",
        "## By Decision",
        "",
        "| Decision | N | Useful Rate | Stress Hit Rate |",
        "|----------|--:|------------:|----------------:|",
    ]
    for dec, stats in sorted(summary.get("by_decision", {}).items()):
        lines.append(
            f"| {dec} | {stats['count']} | {stats['useful_rate']:.1%} | {stats['stress_hit_rate']:.1%} |"
        )

    lines += [
        "",
        "## Confidence Calibration",
        "",
        "Does higher confidence correlate with higher-stress outcomes?",
        "",
        "| Confidence | N | Useful Rate | Avg |SPY 1w| |",
        "|------------|--:|------------:|-------------:|",
    ]
    for conf, stats in sorted(summary.get("confidence_calibration", {}).items()):
        avg_abs = stats.get("avg_abs_spy_1w", "N/A")
        if avg_abs is not None and avg_abs != "N/A":
            avg_abs = f"{avg_abs:.4f}"
        lines.append(f"| {conf} | {stats['count']} | — | {avg_abs} |")

    # Also add useful rate by confidence
    lines += [
        "",
        "| Confidence | N | Useful Rate | Misleading Rate | False Positive Rate | Missed Stress Rate |",
        "|------------|--:|------------:|----------------:|--------------------:|-------------------:|",
    ]
    for conf, stats in sorted(summary.get("by_confidence", {}).items()):
        lc = stats.get("label_counts", {})
        n = stats["count"]
        useful = lc.get("useful", 0)
        misleading = lc.get("misleading", 0)
        fp = lc.get("false_positive", 0)
        missed = lc.get("missed_stress", 0)
        if n > 0:
            lines.append(
                f"| {conf} | {n} | "
                f"{useful/n:.1%} | "
                f"{misleading/n:.1%} | "
                f"{fp/n:.1%} | "
                f"{missed/n:.1%} |"
            )
        else:
            lines.append(f"| {conf} | {n} | — | — | — | — |")

    lines += [
        "",
        "## Claim Tier Analysis",
        "",
        "| Tier | N | Useful Rate |",
        "|-----:|--:|------------:|",
    ]
    for tier, stats in sorted(summary.get("by_claim_tier", {}).items()):
        lines.append(f"| {tier} | {stats['count']} | {stats['useful_rate']:.1%} |")

    # Key findings
    lines += [
        "",
        "## Key Findings",
        "",
    ]

    useful = summary["label_distribution"].get("useful", 0)
    fp = summary["label_distribution"].get("false_positive", 0)
    missed = summary["label_distribution"].get("missed_stress", 0)
    misleading = summary["label_distribution"].get("misleading", 0)

    if total > 0:
        lines.append(f"- **Useful rate:** {useful/total:.1%} ({useful}/{total})")
        lines.append(f"- **False positive rate:** {fp/total:.1%} ({fp}/{total})")
        lines.append(f"- **Missed stress rate:** {missed/total:.1%} ({missed}/{total})")
        lines.append(f"- **Misleading rate:** {misleading/total:.1%} ({misleading}/{total})")

    # Confidence discrimination
    conf_stats = summary.get("by_confidence", {})
    low_useful = conf_stats.get("low", {}).get("useful_rate", 0)
    med_useful = conf_stats.get("medium", {}).get("useful_rate", 0)
    high_useful = conf_stats.get("high", {}).get("useful_rate", 0)
    lines.append("")
    lines.append("### Confidence Discrimination")
    lines.append(f"- Low confidence useful rate: {low_useful:.1%}")
    lines.append(f"- Medium confidence useful rate: {med_useful:.1%}")
    lines.append(f"- High confidence useful rate: {high_useful:.1%}")
    if med_useful > low_useful:
        lines.append("- ✅ Medium confidence shows higher useful rate than low — calibration improving")
    else:
        lines.append("- ⚠️ Medium confidence does NOT outperform low — calibration needs work")

    # Sample type analysis
    st_stats = summary.get("by_sample_type", {})
    stress_useful = st_stats.get("stress_window", {}).get("useful_rate", 0)
    quiet_useful = st_stats.get("quiet_window", {}).get("useful_rate", 0)
    fa_useful = st_stats.get("false_alarm", {}).get("useful_rate", 0)
    lines.append("")
    lines.append("### Sample Type Performance")
    lines.append(f"- Stress window useful rate: {stress_useful:.1%}")
    lines.append(f"- Quiet window useful rate: {quiet_useful:.1%}")
    lines.append(f"- False alarm useful rate: {fa_useful:.1%}")

    lines += [
        "",
        "---",
        "",
        "*This report is auto-generated by evaluate_feedback_samples.py. "
        "Labels are auto-assigned and should be human-reviewed for accuracy.*",
    ]

    return "\n".join(lines)


def generate_failure_cases(samples: list[dict], top_n: int = 50) -> str:
    """Generate failure_cases.md with cases needing human review."""
    failures = [
        s for s in samples
        if s.get("review_label") in ("misleading", "missed_stress", "false_positive", "needs_review")
    ]
    # Sort: misleading first, then missed_stress, then false_positive
    priority = {"misleading": 0, "missed_stress": 1, "false_positive": 2, "needs_review": 3}
    failures.sort(key=lambda s: (priority.get(s.get("review_label", ""), 9), s.get("as_of_date", "")))

    lines = [
        "# Failure Cases for Human Review",
        "",
        f"**Generated:** {utc_now().isoformat()}",
        f"**Total failures:** {len(failures)}",
        f"**Showing top:** {min(top_n, len(failures))}",
        "",
        "---",
        "",
    ]

    for i, sample in enumerate(failures[:top_n]):
        j = sample.get("system_judgment", {})
        fo = sample.get("forward_outcome", {})
        spy = fo.get("spy", {})
        vix = fo.get("vix", {})
        state = sample.get("system_state", {})

        lines += [
            f"## {i+1}. {sample.get('sample_id', 'unknown')}",
            "",
            f"**Date:** {sample.get('as_of_date')} | "
            f"**Type:** {sample.get('sample_type')} | "
            f"**Label:** `{sample.get('review_label')}`",
            "",
            f"**Auto reason:** {sample.get('auto_label_reason', 'N/A')}",
            "",
            "### System State",
            f"- M={state.get('m_value')}, D={state.get('d_value')}, K={state.get('k_value')}, X={state.get('x_value')}",
            "",
            "### System Judgment",
            f"- Decision: {j.get('decision')} | Confidence: {j.get('confidence')} | Tier: {j.get('claim_tier')}",
            f"- Mechanism: {j.get('mechanism_hypothesis', 'N/A')}",
            "",
            "### Forward Outcome",
            f"- SPY 1d: {spy.get('pct_1d')} | 1w: {spy.get('pct_1w')} | 1m: {spy.get('pct_1m')}",
            f"- VIX at: {vix.get('level_at')} | 1w change: {vix.get('change_1w')}",
            f"- Max drawdown 1m: {fo.get('max_drawdown_1m')}",
            f"- Stress event: {fo.get('stress_event_happened')}",
            "",
            "### Review Notes",
            f"_Please add your review notes here:_",
            "",
            "---",
            "",
        ]

    lines += [
        "*Auto-generated by evaluate_feedback_samples.py. "
        "Add human review notes to each case after inspection.*",
    ]

    return "\n".join(lines)


def generate_review_queue(samples: list[dict]) -> list[dict]:
    """Generate review_queue.jsonl for human review."""
    queue = []
    for s in samples:
        label = s.get("review_label", "needs_review")
        if label in ("misleading", "missed_stress", "false_positive", "needs_review"):
            queue.append({
                "sample_id": s.get("sample_id"),
                "as_of_date": s.get("as_of_date"),
                "sample_type": s.get("sample_type"),
                "review_label": label,
                "auto_label_reason": s.get("auto_label_reason", ""),
                "decision": s.get("system_judgment", {}).get("decision"),
                "confidence": s.get("system_judgment", {}).get("confidence"),
                "claim_tier": s.get("system_judgment", {}).get("claim_tier"),
                "spy_1w": s.get("forward_outcome", {}).get("spy", {}).get("pct_1w"),
                "max_drawdown_1m": s.get("forward_outcome", {}).get("max_drawdown_1m"),
                "stress_event": s.get("forward_outcome", {}).get("stress_event_happened"),
            })

    # Priority sort: misleading > missed_stress > false_positive > needs_review
    priority = {"misleading": 0, "missed_stress": 1, "false_positive": 2, "needs_review": 3}
    queue.sort(key=lambda x: (priority.get(x["review_label"], 9), x["as_of_date"]))

    return queue


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate feedback samples: compute forward outcomes and auto-label"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-evaluate even if forward outcome already computed"
    )
    parser.add_argument(
        "--top", type=int, default=50,
        help="Number of failure cases to show in report (default: 50)"
    )
    args = parser.parse_args()

    # Ensure output directory
    ensure_dir(REPORT_PATH.parent)

    # Step 1: Evaluate all samples
    samples = evaluate_all(force=args.force)
    if not samples:
        return

    # Step 2: Generate summary
    summary = generate_summary(samples)
    write_json(SUMMARY_PATH, summary)
    print(f"[OK] Calibration summary: {SUMMARY_PATH}")

    # Step 3: Generate report
    report = generate_report(summary, samples)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"[OK] Evaluation report: {REPORT_PATH}")

    # Step 4: Generate failure cases
    failure_report = generate_failure_cases(samples, top_n=args.top)
    FAILURE_PATH.write_text(failure_report, encoding="utf-8")
    print(f"[OK] Failure cases: {FAILURE_PATH}")

    # Step 5: Generate review queue
    queue = generate_review_queue(samples)
    with open(REVIEW_QUEUE_PATH, "w", encoding="utf-8") as f:
        for entry in queue:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"[OK] Review queue: {REVIEW_QUEUE_PATH} ({len(queue)} entries)")

    # Print summary to stdout
    print(f"\n{'='*60}")
    print(f"EVALUATION COMPLETE")
    print(f"{'='*60}")
    print(f"Total samples: {summary['total_samples']}")
    for label, count in sorted(summary["label_distribution"].items(), key=lambda x: -x[1]):
        pct = count / summary["total_samples"] * 100
        print(f"  {label}: {count} ({pct:.1f}%)")


if __name__ == "__main__":
    main()
