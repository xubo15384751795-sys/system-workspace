#!/usr/bin/env python3
"""WP-T3 stability diagnostics and critical-slowing candidates."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from workbench.measurement.professional_methods import causal_pit, rolling_absorption_ratio


ROOT = Path(__file__).resolve().parents[5]
DEFAULT_PANEL = ROOT / "Output" / "state" / "sandbox" / "structural_replay_v2" / "all_signals.parquet"
DEFAULT_OUTPUT = ROOT / "Output" / "state" / "validation" / "stability_diagnostics"

CHANNEL_ALIASES: dict[str, tuple[str, ...]] = {
    "M": ("channel_M", "M"),
    "D_contraction": ("channel_D_contraction", "D_contraction", "D"),
    "K": ("channel_K", "K"),
    "x_stock_agg": ("channel_X_agg", "x_stock_agg", "X_agg", "X"),
}


def rolling_var_lambda_max(panel: pd.DataFrame, window: int = 252, step: int = 5) -> pd.Series:
    """Rolling standardized VAR(1) spectral radius."""
    data = _select_channels(panel)
    result = pd.Series(np.nan, index=data.index, name="lambda_max")
    min_obs = max(data.shape[1] * 10, min(window, 60))
    for end in range(window, len(data) + 1, max(1, step)):
        sample = data.iloc[end - window:end].dropna()
        if len(sample) < min_obs:
            continue
        coef = _fit_var1_coef(_standardize(sample))
        if coef is not None:
            result.iloc[end - 1] = _spectral_radius(coef)
    return result.ffill(limit=max(1, step - 1))


def rls_var_lambda_max(panel: pd.DataFrame, forgetting: float = 0.99) -> pd.Series:
    """Recursive least-squares VAR(1) spectral radius for smooth daily paths."""
    data = _select_channels(panel)
    z = _expanding_standardize(data)
    k = z.shape[1]
    p = k + 1
    beta = np.zeros((p, k), dtype=float)
    cov = np.eye(p) * 1_000.0
    result = pd.Series(np.nan, index=z.index, name="lambda_max_rls")
    forgetting = float(np.clip(forgetting, 0.90, 0.9999))
    updates = 0
    values = z.to_numpy(dtype=float)
    for i in range(1, len(z)):
        x_lag = values[i - 1]
        y = values[i]
        if not np.isfinite(x_lag).all() or not np.isfinite(y).all():
            continue
        x = np.r_[1.0, x_lag]
        denom = forgetting + float(x @ cov @ x)
        gain = (cov @ x) / denom
        error = y - x @ beta
        beta = beta + np.outer(gain, error)
        cov = (cov - np.outer(gain, x @ cov)) / forgetting
        updates += 1
        if updates >= max(30, k * 10):
            result.iloc[i] = _spectral_radius(beta[1:, :].T)
    return result


def critical_slowing_score(
    panel: pd.DataFrame,
    window: int = 126,
    long_window: int = 252,
    step: int = 5,
    min_periods: int = 63,
) -> pd.Series:
    """Equal-weight lag-1 autocorr, variance-ratio, and absorption-ratio PITs."""
    data = _select_channels(panel)
    lag_scores: dict[str, pd.Series] = {}
    var_scores: dict[str, pd.Series] = {}
    for column in data:
        series = pd.to_numeric(data[column], errors="coerce")
        lag = series.rolling(window, min_periods=min_periods).corr(series.shift(1))
        short_var = series.rolling(window, min_periods=min_periods).var()
        long_var = series.rolling(long_window, min_periods=max(min_periods, long_window // 2)).var()
        lag_scores[f"{column}_lag1"] = causal_pit(lag, min_periods=min_periods)
        var_scores[f"{column}_var_ratio"] = causal_pit(short_var / long_var.replace(0.0, np.nan), min_periods=min_periods)
    absorption = rolling_absorption_ratio(data, window=long_window, min_periods=min_periods, step=step)
    components = pd.DataFrame({**lag_scores, **var_scores, "absorption_ratio": causal_pit(absorption, min_periods=min_periods)}, index=data.index)
    return components.mean(axis=1, skipna=True).rename("csd_score")


def build_stability_candidates(
    panel: pd.DataFrame,
    *,
    window: int = 252,
    step: int = 5,
    forgetting: float = 0.99,
    bootstrap_reps: int = 200,
    block_size: int = 20,
    seed: int = 1729,
) -> pd.DataFrame:
    """Build WP-T3 lambda/CSD candidates plus a bootstrap noise guard."""
    data = _select_channels(panel)
    lam = rolling_var_lambda_max(data, window=window, step=step)
    rls = rls_var_lambda_max(data, forgetting=forgetting)
    csd = critical_slowing_score(data, window=max(63, window // 2), long_window=window, step=step)
    ci = _rolling_lambda_bootstrap_ci(data, window=window, step=step, reps=bootstrap_reps, block_size=block_size, seed=seed)
    q90 = _causal_quantile(lam, 0.90, window=1260, min_periods=max(63, window // 2))
    return pd.DataFrame(
        {
            "lambda_max": lam,
            "lambda_max_rls": rls,
            "csd_score": csd,
            "candidate_lambda_max_pit": causal_pit(lam, min_periods=max(63, window // 2)),
            "candidate_csd_score_pit": causal_pit(csd, min_periods=max(63, window // 2)),
            "lambda_ci_low": ci["low"],
            "lambda_ci_high": ci["high"],
            "lambda_q90": q90,
            "lambda_noise_guard_signal": (ci["low"] > q90).where(ci["low"].notna() & q90.notna()),
        },
        index=data.index,
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    panel = pd.read_parquet(args.panel)
    candidates = build_stability_candidates(
        panel,
        window=args.window,
        step=args.step,
        forgetting=args.forgetting,
        bootstrap_reps=args.bootstrap_reps,
        block_size=args.block_size,
    )
    args.output.mkdir(parents=True, exist_ok=True)
    candidates.to_csv(args.output / "stability_candidates.csv", index_label="date")
    report = {
        "schema_version": "system.stability_diagnostics.wp_t3.v1",
        "mode": "research_shadow",
        "inputs": {"panel": str(args.panel)},
        "rows": int(len(candidates)),
        "latest": {
            key: _finite_or_none(value)
            for key, value in (candidates.dropna(how="all").iloc[-1].to_dict() if not candidates.dropna(how="all").empty else {}).items()
        },
    }
    (args.output / "report.json").write_text(json.dumps(_json_safe(report), indent=2, allow_nan=False), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--window", type=int, default=252)
    parser.add_argument("--step", type=int, default=5)
    parser.add_argument("--forgetting", type=float, default=0.99)
    parser.add_argument("--bootstrap-reps", type=int, default=200)
    parser.add_argument("--block-size", type=int, default=20)
    return parser.parse_args()


def _select_channels(panel: pd.DataFrame) -> pd.DataFrame:
    frame = panel.copy()
    if "date" in frame.columns:
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame = frame.set_index("date")
    elif _looks_date_like(frame.index):
        frame.index = pd.to_datetime(frame.index, errors="coerce")
    frame = frame.sort_index()
    if not frame.index.is_unique:
        frame = frame.groupby(level=0).last()
    out: dict[str, pd.Series] = {}
    lower = {str(column).lower(): column for column in frame.columns}
    for canonical, aliases in CHANNEL_ALIASES.items():
        for alias in aliases:
            column = alias if alias in frame.columns else lower.get(alias.lower())
            if column is not None:
                out[canonical] = pd.to_numeric(frame[column], errors="coerce")
                break
    if len(out) < 2:
        raise ValueError("At least two recognized channels are required for VAR diagnostics")
    return pd.DataFrame(out, index=frame.index)


def _looks_date_like(index: pd.Index) -> bool:
    if isinstance(index, pd.DatetimeIndex):
        return False
    if index.dtype.kind in {"M", "O", "U", "S"}:
        sample = index.dropna()[:5]
        return len(sample) > 0 and any("-" in str(value) or "/" in str(value) for value in sample)
    return False


def _standardize(frame: pd.DataFrame) -> pd.DataFrame:
    scale = frame.std(ddof=0).replace(0.0, np.nan)
    return (frame - frame.mean()) / scale


def _expanding_standardize(frame: pd.DataFrame, min_periods: int = 30) -> pd.DataFrame:
    mean = frame.expanding(min_periods=min_periods).mean().shift(1)
    std = frame.expanding(min_periods=min_periods).std(ddof=0).shift(1).replace(0.0, np.nan)
    return (frame - mean) / std


def _fit_var1_coef(sample: pd.DataFrame) -> np.ndarray | None:
    clean = sample.dropna()
    if len(clean) < sample.shape[1] * 5:
        return None
    x = clean.shift(1).iloc[1:].to_numpy(dtype=float)
    y = clean.iloc[1:].to_numpy(dtype=float)
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        return None
    design = np.column_stack([np.ones(len(x)), x])
    try:
        beta, *_ = np.linalg.lstsq(design, y, rcond=None)
    except np.linalg.LinAlgError:
        return None
    return beta[1:, :].T


def _spectral_radius(matrix: np.ndarray) -> float:
    try:
        eig = np.linalg.eigvals(matrix)
    except np.linalg.LinAlgError:
        return float("nan")
    return float(np.max(np.abs(eig))) if eig.size else float("nan")


def _rolling_lambda_bootstrap_ci(
    data: pd.DataFrame,
    *,
    window: int,
    step: int,
    reps: int,
    block_size: int,
    seed: int,
) -> pd.DataFrame:
    low = pd.Series(np.nan, index=data.index, name="low")
    high = pd.Series(np.nan, index=data.index, name="high")
    if reps <= 0:
        return pd.DataFrame({"low": low, "high": high})
    rng = np.random.default_rng(seed)
    min_obs = max(data.shape[1] * 10, min(window, 60))
    for end in range(window, len(data) + 1, max(1, step)):
        sample = data.iloc[end - window:end].dropna()
        if len(sample) < min_obs:
            continue
        values: list[float] = []
        for _ in range(reps):
            boot = _block_sample(sample, block_size=block_size, rng=rng)
            coef = _fit_var1_coef(_standardize(boot))
            if coef is not None:
                radius = _spectral_radius(coef)
                if np.isfinite(radius):
                    values.append(radius)
        if values:
            low.iloc[end - 1], high.iloc[end - 1] = np.quantile(values, [0.05, 0.95])
    return pd.DataFrame({"low": low.ffill(limit=max(1, step - 1)), "high": high.ffill(limit=max(1, step - 1))})


def _block_sample(sample: pd.DataFrame, *, block_size: int, rng: np.random.Generator) -> pd.DataFrame:
    n = len(sample)
    block_size = max(2, min(int(block_size), n))
    pieces: list[pd.DataFrame] = []
    while sum(len(piece) for piece in pieces) < n:
        start = int(rng.integers(0, max(1, n - block_size + 1)))
        pieces.append(sample.iloc[start:start + block_size])
    out = pd.concat(pieces, axis=0).iloc[:n].copy()
    out.index = sample.index
    return out


def _causal_quantile(series: pd.Series, q: float, window: int, min_periods: int) -> pd.Series:
    return series.shift(1).rolling(window, min_periods=min_periods).quantile(q).rename(f"q{int(q * 100)}")


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


if __name__ == "__main__":
    cli_args = parse_args()
    cli_report = run(cli_args)
    print(json.dumps({"status": "ok", "output": str(cli_args.output), "rows": cli_report["rows"]}))
