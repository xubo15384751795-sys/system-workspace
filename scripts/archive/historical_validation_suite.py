#!/usr/bin/env python3
"""Historical validation suite for M/D/K/X channel signals.

This is an experimental backtest/diagnostic tool. It reads the frozen
structural replay output and tests channels against historical market
outcomes without changing the live runtime path.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from _runtime_io import ROOT, write_json

SIGNALS_PATH = ROOT / "Output" / "sandbox" / "structural_replay_v2" / "all_signals.parquet"
BENCHMARK_PATH = ROOT / "Data" / "harvester" / "exports" / "latest" / "data" / "benchmark_panel.parquet"
OUTPUT_DIR = ROOT / "Output" / "backtest" / "historical_validation"

CHANNEL_COLUMNS = {
    "M": "channel_M",
    "D": "channel_D_contraction",
    "K": "channel_K",
    "X": "channel_X_agg",
}
DEFAULT_HORIZONS = (1, 5, 10, 20, 60)
DEFAULT_START = "1997-01-01"
DEFAULT_END = "2026-12-31"
TRAIN_DAYS = 252 * 5
TEST_DAYS = 252
MIN_EVAL_ROWS = 60


def _round(value: Any, digits: int = 4) -> Any:
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return value
    if not math.isfinite(value):
        return None
    return round(value, digits)


def _binomial_p_value(successes: int, n: int, p0: float = 0.5) -> float | None:
    """Two-sided normal-approximation binomial p-value."""
    if n <= 0:
        return None
    sd = math.sqrt(n * p0 * (1.0 - p0))
    if sd == 0:
        return None
    z = (abs(successes - n * p0) - 0.5) / sd
    p = math.erfc(max(0.0, z) / math.sqrt(2.0))
    return max(0.0, min(1.0, p))


def _safe_corr(a: pd.Series, b: pd.Series) -> float | None:
    aligned = pd.concat([a, b], axis=1).dropna()
    if len(aligned) < MIN_EVAL_ROWS:
        return None
    if aligned.iloc[:, 0].std() == 0 or aligned.iloc[:, 1].std() == 0:
        return None
    return float(aligned.iloc[:, 0].corr(aligned.iloc[:, 1]))


def load_series(series_id: str) -> pd.Series:
    panel = pd.read_parquet(BENCHMARK_PATH)
    panel["date"] = pd.to_datetime(panel["date"])
    subset = panel[panel["series_id"] == series_id].sort_values("date").drop_duplicates("date")
    if subset.empty:
        raise SystemExit(f"Missing benchmark series: {series_id}")
    series = subset.set_index("date")["value"].astype(float).sort_index()
    return series[~series.index.duplicated(keep="last")]


def load_channels(start: str, end: str) -> pd.DataFrame:
    signals = pd.read_parquet(SIGNALS_PATH)
    signals.index = pd.to_datetime(signals.index)
    missing = [col for col in CHANNEL_COLUMNS.values() if col not in signals.columns]
    if missing:
        raise SystemExit(f"Missing channel columns in {SIGNALS_PATH}: {missing}")

    channels = signals[list(CHANNEL_COLUMNS.values())].rename(
        columns={v: k for k, v in CHANNEL_COLUMNS.items()}
    )
    channels["AVG"] = channels[list(CHANNEL_COLUMNS)].mean(axis=1, skipna=True)
    abs_channels = channels[list(CHANNEL_COLUMNS)].abs()
    channels["ABS_MAX_VALUE"] = abs_channels.max(axis=1)
    channels["ABS_MAX"] = pd.Series(pd.NA, index=channels.index, dtype="object")
    has_channel = abs_channels.notna().any(axis=1)
    channels.loc[has_channel, "ABS_MAX"] = abs_channels.loc[has_channel].idxmax(axis=1)
    channels["DISAGREEMENT"] = _sign_disagreement(channels[list(CHANNEL_COLUMNS)])
    return channels.loc[start:end].sort_index()


def _sign_disagreement(channels: pd.DataFrame) -> pd.Series:
    signs = np.sign(channels)
    sign_count = signs.replace(0, np.nan).count(axis=1)
    positive = (signs > 0).sum(axis=1)
    negative = (signs < 0).sum(axis=1)
    minority = pd.concat([positive, negative], axis=1).min(axis=1)
    return (minority / sign_count.replace(0, np.nan)).fillna(0.0)


def build_dataset(start: str, end: str, horizons: tuple[int, ...]) -> pd.DataFrame:
    channels = load_channels(start, end)
    spx = load_series("CBOE:SPX").loc[start:end]
    df = channels.join(spx.rename("SPX"), how="inner")
    df["SPX_ret_1d"] = df["SPX"].pct_change()
    df["SPX_vol_20d"] = df["SPX_ret_1d"].rolling(20, min_periods=10).std()
    df["SPX_ret_63d_past"] = df["SPX"].pct_change(63)
    df["SPX_ret_252d_past"] = df["SPX"].pct_change(252)

    for h in horizons:
        forward = df["SPX"].pct_change(h).shift(-h)
        df[f"fwd_ret_{h}d"] = forward
        df[f"fwd_up_{h}d"] = forward > 0
        df[f"fwd_abs_{h}d"] = forward.abs()
        df[f"fwd_vol_up_{h}d"] = df["SPX_vol_20d"].shift(-h) > df["SPX_vol_20d"]
        min_periods = max(1, min(h, 5))
        rolling_min = df["SPX"].shift(-1).rolling(h, min_periods=min_periods).min().shift(-(h - 1))
        df[f"fwd_drawdown_{h}d"] = (rolling_min / df["SPX"]) - 1.0
        df[f"fwd_stress_{h}d"] = df[f"fwd_drawdown_{h}d"] <= -0.05
    return df


def data_profile(df: pd.DataFrame, start: str, end: str) -> dict[str, Any]:
    date_diffs = df.index.to_series().diff().dt.days.dropna()
    median_gap = float(date_diffs.median()) if not date_diffs.empty else None
    frequency_hint = "daily_or_trading_day" if median_gap is not None and median_gap <= 3 else "weekly_or_sparse"
    profile: dict[str, Any] = {
        "requested_start": start,
        "requested_end": end,
        "actual_start": str(df.index.min().date()) if len(df) else None,
        "actual_end": str(df.index.max().date()) if len(df) else None,
        "rows": int(len(df)),
        "median_calendar_gap_days": _round(median_gap, 2),
        "frequency_hint": frequency_hint,
        "channel_non_null": {},
    }
    for ch in [*CHANNEL_COLUMNS, "AVG"]:
        profile["channel_non_null"][ch] = int(df[ch].notna().sum())
    return profile


def evaluate_direction(df: pd.DataFrame, horizons: tuple[int, ...]) -> dict[str, Any]:
    results: dict[str, Any] = {}
    candidates = [*CHANNEL_COLUMNS, "AVG"]
    for h in horizons:
        target = f"fwd_up_{h}d"
        horizon_results: dict[str, Any] = {}
        base = df[target].dropna()
        if len(base) >= MIN_EVAL_ROWS:
            up_rate = float(base.mean())
            baseline = max(up_rate, 1.0 - up_rate)
            horizon_results["baselines"] = {
                "always_up": _direction_metric(pd.Series(True, index=base.index), base),
                "always_majority": _round(baseline),
                "momentum_63d": _direction_metric(df["SPX_ret_63d_past"] > 0, df[target]),
                "momentum_252d": _direction_metric(df["SPX_ret_252d_past"] > 0, df[target]),
            }
        for ch in candidates:
            # Convention used by the existing monitor: negative = relief/bullish,
            # positive = stress/bearish.
            bullish = df[ch] < 0
            horizon_results[ch] = _direction_metric(bullish, df[target], signal=df[ch])
        horizon_results["ABS_MAX_ROUTER"] = _abs_max_direction_metric(df, target)
        results[f"{h}d"] = horizon_results
    return results


def _direction_metric(pred_bullish: pd.Series, target_up: pd.Series, signal: pd.Series | None = None) -> dict[str, Any]:
    aligned = pd.concat([pred_bullish.rename("pred"), target_up.rename("target")], axis=1).dropna()
    if signal is not None:
        aligned = aligned.join(signal.rename("signal"), how="inner").dropna()
    if len(aligned) < MIN_EVAL_ROWS:
        return {"n": int(len(aligned)), "status": "insufficient_data"}
    correct = aligned["pred"].astype(bool) == aligned["target"].astype(bool)
    successes = int(correct.sum())
    metric = {
        "n": int(len(aligned)),
        "agreement": _round(float(correct.mean())),
        "edge_vs_50": _round(float(correct.mean() - 0.5)),
        "p_value_vs_50": _round(_binomial_p_value(successes, len(aligned))),
    }
    if signal is not None:
        metric["ic"] = _round(_safe_corr(aligned["signal"], aligned["target"].astype(float)))
    return metric


def _abs_max_direction_metric(df: pd.DataFrame, target: str) -> dict[str, Any]:
    rows = []
    for date, row in df.iterrows():
        ch = row.get("ABS_MAX")
        if not isinstance(ch, str) or ch not in CHANNEL_COLUMNS:
            continue
        val = row.get(ch)
        outcome = row.get(target)
        if pd.isna(val) or pd.isna(outcome):
            continue
        rows.append((date, val < 0, bool(outcome), ch))
    if len(rows) < MIN_EVAL_ROWS:
        return {"n": len(rows), "status": "insufficient_data"}
    correct = [pred == actual for _, pred, actual, _ in rows]
    by_channel: dict[str, dict[str, Any]] = {}
    for ch in CHANNEL_COLUMNS:
        subset = [item for item in rows if item[3] == ch]
        if not subset:
            continue
        c = [pred == actual for _, pred, actual, _ in subset]
        by_channel[ch] = {"n": len(c), "agreement": _round(sum(c) / len(c))}
    return {
        "n": len(rows),
        "agreement": _round(sum(correct) / len(correct)),
        "edge_vs_50": _round(sum(correct) / len(correct) - 0.5),
        "p_value_vs_50": _round(_binomial_p_value(sum(correct), len(correct))),
        "selected_channel_mix": by_channel,
    }


def evaluate_by_year(df: pd.DataFrame, horizon: int) -> dict[str, Any]:
    target = f"fwd_up_{horizon}d"
    out: dict[str, Any] = {}
    for year, group in df.groupby(df.index.year):
        row: dict[str, Any] = {}
        for ch in [*CHANNEL_COLUMNS, "AVG"]:
            metric = _direction_metric(group[ch] < 0, group[target], signal=group[ch])
            if metric.get("status") != "insufficient_data":
                row[ch] = {
                    "n": metric["n"],
                    "agreement": metric["agreement"],
                    "ic": metric.get("ic"),
                }
        if row:
            best = max(row.items(), key=lambda kv: kv[1]["agreement"])
            row["best_channel"] = {"channel": best[0], "agreement": best[1]["agreement"]}
            out[str(year)] = row
    return out


def evaluate_state_targets(df: pd.DataFrame, horizons: tuple[int, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for h in horizons:
        hkey = f"{h}d"
        out[hkey] = {}
        stress = df[f"fwd_stress_{h}d"]
        vol_up = df[f"fwd_vol_up_{h}d"]
        df[f"fwd_abs_{h}d"]
        base_stress = float(stress.dropna().mean()) if stress.dropna().any() else 0.0
        base_vol = float(vol_up.dropna().mean()) if len(vol_up.dropna()) else 0.0
        for ch in CHANNEL_COLUMNS:
            valid = df[[ch, f"fwd_stress_{h}d", f"fwd_vol_up_{h}d", f"fwd_abs_{h}d"]].dropna()
            if len(valid) < MIN_EVAL_ROWS:
                out[hkey][ch] = {"n": int(len(valid)), "status": "insufficient_data"}
                continue
            threshold = valid[ch].abs().quantile(0.8)
            active = valid[valid[ch].abs() >= threshold]
            inactive = valid[valid[ch].abs() < threshold]
            out[hkey][ch] = {
                "n": int(len(valid)),
                "active_n": int(len(active)),
                "abs_threshold_p80": _round(threshold),
                "stress_rate_base": _round(base_stress),
                "stress_rate_active": _round(float(active[f"fwd_stress_{h}d"].mean())),
                "stress_rate_inactive": _round(float(inactive[f"fwd_stress_{h}d"].mean())),
                "vol_up_rate_base": _round(base_vol),
                "vol_up_rate_active": _round(float(active[f"fwd_vol_up_{h}d"].mean())),
                "vol_up_rate_inactive": _round(float(inactive[f"fwd_vol_up_{h}d"].mean())),
                "mean_abs_return_active": _round(float(active[f"fwd_abs_{h}d"].mean())),
                "mean_abs_return_inactive": _round(float(inactive[f"fwd_abs_{h}d"].mean())),
                "corr_abs_signal_abs_return": _round(_safe_corr(valid[ch].abs(), valid[f"fwd_abs_{h}d"])),
            }
    return out


def evaluate_conflict(df: pd.DataFrame, horizon: int) -> dict[str, Any]:
    target = f"fwd_up_{horizon}d"
    rows = df[[*CHANNEL_COLUMNS, "AVG", "DISAGREEMENT", target]].dropna()
    if len(rows) < MIN_EVAL_ROWS:
        return {"n": int(len(rows)), "status": "insufficient_data"}
    rows = rows.copy()
    rows["conflict_bucket"] = pd.cut(
        rows["DISAGREEMENT"],
        bins=[-0.01, 0.0, 0.25, 0.5],
        labels=["unanimous", "mild_conflict", "split"],
    )
    out: dict[str, Any] = {"n": int(len(rows)), "buckets": {}}
    for bucket, group in rows.groupby("conflict_bucket", observed=False):
        if len(group) < 20:
            continue
        avg_metric = _direction_metric(group["AVG"] < 0, group[target], signal=group["AVG"])
        out["buckets"][str(bucket)] = {
            "n": int(len(group)),
            "avg_direction_agreement": avg_metric.get("agreement"),
            "future_up_rate": _round(float(group[target].mean())),
            "mean_abs_avg_signal": _round(float(group["AVG"].abs().mean())),
        }
    return out


def walk_forward_router(df: pd.DataFrame, horizon: int) -> dict[str, Any]:
    """Choose the best historical channel on a rolling basis and test OOS."""
    target = f"fwd_up_{horizon}d"
    cols = [*CHANNEL_COLUMNS, "AVG"]
    frame = df[[*cols, target]].dropna().sort_index()
    if len(frame) < TRAIN_DAYS + MIN_EVAL_ROWS:
        return {"n": int(len(frame)), "status": "insufficient_data"}

    picks = []
    for i in range(TRAIN_DAYS, len(frame), TEST_DAYS):
        train = frame.iloc[i - TRAIN_DAYS:i]
        test = frame.iloc[i:min(i + TEST_DAYS, len(frame))]
        if len(test) < 20:
            continue
        scores = {}
        for ch in cols:
            metric = _direction_metric(train[ch] < 0, train[target], signal=train[ch])
            scores[ch] = metric.get("agreement") if metric.get("status") != "insufficient_data" else None
        valid_scores = {k: v for k, v in scores.items() if v is not None}
        if not valid_scores:
            continue
        chosen = max(valid_scores.items(), key=lambda kv: kv[1])[0]
        for date, row in test.iterrows():
            picks.append({
                "date": date,
                "chosen": chosen,
                "train_agreement": valid_scores[chosen],
                "pred": bool(row[chosen] < 0),
                "target": bool(row[target]),
            })

    if len(picks) < MIN_EVAL_ROWS:
        return {"n": len(picks), "status": "insufficient_data"}
    correct = [p["pred"] == p["target"] for p in picks]
    mix: dict[str, int] = {}
    for p in picks:
        mix[p["chosen"]] = mix.get(p["chosen"], 0) + 1
    by_year: dict[str, dict[str, Any]] = {}
    for year in sorted({p["date"].year for p in picks}):
        sub = [p for p in picks if p["date"].year == year]
        c = [p["pred"] == p["target"] for p in sub]
        if len(c) >= 20:
            by_year[str(year)] = {"n": len(c), "agreement": _round(sum(c) / len(c))}
    return {
        "n": len(picks),
        "agreement": _round(sum(correct) / len(correct)),
        "edge_vs_50": _round(sum(correct) / len(correct) - 0.5),
        "p_value_vs_50": _round(_binomial_p_value(sum(correct), len(correct))),
        "train_window_days": TRAIN_DAYS,
        "test_window_days": TEST_DAYS,
        "chosen_channel_mix": mix,
        "by_year": by_year,
    }


def write_markdown(report: dict[str, Any], path: Path) -> None:
    profile = report["data_profile"]
    lines = [
        "# Historical Validation Suite",
        "",
        f"Generated: {report['generated_at']}",
        "",
        "## Data Profile",
        "",
        f"- Window: {profile['actual_start']} to {profile['actual_end']}",
        f"- Rows: {profile['rows']:,}",
        f"- Frequency hint: {profile['frequency_hint']} (median gap {profile['median_calendar_gap_days']} calendar days)",
        "",
        "Channel non-null rows:",
    ]
    for ch, n in profile["channel_non_null"].items():
        lines.append(f"- {ch}: {n:,}")

    lines += ["", "## Direction Tests", ""]
    for hkey, hdata in report["direction_tests"].items():
        lines += [f"### Horizon {hkey}", "", "| Signal | N | Agreement | Edge vs 50 | p-value | IC |", "|---|---:|---:|---:|---:|---:|"]
        for name in [*CHANNEL_COLUMNS, "AVG", "ABS_MAX_ROUTER"]:
            metric = hdata.get(name, {})
            lines.append(
                f"| {name} | {metric.get('n', '')} | {_pct(metric.get('agreement'))} | "
                f"{_pct(metric.get('edge_vs_50'))} | {metric.get('p_value_vs_50', '')} | {metric.get('ic', '')} |"
            )
        baselines = hdata.get("baselines", {})
        if baselines:
            lines += ["", f"Baseline majority rate: {_pct(baselines.get('always_majority'))}", ""]

    lines += ["", "## State Tests", ""]
    for hkey, hdata in report["state_tests"].items():
        lines += [f"### Horizon {hkey}", "", "| Channel | Active N | Stress active | Stress inactive | Vol-up active | Vol-up inactive | Corr(abs signal, abs return) |", "|---|---:|---:|---:|---:|---:|---:|"]
        for ch, metric in hdata.items():
            lines.append(
                f"| {ch} | {metric.get('active_n', '')} | {_pct(metric.get('stress_rate_active'))} | "
                f"{_pct(metric.get('stress_rate_inactive'))} | {_pct(metric.get('vol_up_rate_active'))} | "
                f"{_pct(metric.get('vol_up_rate_inactive'))} | {metric.get('corr_abs_signal_abs_return', '')} |"
            )

    router = report["walk_forward_router"]
    lines += [
        "",
        "## Walk-Forward Router",
        "",
        f"- N: {router.get('n')}",
        f"- Agreement: {_pct(router.get('agreement'))}",
        f"- Chosen channel mix: `{json.dumps(router.get('chosen_channel_mix', {}), ensure_ascii=False)}`",
        "",
        "## Interpretation",
        "",
        report["interpretation"],
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _pct(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):.1%}"
    except (TypeError, ValueError):
        return str(value)


def build_interpretation(report: dict[str, Any], primary_horizon: int) -> str:
    hkey = f"{primary_horizon}d"
    hdata = report["direction_tests"].get(hkey, {})
    avg = hdata.get("AVG", {}).get("agreement")
    best_name = None
    best_score = -1.0
    for name in [*CHANNEL_COLUMNS, "AVG", "ABS_MAX_ROUTER"]:
        score = hdata.get(name, {}).get("agreement")
        if isinstance(score, (int, float)) and score > best_score:
            best_name = name
            best_score = float(score)
    router = report["walk_forward_router"]
    state = report["state_tests"].get(hkey, {})
    state_edges = []
    for ch, metric in state.items():
        a = metric.get("stress_rate_active")
        i = metric.get("stress_rate_inactive")
        if isinstance(a, (int, float)) and isinstance(i, (int, float)):
            state_edges.append((ch, a - i))
    state_edges.sort(key=lambda x: abs(x[1]), reverse=True)
    strongest_state = state_edges[0] if state_edges else None

    parts = []
    if avg is not None and avg < 0.5:
        parts.append("The simple four-channel average fails as a direction signal in this window.")
    elif avg is not None:
        parts.append("The simple four-channel average has non-negative direction evidence, but it still needs router and state-target checks.")
    if best_name:
        parts.append(f"The best raw direction candidate at {hkey} is {best_name} with {best_score:.1%} agreement.")
    if router.get("agreement") is not None:
        parts.append(f"The rolling walk-forward router scores {router['agreement']:.1%}; use this as the anti-hindsight check.")
    if strongest_state:
        parts.append(
            f"The strongest state-target separation is {strongest_state[0]} "
            f"with stress-rate spread {strongest_state[1]:+.1%}."
        )
    parts.append(
        "Decision rule: do not promote any channel from this suite unless it passes both direction or state-target evidence "
        "and the walk-forward router without using future year labels."
    )
    return " ".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run historical validation suite for M/D/K/X channels.")
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=DEFAULT_END)
    parser.add_argument("--horizons", default=",".join(str(h) for h in DEFAULT_HORIZONS))
    parser.add_argument("--primary-horizon", type=int, default=5)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    horizons = tuple(int(h.strip()) for h in args.horizons.split(",") if h.strip())
    if args.primary_horizon not in horizons:
        horizons = tuple(sorted((*horizons, args.primary_horizon)))

    df = build_dataset(args.start, args.end, horizons)
    report: dict[str, Any] = {
        "schema_version": "system.historical_validation_suite.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "inputs": {
            "signals_path": str(SIGNALS_PATH),
            "benchmark_path": str(BENCHMARK_PATH),
            "start": args.start,
            "end": args.end,
            "horizons_days": horizons,
            "primary_horizon_days": args.primary_horizon,
        },
        "data_profile": data_profile(df, args.start, args.end),
        "direction_tests": evaluate_direction(df, horizons),
        "yearly_direction_primary": evaluate_by_year(df, args.primary_horizon),
        "state_tests": evaluate_state_targets(df, horizons),
        "conflict_test_primary": evaluate_conflict(df, args.primary_horizon),
        "walk_forward_router": walk_forward_router(df, args.primary_horizon),
    }
    report["interpretation"] = build_interpretation(report, args.primary_horizon)

    out_dir = OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "historical_validation_report.json", report)
    write_markdown(report, out_dir / "historical_validation_report.md")
    df.reset_index(names="date").to_csv(out_dir / "historical_validation_panel.csv", index=False)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    else:
        print(f"Historical validation suite wrote {out_dir}")
        print(report["interpretation"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
