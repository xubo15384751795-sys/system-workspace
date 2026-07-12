#!/usr/bin/env python3
"""WP-T6 framework validation protocol for nonlinear-framework candidates.

The runner is research-only: it writes Output/validation artifacts and does not
promote candidates into production paths.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    from professional_methods import (
        build_forward_stress_events,
        causal_pit,
        har_realized_variance_forecast,
        incremental_logistic_test,
        lead_profile,
        probability_metrics,
        stationary_bootstrap_metric,
    )
except ModuleNotFoundError:
    from scripts.professional_methods import (
        build_forward_stress_events,
        causal_pit,
        har_realized_variance_forecast,
        incremental_logistic_test,
        lead_profile,
        probability_metrics,
        stationary_bootstrap_metric,
    )

try:
    from _data_paths import resolve_benchmark_panel_path, resolve_cross_asset_panel_path
except ModuleNotFoundError:
    from scripts._data_paths import (
        resolve_benchmark_panel_path,
        resolve_cross_asset_panel_path,
    )


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PANEL = resolve_benchmark_panel_path()
DEFAULT_CROSS_ASSET = resolve_cross_asset_panel_path()
DEFAULT_CHANNELS = ROOT / "Output" / "sandbox" / "structural_replay_v2" / "all_signals.parquet"
DEFAULT_OUTPUT = ROOT / "Output" / "validation" / "framework_validation"
DEFAULT_CASE_DATES = ("2008-09-15", "2020-03-16", "2023-03-10")

CHANNEL_ALIASES: dict[str, tuple[str, ...]] = {
    "M": ("channel_M", "M"),
    "D": ("channel_D_contraction", "D_contraction", "D"),
    "K": ("channel_K", "K"),
    "X": ("channel_X_agg", "X_agg", "X", "x_stock_agg"),
}


def build_event_battery(
    panel: pd.DataFrame,
    cross_asset: pd.DataFrame | None = None,
    *,
    horizon: int = 20,
) -> tuple[dict[str, pd.Series], dict[str, Any]]:
    """Build causal event battery E1-E5, skipping unavailable series."""
    panel = _normalize_panel(panel)
    cross = _normalize_cross_asset(cross_asset) if cross_asset is not None else {}
    events: dict[str, pd.Series] = {}
    status: dict[str, Any] = {}

    # Event input series extracted from the benchmark panel inherit the panel's
    # calendar-day union grid (weekends/holidays as NaN rows). The forward
    # rolling windows below use min_periods=horizon, which on a calendar grid
    # is never satisfied (weekend NaNs break every window) and silently yields
    # all-NaN event labels. Drop to a trading-day-only index before forward
    # rolling so E1/E2/E3/E5 are not silently emptied (E4/TLT was unaffected
    # only because it comes from the per-symbol cross-asset dict, which is
    # already trading-day-only). Events are reindexed to the common index
    # later in run(), so dropping non-trading days here is safe.
    def _td(series: pd.Series | None) -> pd.Series | None:
        return None if series is None else series.dropna()

    equity = _td(_first_market_series(panel, cross, ("SPY", "SPX", "CBOE:SPX", "close")))
    if equity is not None:
        e1 = build_forward_stress_events(equity, horizon=horizon, vol_quantile=0.95, drawdown_threshold=-0.08, logic="or")
        events["E1_equity"] = e1["stress_event"]
        status["E1_equity"] = {"status": "ok", "definition": "or_tight: vol q95 or drawdown < -8%"}
    else:
        status["E1_equity"] = {"status": "skipped", "reason": "SPY/SPX price unavailable"}

    move = _td(_first_series(panel, ("FRED:MOVE", "CBOE:MOVE", "MOVE", "CBOE:VXTLT")))
    if move is None:
        move = _td(_first_market_series(panel, cross, ("MOVE",)))
    if move is not None:
        events["E2_rates_vol"] = _forward_level_event(move, horizon=horizon, quantile=0.90)
        status["E2_rates_vol"] = {"status": "ok", "definition": "max next 20d MOVE >= causal q90"}
    else:
        status["E2_rates_vol"] = {"status": "skipped", "reason": "MOVE unavailable"}

    funding = _td(_funding_spread(panel))
    if funding is not None:
        events["E3_funding"] = _forward_level_event(funding, horizon=horizon, quantile=0.95)
        status["E3_funding"] = {"status": "ok", "definition": "SOFR-IORB / EFFR-IOER max next 20d >= causal q95"}
    else:
        status["E3_funding"] = {"status": "skipped", "reason": "funding spread inputs unavailable"}

    tlt = _td(_first_market_series(panel, cross, ("TLT",)))
    if tlt is not None:
        events["E4_duration"] = _forward_drawdown_event(tlt, horizon=horizon, threshold=-0.05)
        status["E4_duration"] = {"status": "ok", "definition": "TLT 20d forward drawdown <= -5%"}
    else:
        status["E4_duration"] = {"status": "skipped", "reason": "TLT unavailable"}

    hy_oas = _td(_first_series(panel, ("FRED:BAMLH0A0HYM2", "BAMLH0A0HYM2", "HY_OAS")))
    if hy_oas is not None:
        events["E5_credit"] = _forward_widening_event(hy_oas, horizon=horizon, threshold=0.50)
        status["E5_credit"] = {"status": "ok", "definition": "HY OAS 20d widening >= 50bp"}
    else:
        status["E5_credit"] = {"status": "skipped", "reason": "BAMLH0A0HYM2 unavailable"}

    return events, status


def build_validation_candidates(
    channels: pd.DataFrame,
    panel: pd.DataFrame,
    cross_asset: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Build baselines, channel composites, and ablations for WP-T6."""
    channels = _normalize_channels(channels)
    panel = _normalize_panel(panel)
    cross = _normalize_cross_asset(cross_asset) if cross_asset is not None else {}
    index = channels.index.union(panel.index).sort_values()
    for data in cross.values():
        index = index.union(data.index).sort_values()
    channels = channels.reindex(index)
    panel = panel.reindex(index)

    channel_pits = pd.DataFrame({column: causal_pit(channels[column], min_periods=126) for column in channels}, index=index)
    candidates = pd.DataFrame(index=index)
    candidates["framework_full"] = channel_pits.mean(axis=1, skipna=True)
    for channel in ("M", "D", "K", "X"):
        subset = [column for column in channel_pits.columns if column != channel]
        if subset:
            candidates[f"framework_no_{channel}"] = channel_pits[subset].mean(axis=1, skipna=True)

    vol_parts: dict[str, pd.Series] = {}
    vix = _first_series(panel, ("FRED:VIXCLS", "CBOE:VIXCLS", "VIX", "VIXCLS"))
    if vix is not None:
        vol_parts["vix"] = causal_pit(vix, min_periods=126)
    equity = _first_market_series(panel, cross, ("SPY", "SPX", "CBOE:SPX", "close"))
    if equity is not None:
        returns = np.log(equity).diff()
        har = har_realized_variance_forecast(returns)
        vol_parts["har_rv"] = causal_pit(har, min_periods=126)
    if vol_parts:
        candidates["vol_only"] = pd.DataFrame(vol_parts, index=index).mean(axis=1, skipna=True)

    funding = _funding_spread(panel)
    if funding is not None:
        candidates["funding_only"] = causal_pit(funding.reindex(index), min_periods=126)

    public = _public_composite(panel)
    if public is not None:
        candidates["public_composite"] = public.reindex(index)

    combo_columns = [column for column in ("vol_only", "funding_only", "public_composite", "framework_full") if column in candidates]
    if combo_columns:
        candidates["combination"] = candidates[combo_columns].mean(axis=1, skipna=True)

    diagnostics = {
        "channel_coverage": {column: float(channels[column].notna().mean()) for column in channels},
        "candidate_coverage": {column: float(candidates[column].notna().mean()) for column in candidates},
    }
    return candidates, diagnostics


def evaluate_protocol(
    events: dict[str, pd.Series],
    candidates: pd.DataFrame,
    *,
    bootstrap_reps: int = 100,
    case_dates: tuple[str, ...] = DEFAULT_CASE_DATES,
) -> dict[str, Any]:
    """Evaluate every candidate against every available event definition."""
    report: dict[str, Any] = {}
    baseline_cols = [column for column in ("vol_only", "funding_only", "public_composite") if column in candidates]
    for event_name, target in events.items():
        event_report: dict[str, Any] = {"candidate_evaluation": {}, "incremental_tests": {}}
        for candidate_name in candidates:
            probability = candidates[candidate_name]
            event_report["candidate_evaluation"][candidate_name] = {
                "metrics": probability_metrics(target, probability),
                "lead_profile": lead_profile(target, probability),
                "stationary_bootstrap_auc": stationary_bootstrap_metric(
                    target, probability, reps=bootstrap_reps, mean_block=20
                ),
                "case_calendar_lead_profile": _case_calendar_profile(probability, case_dates=case_dates),
            }
        if baseline_cols and "framework_full" in candidates:
            event_report["incremental_tests"]["framework_full_vs_public_baselines"] = incremental_logistic_test(
                target,
                candidates[baseline_cols],
                candidates["framework_full"],
                embargo=20,
            )
        report[event_name] = event_report
    return report


def run(args: argparse.Namespace) -> dict[str, Any]:
    panel = load_benchmark_panel(args.panel)
    cross_asset = load_cross_asset(args.cross_asset) if args.cross_asset and args.cross_asset.exists() else None
    channels = pd.read_parquet(args.channels)
    events, event_status = build_event_battery(panel, cross_asset, horizon=args.horizon)
    candidates, diagnostics = build_validation_candidates(channels, panel, cross_asset)
    common_index = candidates.index
    events = {name: event.reindex(common_index) for name, event in events.items()}
    evaluation = evaluate_protocol(
        events,
        candidates.reindex(common_index),
        bootstrap_reps=args.bootstrap_reps,
        case_dates=tuple(args.case_dates),
    )
    events_frame = pd.DataFrame(events, index=common_index)
    args.output.mkdir(parents=True, exist_ok=True)
    candidates.to_csv(args.output / "candidates.csv", index_label="date")
    events_frame.to_csv(args.output / "events.csv", index_label="date")
    report = {
        "schema_version": "system.framework_validation.wp_t6.v1",
        "mode": "research_shadow",
        "inputs": {
            "panel": str(args.panel),
            "cross_asset": str(args.cross_asset) if args.cross_asset else None,
            "channels": str(args.channels),
        },
        "event_status": event_status,
        "candidate_diagnostics": diagnostics,
        "evaluation": evaluation,
    }
    (args.output / "report.json").write_text(json.dumps(_json_safe(report), indent=2, allow_nan=False), encoding="utf-8")
    (args.output / "report.md").write_text(render_markdown(report), encoding="utf-8")
    return report


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Framework Validation Protocol",
        "",
        "- Mode: `research_shadow`",
        "- Promotion: none; this report is validation evidence only.",
        "",
        "## Event Battery",
        "",
    ]
    for name, status in report["event_status"].items():
        lines.append(f"- `{name}`: `{status['status']}` - {status.get('definition') or status.get('reason')}")
    lines.extend(["", "## Candidate Metrics", ""])
    for event_name, event_report in report["evaluation"].items():
        lines.extend([f"### {event_name}", "", "| Candidate | ROC-AUC | PR-AUC | Brier | n |", "|---|---:|---:|---:|---:|"])
        for candidate, result in event_report["candidate_evaluation"].items():
            metrics = result["metrics"]
            lines.append(
                f"| {candidate} | {_fmt(metrics.get('roc_auc'))} | {_fmt(metrics.get('pr_auc'))} | "
                f"{_fmt(metrics.get('brier'))} | {metrics.get('n', 0)} |"
            )
        lines.append("")
        # Incremental significance gate (prereg pass_criteria: DM p < 0.05).
        # Rendered per event so the §7.5 acceptance verdict is auditable.
        inc = event_report.get("incremental_tests", {}).get("framework_full_vs_public_baselines")
        if isinstance(inc, dict) and inc.get("status") == "ok":
            delta = inc.get("delta", {}) if isinstance(inc.get("delta"), dict) else {}
            dm = delta.get("diebold_mariano", {}) if isinstance(delta.get("diebold_mariano"), dict) else {}
            gate_pass = (delta.get("pr_auc", 0) or 0) > 0 and (dm.get("p_value") or 1.0) < 0.05
            lines.extend([
                f"#### Incremental gate — `{event_name}`",
                "",
                f"- ΔPR-AUC: **{_fmt(delta.get('pr_auc'))}**",
                f"- ΔROC-AUC: {_fmt(delta.get('roc_auc'))}",
                f"- Diebold-Mariano: stat={_fmt(dm.get('dm_stat'))}, "
                f"p-value=**{_fmt(dm.get('p_value'))}** "
                f"(mean_diff={_fmt(dm.get('mean_diff'))}, n={dm.get('n', 'n/a')})",
                f"- Pass criterion (ΔPR-AUC>0 AND DM p<0.05): **{'PASS' if gate_pass else 'FAIL'}**",
                "",
            ])
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--cross-asset", type=Path, default=DEFAULT_CROSS_ASSET)
    parser.add_argument("--channels", type=Path, default=DEFAULT_CHANNELS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--horizon", type=int, default=20)
    parser.add_argument("--bootstrap-reps", type=int, default=100)
    parser.add_argument("--case-dates", nargs="*", default=list(DEFAULT_CASE_DATES))
    return parser.parse_args()


def load_benchmark_panel(path: Path) -> pd.DataFrame:
    raw = pd.read_parquet(path)
    if {"date", "series_id", "value"}.issubset(raw.columns):
        raw = raw.copy()
        raw["date"] = pd.to_datetime(raw["date"], errors="coerce")
        raw["value"] = pd.to_numeric(raw["value"], errors="coerce")
        return pd.concat(
            {str(k): g.groupby("date", sort=True)["value"].last() for k, g in raw.dropna(subset=["date"]).groupby("series_id")},
            axis=1,
        ).sort_index()
    return _normalize_panel(raw)


def load_cross_asset(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path)


def _normalize_panel(frame: pd.DataFrame) -> pd.DataFrame:
    panel = frame.copy()
    if "date" in panel.columns:
        panel["date"] = pd.to_datetime(panel["date"], errors="coerce")
        panel = panel.set_index("date")
    elif _looks_date_like(panel.index):
        try:
            panel.index = pd.to_datetime(panel.index)
        except Exception:
            pass
    panel = panel.sort_index()
    if not panel.index.is_unique:
        panel = panel.groupby(level=0).last()
    return panel


def _looks_date_like(index: pd.Index) -> bool:
    if isinstance(index, pd.DatetimeIndex):
        return False
    if index.dtype.kind in {"M", "O", "U", "S"}:
        sample = index.dropna()[:5]
        return len(sample) > 0 and any("-" in str(value) or "/" in str(value) for value in sample)
    return False


def _normalize_channels(channels: pd.DataFrame) -> pd.DataFrame:
    frame = _normalize_panel(channels)
    lower = {str(column).lower(): column for column in frame.columns}
    out: dict[str, pd.Series] = {}
    for canonical, aliases in CHANNEL_ALIASES.items():
        for alias in aliases:
            column = alias if alias in frame.columns else lower.get(alias.lower())
            if column is not None:
                out[canonical] = pd.to_numeric(frame[column], errors="coerce")
                break
    if not out:
        raise ValueError("No recognized channel columns found")
    return pd.DataFrame(out, index=frame.index)


def _normalize_cross_asset(frame: pd.DataFrame | None) -> dict[str, pd.DataFrame]:
    if frame is None or frame.empty:
        return {}
    raw = frame.copy()
    if "date" in raw.columns:
        raw["date"] = pd.to_datetime(raw["date"], errors="coerce")
    if "symbol" not in raw.columns:
        wide = _normalize_panel(raw)
        return {str(column): pd.DataFrame({"close": pd.to_numeric(wide[column], errors="coerce")}) for column in wide.columns}
    out: dict[str, pd.DataFrame] = {}
    for symbol, group in raw.dropna(subset=["date"]).groupby("symbol"):
        group = group.set_index("date").sort_index()
        if not group.index.is_unique:
            group = group.groupby(level=0).last()
        out[str(symbol)] = group
    return out


def _first_series(frame: pd.DataFrame, aliases: tuple[str, ...]) -> pd.Series | None:
    lower = {str(column).lower(): column for column in frame.columns}
    for alias in aliases:
        column = alias if alias in frame.columns else lower.get(alias.lower())
        if column is not None:
            return pd.to_numeric(frame[column], errors="coerce")
    return None


def _first_market_series(
    panel: pd.DataFrame,
    cross: dict[str, pd.DataFrame],
    aliases: tuple[str, ...],
) -> pd.Series | None:
    direct = _first_series(panel, aliases)
    if direct is not None:
        return direct
    for alias in aliases:
        frame = cross.get(alias)
        if frame is None:
            continue
        for column in ("close", "adj_close", "value", "price"):
            if column in frame:
                return pd.to_numeric(frame[column], errors="coerce")
    return None


def _funding_spread(panel: pd.DataFrame) -> pd.Series | None:
    sofr = _first_series(panel, ("FRED:SOFR", "SOFR"))
    iorb = _first_series(panel, ("FRED:IORB", "IORB"))
    effr = _first_series(panel, ("FRED:EFFR", "EFFR"))
    ioer = _first_series(panel, ("FRED:IOER", "IOER"))
    spread = pd.Series(np.nan, index=panel.index, name="funding_spread")
    used = False
    splice = pd.Timestamp("2018-04-03")
    if effr is not None and ioer is not None:
        spread.loc[spread.index < splice] = (effr - ioer).loc[spread.index < splice]
        used = True
    if sofr is not None and iorb is not None:
        spread.loc[spread.index >= splice] = (sofr - iorb).loc[spread.index >= splice]
        used = True
    if used:
        return spread
    return None


def _public_composite(panel: pd.DataFrame) -> pd.Series | None:
    parts: dict[str, pd.Series] = {}
    for name, aliases in {
        "nfci": ("FRED:NFCI", "NFCI"),
        "ofr_fsi": ("OFR_FSI", "FRED:OFR_FSI"),
        "ciss": ("CISS", "ECB:CISS", "FRED:CISS"),
    }.items():
        series = _first_series(panel, aliases)
        if series is not None:
            parts[name] = causal_pit(series, min_periods=126)
    if not parts:
        return None
    return pd.DataFrame(parts, index=panel.index).mean(axis=1, skipna=True).rename("public_composite")


def _forward_level_event(series: pd.Series, *, horizon: int, quantile: float, min_history: int = 252) -> pd.Series:
    x = pd.to_numeric(series, errors="coerce")
    future = x.shift(-1).rolling(horizon, min_periods=horizon).max().shift(-(horizon - 1))
    threshold = x.shift(1).rolling(2520, min_periods=min_history).quantile(quantile)
    return (future >= threshold).where(future.notna() & threshold.notna()).rename("event")


def _forward_drawdown_event(series: pd.Series, *, horizon: int, threshold: float) -> pd.Series:
    px = pd.to_numeric(series, errors="coerce")
    future_min = px.shift(-1).rolling(horizon, min_periods=horizon).min().shift(-(horizon - 1))
    drawdown = future_min / px - 1.0
    return (drawdown <= threshold).where(drawdown.notna()).rename("event")


def _forward_widening_event(series: pd.Series, *, horizon: int, threshold: float) -> pd.Series:
    x = pd.to_numeric(series, errors="coerce")
    future_max = x.shift(-1).rolling(horizon, min_periods=horizon).max().shift(-(horizon - 1))
    widening = future_max - x
    return (widening >= threshold).where(widening.notna()).rename("event")


def _case_calendar_profile(probability: pd.Series, *, case_dates: tuple[str, ...], offsets: tuple[int, ...] = (20, 10, 5, 0)) -> dict[str, Any]:
    series = pd.to_numeric(probability, errors="coerce").sort_index()
    values = series.to_numpy(dtype=float)
    positions = series.index
    out: dict[str, Any] = {}
    for case in case_dates:
        date = pd.Timestamp(case)
        pos = int(positions.searchsorted(date, side="right") - 1)
        row: dict[str, Any] = {}
        for offset in offsets:
            idx = pos - offset
            row[f"t_minus_{offset}"] = _finite_or_none(values[idx]) if 0 <= idx < len(values) else None
        out[str(date.date())] = row
    return out


def _finite_or_none(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, bool)) or value is None:
        return value
    if isinstance(value, (np.integer, int)) and not isinstance(value, bool):
        return int(value)
    return _finite_or_none(value)


def _fmt(value: Any) -> str:
    numeric = _finite_or_none(value)
    return "n/a" if numeric is None else f"{numeric:.3f}"


if __name__ == "__main__":
    cli_args = parse_args()
    cli_report = run(cli_args)
    print(json.dumps({"status": "ok", "output": str(cli_args.output), "events": list(cli_report["evaluation"])}))
