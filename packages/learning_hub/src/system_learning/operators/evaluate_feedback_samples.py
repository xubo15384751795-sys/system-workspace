#!/usr/bin/env python3
"""Evaluate forward outcomes for feedback sample pool records.

Reads Data/feedback_samples/sample_manifest.jsonl, backfills forward_outcome
for elapsed windows using cross-asset and benchmark panels, auto-labels samples,
and mirrors evaluated records to Output/state/feedback_samples/replay_runs/.

Usage:
    python3 scripts/commands/weekly/evaluate_feedback_samples.py
    python3 scripts/commands/weekly/evaluate_feedback_samples.py --force
    python3 scripts/commands/weekly/evaluate_feedback_samples.py --limit 50
"""
from __future__ import annotations

import argparse
import json
from typing import Any

import pandas as pd
import yaml

from verity.runtime._data_paths import (
    resolve_benchmark_panel_path,
    resolve_cross_asset_panel_path,
)
from verity.runtime.runtime_io import ROOT, ensure_dir, utc_now, write_json

MANIFEST = ROOT / "Data" / "feedback_samples" / "sample_manifest.jsonl"
REPLAY_DIR = ROOT / "Output" / "state" / "feedback_samples" / "replay_runs"
POLICY = ROOT / "governance" / "feedback_sampling_policy.yaml"
CALIBRATION_PATH = ROOT / "Output" / "state" / "feedback_samples" / "calibration_summary.json"
EVAL_REPORT = ROOT / "Output" / "state" / "feedback_samples" / "evaluation_report.md"

ETF_SYMBOLS = ("SPY", "HYG", "TLT", "GLD")
BENCHMARK_SERIES = {"VIX": "FRED:VIXCLS", "MOVE": "CBOE:MOVE"}
HORIZONS = {"1d": 1, "1w": 5, "1m": 20, "3m": 60}
HORIZON_KEYS = {"1d": "pct_1d", "1w": "pct_1w", "1m": "pct_1m", "3m": "pct_3m"}


def _load_policy() -> dict[str, Any]:
    if not POLICY.is_file():
        return {}
    return yaml.safe_load(POLICY.read_text(encoding="utf-8")) or {}


def _load_market_series() -> dict[str, pd.Series]:
    series: dict[str, pd.Series] = {}
    etf_path = resolve_cross_asset_panel_path()
    if etf_path.exists():
        etf = pd.read_parquet(etf_path)
        etf["date"] = pd.to_datetime(etf["date"])
        for symbol in ETF_SYMBOLS:
            part = etf[etf["symbol"] == symbol].sort_values("date")
            part = part[part["close"].astype(float) > 0].drop_duplicates("date")
            if not part.empty:
                series[symbol] = part.set_index("date")["close"].astype(float)

    bench_path = resolve_benchmark_panel_path()
    if bench_path.exists():
        panel = pd.read_parquet(bench_path)
        panel["date"] = pd.to_datetime(panel["date"])
        for label, series_id in BENCHMARK_SERIES.items():
            part = panel[panel["series_id"] == series_id].sort_values("date")
            part = part.drop_duplicates("date")
            if not part.empty:
                series[label] = part.set_index("date")["value"].astype(float)
    return series


def _entry_and_exit(
    series: pd.Series, as_of: str, horizon_rows: int
) -> tuple[pd.Timestamp, float, pd.Timestamp, float] | None:
    clean = series.dropna().sort_index()
    if clean.empty:
        return None
    as_of_ts = pd.Timestamp(as_of)
    positions = clean.index.searchsorted(as_of_ts, side="left")
    if positions >= len(clean):
        return None
    exit_pos = positions + horizon_rows
    if exit_pos >= len(clean):
        return None
    entry_date = clean.index[positions]
    exit_date = clean.index[exit_pos]
    entry_value = float(clean.iloc[positions])
    exit_value = float(clean.iloc[exit_pos])
    if entry_value <= 0 or exit_value <= 0:
        return None
    return entry_date, entry_value, exit_date, exit_value


def _max_drawdown_1m(spy: pd.Series, as_of: str, rows: int = 20) -> float | None:
    clean = spy.dropna().sort_index()
    if clean.empty:
        return None
    as_of_ts = pd.Timestamp(as_of)
    start = clean.index.searchsorted(as_of_ts, side="left")
    end = start + rows
    if start >= len(clean) or end >= len(clean):
        return None
    window = clean.iloc[start : end + 1]
    if window.empty or (window <= 0).any():
        return None
    peak = window.cummax()
    dd = (window / peak - 1.0).min()
    return float(round(dd, 6))


def _build_forward_outcome(as_of: str, market: dict[str, pd.Series]) -> dict[str, Any] | None:
    etf_out: dict[str, dict[str, float | None]] = {s.lower(): {} for s in ETF_SYMBOLS}
    vix_out: dict[str, float | None] = {}
    move_out: dict[str, float | None] = {}

    any_metric = False
    for horizon, rows in HORIZONS.items():
        key = HORIZON_KEYS[horizon]
        for symbol in ETF_SYMBOLS:
            points = _entry_and_exit(market.get(symbol, pd.Series(dtype=float)), as_of, rows)
            if points is None:
                etf_out[symbol.lower()][key] = None
                continue
            _, entry, _, exit_ = points
            etf_out[symbol.lower()][key] = round(exit_ / entry - 1.0, 6)
            any_metric = True

        for index_name in ("VIX", "MOVE"):
            points = _entry_and_exit(market.get(index_name, pd.Series(dtype=float)), as_of, rows)
            if points is None:
                continue
            _, entry, _, exit_ = points
            any_metric = True
            if horizon == "1d":
                if index_name == "VIX":
                    vix_out["level_at"] = round(entry, 4)
                    vix_out["change_1d"] = round(exit_ - entry, 4)
            elif horizon == "1w":
                if index_name == "VIX":
                    vix_out["change_1w"] = round(exit_ - entry, 4)
                else:
                    move_out["change_1w"] = round(exit_ - entry, 4)
            elif horizon == "1m":
                if index_name == "VIX":
                    vix_out["change_1m"] = round(exit_ - entry, 4)
                else:
                    move_out["change_1m"] = round(exit_ - entry, 4)
                    move_out["level_at"] = round(entry, 4)

    if not any_metric:
        return None

    mdd = _max_drawdown_1m(market.get("SPY", pd.Series(dtype=float)), as_of)
    thresholds = (_load_policy().get("auto_labeling") or {}).get("stress_thresholds") or {}
    mdd_sig = float(thresholds.get("max_drawdown_significant", 0.05))
    vix_sig = float(thresholds.get("vix_spike_significant", 5.0))
    hyg_sig = float(thresholds.get("hyg_drop_significant", -0.03))

    stress = False
    if mdd is not None and mdd <= -mdd_sig:
        stress = True
    if vix_out.get("change_1w") is not None and vix_out["change_1w"] >= vix_sig:
        stress = True
    hyg_1w = etf_out.get("hyg", {}).get("pct_1w")
    if hyg_1w is not None and hyg_1w <= hyg_sig:
        stress = True

    return {
        "computed_at": utc_now().isoformat().replace("+00:00", "Z"),
        "spy": etf_out.get("spy", {}),
        "hyg": etf_out.get("hyg", {}),
        "tlt": etf_out.get("tlt", {}),
        "gld": etf_out.get("gld", {}),
        "vix": vix_out,
        "move": move_out,
        "max_drawdown_1m": mdd,
        "stress_event_happened": stress,
    }


def _auto_label(sample: dict[str, Any], fo: dict[str, Any]) -> tuple[str, str]:
    decision = str(sample.get("system_judgment", {}).get("decision", "")).upper()
    warned = decision in {"WATCH", "RESEARCH_REVIEW", "ACTIVE_WATCH"}
    stress = bool(fo.get("stress_event_happened"))
    mdd = fo.get("max_drawdown_1m")
    spy_1m = (fo.get("spy") or {}).get("pct_1m")
    thresholds = (_load_policy().get("auto_labeling") or {}).get("stress_thresholds") or {}
    mdd_mod = float(thresholds.get("max_drawdown_moderate", 0.02))

    if warned and stress:
        return "useful", "WATCH/REVIEW and stress materialized within forward window"
    if warned and not stress and mdd is not None and mdd > -mdd_mod:
        return "false_positive", "Warning issued but no stress and drawdown < moderate threshold"
    if not warned and stress and mdd is not None and mdd <= -float(thresholds.get("max_drawdown_significant", 0.05)):
        return "missed_stress", "NO_TRADE/low alert but stress event within window"
    if warned and stress and spy_1m is not None and abs(spy_1m) < 0.01:
        return "too_early", "Warning preceded stress by more than actionable 1m window"
    if sample.get("sample_type") == "caselab_context":
        return "needs_review", "CaseLab context samples require human review"
    return "correct_but_low_value", "Evaluated; no strong auto-label rule matched"


def evaluate_samples(*, force: bool = False, limit: int | None = None) -> dict[str, Any]:
    if not MANIFEST.exists():
        return {"status": "no_manifest", "evaluated": 0}

    market = _load_market_series()
    if not market:
        return {"status": "no_market_data", "evaluated": 0}

    lines = [ln for ln in MANIFEST.read_text(encoding="utf-8").splitlines() if ln.strip()]
    samples = [json.loads(ln) for ln in lines]
    ensure_dir(REPLAY_DIR)

    evaluated = 0
    skipped = 0
    not_evaluable = 0
    label_counts: dict[str, int] = {}

    for sample in samples:
        if limit is not None and evaluated >= limit:
            break
        fo_existing = sample.get("forward_outcome") or {}
        if fo_existing.get("computed_at") and not force:
            skipped += 1
            continue

        as_of = sample.get("as_of_date", "")
        fo = _build_forward_outcome(as_of, market)
        if fo is None:
            sample["review_label"] = "not_evaluable"
            sample["auto_label_reason"] = "Insufficient forward market data for minimum horizons"
            not_evaluable += 1
            continue

        label, reason = _auto_label(sample, fo)
        sample["forward_outcome"] = fo
        sample["review_label"] = label
        sample["auto_label_reason"] = reason
        evaluated += 1
        label_counts[label] = label_counts.get(label, 0) + 1

        replay_path = REPLAY_DIR / f"{sample['sample_id']}.json"
        write_json(replay_path, sample)

    tmp = MANIFEST.with_suffix(".jsonl.tmp")
    tmp.write_text(
        "\n".join(json.dumps(s, ensure_ascii=False) for s in samples) + ("\n" if samples else ""),
        encoding="utf-8",
    )
    tmp.replace(MANIFEST)

    summary = {
        "schema_version": "feedback_samples.calibration_summary.v1",
        "generated_at": utc_now().isoformat().replace("+00:00", "Z"),
        "total_samples": len(samples),
        "newly_evaluated": evaluated,
        "skipped_already_evaluated": skipped,
        "not_evaluable": not_evaluable,
        "label_counts": label_counts,
        "eligible_for_calibration": 0,
        "calibration_set_count": sum(
            1
            for sample in samples
            if sample.get("eligibility") == "eligible"
            and sample.get("calibration_set") is True
            and sample.get("allowed_to_affect_core_judgment") is False
        ),
        "allowed_to_affect_core_judgment": False,
    }
    ensure_dir(CALIBRATION_PATH.parent)
    write_json(CALIBRATION_PATH, summary)

    report_lines = [
        "# Feedback Sample Evaluation",
        "",
        f"Total samples: {len(samples)}",
        f"Newly evaluated: {evaluated}",
        f"Skipped (already done): {skipped}",
        f"Not evaluable: {not_evaluable}",
        "",
        "## Label distribution (this run)",
    ]
    for label, count in sorted(label_counts.items()):
        report_lines.append(f"- {label}: {count}")
    EVAL_REPORT.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    summary["status"] = "ok"
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Recompute even if computed_at exists")
    parser.add_argument("--limit", type=int, default=None, help="Max new evaluations this run")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = evaluate_samples(force=args.force, limit=args.limit)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Feedback evaluation: {result.get('status')}")
        print(f"  Newly evaluated: {result.get('newly_evaluated', 0)}")
        print(f"  Skipped: {result.get('skipped_already_evaluated', 0)}")
        print(f"  Not evaluable: {result.get('not_evaluable', 0)}")
        print(f"  Summary: {CALIBRATION_PATH}")


if __name__ == "__main__":
    main()
