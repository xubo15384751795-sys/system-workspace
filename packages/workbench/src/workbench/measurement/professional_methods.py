"""Causal candidate methods for structural-stress measurement and validation.

These functions are research candidates.  They do not write current-state
artifacts and must be compared with incumbent methods before promotion.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass
from math import exp, sqrt
from statistics import NormalDist

import numpy as np
import pandas as pd

MAD_SCALE = 1.4826
TRADING_DAYS = 252


def causal_robust_zscore(
    series: pd.Series,
    window: int = TRADING_DAYS,
    min_periods: int | None = None,
    clip: float | None = 4.0,
) -> pd.Series:
    """Rolling median/MAD z-score using observations strictly before *t*."""
    numeric = pd.to_numeric(series, errors="coerce")
    min_periods = min_periods or max(20, window // 2)
    history = numeric.shift(1)
    median = history.rolling(window, min_periods=min_periods).median()
    mad = history.rolling(window, min_periods=min_periods).apply(
        lambda values: float(np.nanmedian(np.abs(values - np.nanmedian(values)))),
        raw=True,
    )
    fallback = history.rolling(window, min_periods=min_periods).std(ddof=0)
    scale = (MAD_SCALE * mad).where(mad > 0, fallback).replace(0.0, np.nan)
    result = (numeric - median) / scale
    result = result.replace([np.inf, -np.inf], np.nan)
    return result.clip(-clip, clip) if clip is not None else result


def causal_pit(
    series: pd.Series,
    window: int | None = 1260,
    min_periods: int = 126,
) -> pd.Series:
    """Empirical CDF score in [0, 1] based only on values before *t*.

    Ties receive their mid-rank, which avoids mapping a constant series to 1.
    """
    values = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    out = np.full(len(values), np.nan)
    for i, value in enumerate(values):
        if not np.isfinite(value):
            continue
        start = 0 if window is None else max(0, i - window)
        hist = values[start:i]
        hist = hist[np.isfinite(hist)]
        if len(hist) < min_periods:
            continue
        below = np.count_nonzero(hist < value)
        equal = np.count_nonzero(hist == value)
        out[i] = (below + 0.5 * equal) / len(hist)
    return pd.Series(out, index=series.index, name=f"{series.name or 'value'}_pit")


def folded_pit(
    series: pd.Series,
    window: int | None = 1260,
    min_periods: int = 126,
) -> pd.Series:
    """Two-sided pressure: farther from the causal median → hotter.

    ``s = 2 · |causal_pit(x) − 0.5|`` maps both tails into [0, 1].
    """
    pit = causal_pit(series, window=window, min_periods=min_periods)
    return (2.0 * (pit - 0.5).abs()).rename(f"{series.name or 'value'}_folded_pit")


def _channel_series(channels: pd.DataFrame, aliases: tuple[str, ...]) -> pd.Series | None:
    for name in aliases:
        if name in channels.columns:
            return pd.to_numeric(channels[name], errors="coerce")
    return None


def release_intensity_features(
    channels: pd.DataFrame,
    *,
    d_crit_q: float = 0.75,
    k_crit_q: float = 0.75,
    train_end: str | pd.Timestamp | None = "2018-12-31",
    min_periods: int = 126,
    pit_window: int | None = 1260,
) -> pd.DataFrame:
    """Paper R_t featureization (fully causal).

    Uses ``D_stress ≡ D_contraction`` (positive = contraction = stress).
    Critical quantiles are frozen on the train window of the PIT series.
    """
    d_raw = _channel_series(channels, ("channel_D_contraction", "D_contraction", "D"))
    k_raw = _channel_series(channels, ("channel_K", "K"))
    m_raw = _channel_series(channels, ("channel_M", "M"))
    x_raw = _channel_series(channels, ("channel_X_agg", "X_agg", "X", "x_stock_agg"))
    if d_raw is None or k_raw is None:
        raise ValueError("release_intensity_features requires D_contraction and K channels")

    d_pit = causal_pit(d_raw, window=pit_window, min_periods=min_periods)
    k_pit = causal_pit(k_raw, window=pit_window, min_periods=min_periods)

    if train_end is None:
        d_crit = float(d_pit.expanding(min_periods=min_periods).quantile(d_crit_q).iloc[-1])
        k_crit = float(k_pit.expanding(min_periods=min_periods).quantile(k_crit_q).iloc[-1])
    else:
        end = pd.Timestamp(train_end)
        d_train = d_pit.loc[d_pit.index <= end].dropna()
        k_train = k_pit.loc[k_pit.index <= end].dropna()
        if len(d_train) < min_periods or len(k_train) < min_periods:
            raise ValueError("insufficient train history to freeze D_crit / K_crit")
        d_crit = float(d_train.quantile(d_crit_q))
        k_crit = float(k_train.quantile(k_crit_q))

    d_stress = (d_pit - d_crit).clip(lower=0.0).rename("d_stress")
    k_stress = (k_pit - k_crit).clip(lower=0.0).rename("k_stress")
    f1 = (d_stress * k_stress).rename("f1_release_kernel")

    if x_raw is None:
        f2 = pd.Series(np.nan, index=channels.index, name="f2_forced_sale")
        f3 = pd.Series(np.nan, index=channels.index, name="f3_injection_amp")
        x_fold = pd.Series(np.nan, index=channels.index, name="x_folded")
    else:
        x_fold = folded_pit(x_raw, window=pit_window, min_periods=min_periods)
        f2 = (x_fold * (d_stress > 0).astype(float)).rename("f2_forced_sale")
        if m_raw is None:
            f3 = pd.Series(np.nan, index=channels.index, name="f3_injection_amp")
        else:
            m_fold = folded_pit(m_raw, window=pit_window, min_periods=min_periods)
            f3 = (m_fold * x_fold).rename("f3_injection_amp")

    return pd.DataFrame(
        {
            "d_stress": d_stress,
            "k_stress": k_stress,
            "f1_release_kernel": f1,
            "f2_forced_sale": f2,
            "f3_injection_amp": f3,
            "d_crit_train": d_crit,
            "k_crit_train": k_crit,
        },
        index=channels.index,
    )


def diebold_mariano_logloss(
    target: pd.Series,
    probability_a: pd.Series,
    probability_b: pd.Series,
    *,
    h: int = 1,
) -> dict[str, float | int]:
    """Diebold–Mariano test on binary log-loss (A vs B; negative → A better)."""
    aligned = pd.concat(
        [
            target.rename("y"),
            probability_a.rename("pa").clip(1e-6, 1 - 1e-6),
            probability_b.rename("pb").clip(1e-6, 1 - 1e-6),
        ],
        axis=1,
    ).dropna()
    if len(aligned) < 30 or aligned["y"].nunique() < 2:
        return {"n": int(len(aligned)), "mean_diff": np.nan, "dm_stat": np.nan, "p_value": np.nan}
    y = aligned["y"].astype(float).to_numpy()
    loss_a = -(y * np.log(aligned["pa"]) + (1 - y) * np.log(1 - aligned["pa"]))
    loss_b = -(y * np.log(aligned["pb"]) + (1 - y) * np.log(1 - aligned["pb"]))
    diff = (loss_a - loss_b).to_numpy(dtype=float)
    mean_diff = float(np.mean(diff))
    n = len(diff)
    # Newey–West variance for horizon h.
    gamma0 = float(np.mean((diff - mean_diff) ** 2))
    var = gamma0
    for lag in range(1, max(1, h)):
        cov = float(np.mean((diff[lag:] - mean_diff) * (diff[:-lag] - mean_diff)))
        var += 2.0 * (1.0 - lag / h) * cov
    se = sqrt(max(var, 0.0) / n)
    if se < 1e-12:
        return {"n": n, "mean_diff": mean_diff, "dm_stat": np.nan, "p_value": np.nan}
    dm_stat = mean_diff / se
    p_value = float(2.0 * (1.0 - NormalDist().cdf(abs(dm_stat))))
    return {"n": n, "mean_diff": mean_diff, "dm_stat": float(dm_stat), "p_value": p_value}


@dataclass(frozen=True)
class KalmanAnchorResult:
    anchor: pd.Series
    innovation_z: pd.Series
    anchor_velocity: pd.Series
    state_variance: pd.Series


def _estimate_local_level_variances(values: np.ndarray) -> tuple[float, float]:
    """MLE local-level (q, r) via statsmodels UnobservedComponents on *past-only* data."""
    from statsmodels.tsa.statespace.structural import UnobservedComponents

    clean = values[np.isfinite(values)]
    if len(clean) < 20:
        level_var = float(np.nanvar(clean)) if len(clean) else 1.0
        level_var = level_var or 1.0
        return max(level_var * 0.01, 1e-10), max(level_var * 0.25, 1e-10)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = UnobservedComponents(clean, level="local level")
        result = model.fit(disp=False, maxiter=100)
    # params: typically [sigma2.level, sigma2.irregular]
    params = np.asarray(result.params, dtype=float)
    if len(params) >= 2:
        q, r = float(params[0]), float(params[1])
    elif len(params) == 1:
        q, r = float(params[0]), float(params[0])
    else:
        q, r = 1e-4, 1.0
    return max(q, 1e-10), max(r, 1e-10)


def kalman_local_level(
    series: pd.Series,
    process_variance: float | None = None,
    observation_variance: float | None = None,
    *,
    refit_every: int = 21,
    min_fit: int = 126,
    max_fit_window: int = 1260,
) -> KalmanAnchorResult:
    """Causal local-level Kalman with MLE (q, r) from UnobservedComponents.

    Parameters are re-estimated only on observations strictly before the
    current point (expanding / trailing window), then the one-sided filter
    advances with those fixed variances until the next refit.

    Leading missing values are skipped (no variance inflation). Interior gaps
    use a fixed process-noise predict step so calendar NaNs cannot explode
    the state variance.
    """
    numeric = pd.to_numeric(series, errors="coerce")
    values = numeric.to_numpy(dtype=float)
    n = len(values)
    anchor = np.full(n, np.nan)
    innovations = np.full(n, np.nan)
    variances = np.full(n, np.nan)
    finite_idx = np.flatnonzero(np.isfinite(values))
    if finite_idx.size == 0:
        empty = pd.Series(np.nan, index=series.index)
        return KalmanAnchorResult(empty, empty.copy(), empty.copy(), empty.copy())

    first = int(finite_idx[0])
    state = float(values[first])
    variance = float(np.nanvar(values[finite_idx[: min(50, finite_idx.size)]]) or 1.0)
    q = process_variance
    r = observation_variance
    last_refit_count = -10**9
    observed_count = 0
    warmup_q = max(variance * 0.05, 1e-10)
    warmup_r = max(variance * 0.25, 1e-10)

    for i in range(first, n):
        value = values[i]
        q_use = float(q) if q is not None else warmup_q
        r_use = float(r) if r is not None else warmup_r
        predicted_state = state
        predicted_variance = variance + q_use
        if np.isfinite(value):
            observed_count += 1
            if (
                (process_variance is None or observation_variance is None)
                and observed_count >= min_fit
                and observed_count - last_refit_count >= refit_every
            ):
                start = max(first, i + 1 - max_fit_window)
                try:
                    q_hat, r_hat = _estimate_local_level_variances(values[start:i])
                except Exception:
                    q_hat, r_hat = warmup_q, warmup_r
                if process_variance is None:
                    q = q_hat
                if observation_variance is None:
                    r = r_hat
                last_refit_count = observed_count
                q_use = float(q) if q is not None else warmup_q
                r_use = float(r) if r is not None else warmup_r
                predicted_variance = variance + q_use
            innovation_variance = predicted_variance + r_use
            innovation = value - predicted_state
            gain = predicted_variance / innovation_variance
            state = predicted_state + gain * innovation
            variance = max((1.0 - gain) * predicted_variance, 1e-12)
            innovations[i] = innovation / sqrt(innovation_variance)
        else:
            state = predicted_state
            variance = min(predicted_variance, 1e6)  # cap gap inflation
        anchor[i] = state
        variances[i] = variance

    anchor_s = pd.Series(anchor, index=series.index, name="kalman_anchor")
    return KalmanAnchorResult(
        anchor=anchor_s,
        innovation_z=pd.Series(innovations, index=series.index, name="kalman_innovation_z"),
        anchor_velocity=anchor_s.diff().rename("kalman_anchor_velocity"),
        state_variance=pd.Series(variances, index=series.index, name="kalman_state_variance"),
    )

def positive_cusum(
    score: pd.Series,
    reference: float = 0.25,
    threshold: float = 5.0,
    reset_on_alarm: bool = False,
) -> pd.DataFrame:
    """One-sided CUSUM with a continuous alarm intensity."""
    values = pd.to_numeric(score, errors="coerce").to_numpy(dtype=float)
    statistic = np.zeros(len(values), dtype=float)
    alarms = np.zeros(len(values), dtype=bool)
    running = 0.0
    for i, value in enumerate(values):
        if not np.isfinite(value):
            statistic[i] = running
            continue
        running = max(0.0, running + value - reference)
        alarms[i] = running >= threshold
        statistic[i] = running
        if alarms[i] and reset_on_alarm:
            running = 0.0
    return pd.DataFrame(
        {
            "cusum": statistic,
            "alarm": alarms,
            "stress_probability": np.clip(statistic / threshold, 0.0, 1.0),
        },
        index=score.index,
    )


def ciss_index(
    pit_channels: pd.DataFrame,
    weights: dict[str, float] | None = None,
    span: int = 60,
    min_periods: int = 20,
) -> pd.DataFrame:
    """Correlation-weighted CISS-style aggregation with missing-aware weights.

    Returns the quadratic CISS form and its square-root intensity.  Missing
    channels are removed and weights are renormalized rather than set to zero.
    """
    values = pit_channels.apply(pd.to_numeric, errors="coerce").clip(0.0, 1.0)
    columns = list(values.columns)
    if not columns:
        return pd.DataFrame(index=values.index, columns=["ciss", "ciss_sqrt", "coverage"])
    base_weights = np.array([weights.get(c, 1.0) if weights else 1.0 for c in columns], dtype=float)
    base_weights /= base_weights.sum()
    correlations: dict[tuple[int, int], pd.Series] = {}
    for i in range(len(columns)):
        for j in range(i + 1, len(columns)):
            correlations[i, j] = values[columns[i]].ewm(
                span=span, min_periods=min_periods, adjust=False
            ).corr(values[columns[j]])

    raw = np.full(len(values), np.nan)
    root = np.full(len(values), np.nan)
    coverage = values.notna().mean(axis=1).to_numpy(dtype=float)
    matrix = np.eye(len(columns))
    arr = values.to_numpy(dtype=float)
    for t in range(len(values)):
        available = np.isfinite(arr[t])
        if not available.any():
            continue
        for (i, j), corr in correlations.items():
            value = corr.iloc[t]
            matrix[i, j] = matrix[j, i] = float(np.clip(value, -1.0, 1.0)) if np.isfinite(value) else 0.0
        sub = matrix[np.ix_(available, available)]
        w = base_weights[available]
        w /= w.sum()
        vector = w * arr[t, available]
        quadratic = max(0.0, float(vector @ sub @ vector))
        raw[t] = quadratic
        root[t] = sqrt(quadratic)
    return pd.DataFrame({"ciss": raw, "ciss_sqrt": root, "coverage": coverage}, index=values.index)


def rolling_absorption_ratio(
    frame: pd.DataFrame,
    window: int = TRADING_DAYS,
    min_periods: int = 126,
    variance_fraction: float = 0.2,
    step: int = 5,
) -> pd.Series:
    """Share of covariance variance absorbed by the leading eigenvalues."""
    numeric = frame.apply(pd.to_numeric, errors="coerce")
    result = pd.Series(np.nan, index=numeric.index, name="absorption_ratio")
    for end in range(min_periods, len(numeric) + 1, max(1, step)):
        sample = numeric.iloc[max(0, end - window):end].dropna(axis=1, thresh=min_periods)
        sample = sample.dropna()
        if sample.shape[0] < min_periods or sample.shape[1] < 2:
            continue
        covariance = np.cov(sample.to_numpy(dtype=float), rowvar=False)
        eigenvalues = np.linalg.eigvalsh(covariance)
        total = float(eigenvalues.sum())
        if total <= 0:
            continue
        n_leading = max(1, int(np.ceil(sample.shape[1] * variance_fraction)))
        result.iloc[end - 1] = float(np.sort(eigenvalues)[-n_leading:].sum() / total)
    return result.ffill(limit=max(1, step - 1))


def har_realized_variance_forecast(
    returns: pd.Series,
    fit_window: int = 504,
    min_periods: int = 252,
) -> pd.Series:
    """Causal HAR-RV one-day forecast from daily, weekly, monthly RV."""
    ret = pd.to_numeric(returns, errors="coerce")
    rv = ret.pow(2) * TRADING_DAYS
    design = pd.DataFrame({"d": rv, "w": rv.rolling(5).mean(), "m": rv.rolling(22).mean()})
    target = rv.shift(-1)
    forecast = pd.Series(np.nan, index=ret.index, name="har_rv_forecast")
    for i in range(min_periods, len(ret)):
        start = max(0, i - fit_window)
        train = design.iloc[start:i].copy()
        train["target"] = target.iloc[start:i]
        train = train.dropna()
        current = design.iloc[i]
        if len(train) < min_periods or current.isna().any():
            continue
        x = np.column_stack([np.ones(len(train)), train[["d", "w", "m"]].to_numpy()])
        beta, *_ = np.linalg.lstsq(x, train["target"].to_numpy(), rcond=None)
        forecast.iloc[i] = max(0.0, float(np.r_[1.0, current.to_numpy()] @ beta))
    return forecast


def k_surface_features(panel: pd.DataFrame) -> pd.DataFrame:
    """Build causal K candidates from the free CBOE/SPX surface inputs."""
    out = pd.DataFrame(index=panel.index)
    vix = _first(panel, ("FRED:VIXCLS", "CBOE:VIXCLS", "VIX"))
    vix9d = _first(panel, ("CBOE:VIX9D",))
    vix3m = _first(panel, ("CBOE:VIX3M",))
    vix6m = _first(panel, ("CBOE:VIX6M",))
    skew = _first(panel, ("CBOE:SKEW", "SKEW"))
    vvix = _first(panel, ("CBOE:VVIX", "VVIX"))
    move = _first(panel, ("CBOE:MOVE", "MOVE", "CBOE:VXTLT"))
    spx = _first(panel, ("CBOE:SPX", "SPX", "SPY"))
    if vix is not None and vix3m is not None:
        out["vix_vix3m_ratio"] = vix / vix3m.replace(0.0, np.nan)
    if vix9d is not None and vix3m is not None and vix6m is not None:
        out["term_structure_curvature"] = vix9d - 2.0 * vix3m + vix6m
    if skew is not None:
        out["skew"] = skew
    if vvix is not None:
        out["vvix"] = vvix
    if move is not None:
        out["move"] = move
    if spx is not None:
        trading_spx = spx.dropna()
        returns = np.log(trading_spx).diff()
        rv = returns.pow(2) * TRADING_DAYS
        bipower = (np.pi / 2.0) * returns.abs() * returns.shift(1).abs() * TRADING_DAYS
        out["jump_variation"] = (rv - bipower).clip(lower=0.0).reindex(out.index)
        if vix is not None:
            har = har_realized_variance_forecast(returns).reindex(out.index)
            out["har_rv_forecast"] = har
            out["variance_risk_premium"] = (vix / 100.0).pow(2) - har
    return out


def bocpd_change_probability(
    score: pd.Series,
    hazard: float = 1.0 / 50.0,
    observation_variance: float = 1.0,
    max_run: int = 200,
    recent_run_days: int = 5,
) -> pd.Series:
    """Online Bayesian change-point recent-run probability (Adams & MacKay).

    Returns the posterior mass on run lengths ``<= recent_run_days`` after
    observing *t*.  Constant-hazard ``P(r=0)`` alone is nearly flat; the short
    run mass rises after a genuine level shift and then decays.
    """
    values = pd.to_numeric(score, errors="coerce").to_numpy(dtype=float)
    hazard = float(np.clip(hazard, 1e-6, 1.0 - 1e-6))
    r = max(float(observation_variance), 1e-8)
    recent = max(0, int(recent_run_days))
    run_probs = np.array([1.0], dtype=float)
    run_means = np.array([0.0], dtype=float)
    run_counts = np.array([0.0], dtype=float)
    out = np.full(len(values), np.nan)
    for i, value in enumerate(values):
        if not np.isfinite(value):
            continue
        predictive = np.exp(-0.5 * ((value - run_means) ** 2) / r) / sqrt(2.0 * np.pi * r)
        growth = run_probs * predictive * (1.0 - hazard)
        cp = float((run_probs * predictive * hazard).sum())
        run_probs = np.r_[cp, growth]
        run_means = np.r_[value, (run_means * run_counts + value) / (run_counts + 1.0)]
        run_counts = np.r_[1.0, run_counts + 1.0]
        if len(run_probs) > max_run + 1:
            run_probs = run_probs[: max_run + 1]
            run_means = run_means[: max_run + 1]
            run_counts = run_counts[: max_run + 1]
        total = run_probs.sum()
        if total <= 0:
            run_probs = np.array([1.0])
            run_means = np.array([value])
            run_counts = np.array([1.0])
            out[i] = 1.0
            continue
        run_probs /= total
        out[i] = float(run_probs[: recent + 1].sum())
    return pd.Series(out, index=score.index, name="bocpd_change_probability")


def build_forward_stress_events(
    price: pd.Series,
    horizon: int = 20,
    vol_quantile: float = 0.90,
    drawdown_threshold: float = -0.05,
    threshold_window: int = 2520,
    min_history: int = 252,
    logic: str = "or",
) -> pd.DataFrame:
    """Causal event labels from future realized vol and/or future drawdown.

    ``logic``:
      - ``or``: either condition (legacy; higher event rate)
      - ``and``: both conditions (stricter stress)
      - ``vol`` / ``drawdown``: single definition
    """
    px = pd.to_numeric(price, errors="coerce")
    returns = px.pct_change(fill_method=None)
    future_rv = returns.shift(-1).pow(2).rolling(horizon, min_periods=horizon).sum().shift(-(horizon - 1))
    future_rv = np.sqrt(future_rv * TRADING_DAYS / horizon)
    future_min = px.shift(-1).rolling(horizon, min_periods=horizon).min().shift(-(horizon - 1))
    future_drawdown = future_min / px - 1.0
    matured = future_rv.shift(horizon)
    threshold = matured.rolling(threshold_window, min_periods=min_history).quantile(vol_quantile)
    vol_event = future_rv > threshold
    drawdown_event = future_drawdown < drawdown_threshold
    valid = future_rv.notna() & threshold.notna() & future_drawdown.notna()
    logic_key = logic.strip().lower()
    if logic_key == "and":
        event = (vol_event & drawdown_event).where(valid)
    elif logic_key == "vol":
        event = vol_event.where(valid)
    elif logic_key == "drawdown":
        event = drawdown_event.where(valid)
    else:
        event = (vol_event | drawdown_event).where(valid)
    return pd.DataFrame(
        {
            "future_realized_vol": future_rv,
            "future_max_drawdown": future_drawdown,
            "causal_vol_threshold": threshold,
            "vol_event": vol_event.where(valid),
            "drawdown_event": drawdown_event.where(valid),
            "stress_event": event,
        },
        index=px.index,
    )


def probability_metrics(target: pd.Series, probability: pd.Series) -> dict[str, float | int]:
    """ROC-AUC, PR-AUC, Brier and calibration error for a rare event."""
    from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

    aligned = pd.concat([target.rename("y"), probability.rename("p")], axis=1).dropna()
    if aligned.empty or aligned["y"].nunique() < 2:
        return {"n": int(len(aligned)), "event_rate": float(aligned["y"].mean()) if len(aligned) else np.nan,
                "roc_auc": np.nan, "pr_auc": np.nan, "brier": np.nan, "ece": np.nan}
    y = aligned["y"].astype(int).to_numpy()
    p = aligned["p"].clip(0.0, 1.0).to_numpy(dtype=float)
    ece = 0.0
    for lo, hi in zip(np.linspace(0, 1, 11)[:-1], np.linspace(0, 1, 11)[1:]):
        mask = (p >= lo) & (p < hi if hi < 1 else p <= hi)
        if mask.any():
            ece += mask.mean() * abs(float(y[mask].mean()) - float(p[mask].mean()))
    return {
        "n": int(len(y)),
        "event_rate": float(y.mean()),
        "roc_auc": float(roc_auc_score(y, p)),
        "pr_auc": float(average_precision_score(y, p)),
        "brier": float(brier_score_loss(y, p)),
        "ece": float(ece),
    }


def lead_profile(target: pd.Series, probability: pd.Series, offsets: tuple[int, ...] = (20, 10, 5, 0)) -> dict[str, float]:
    """Mean signal probability at fixed lead offsets before event onsets."""
    y = target.eq(True)
    onsets = y & ~y.shift(1, fill_value=False)
    positions = np.flatnonzero(onsets.to_numpy())
    values = pd.to_numeric(probability, errors="coerce").to_numpy(dtype=float)
    result: dict[str, float] = {}
    for offset in offsets:
        samples = [values[pos - offset] for pos in positions if pos >= offset and np.isfinite(values[pos - offset])]
        result[f"t_minus_{offset}"] = float(np.mean(samples)) if samples else np.nan
    result["event_onsets"] = int(len(positions))
    return result


def stationary_bootstrap_metric(
    target: pd.Series,
    probability: pd.Series,
    metric: str = "roc_auc",
    reps: int = 200,
    mean_block: int = 20,
    seed: int = 1729,
) -> dict[str, float | int]:
    """Stationary-bootstrap confidence interval preserving serial dependence."""
    aligned = pd.concat([target.rename("y"), probability.rename("p")], axis=1).dropna()
    n = len(aligned)
    if n < 50:
        return {"reps": 0, "low": np.nan, "median": np.nan, "high": np.nan}
    rng = np.random.default_rng(seed)
    values: list[float] = []
    restart_probability = 1.0 / mean_block
    y, p = aligned["y"].reset_index(drop=True), aligned["p"].reset_index(drop=True)
    for _ in range(reps):
        indices = np.empty(n, dtype=int)
        indices[0] = rng.integers(0, n)
        for i in range(1, n):
            indices[i] = rng.integers(0, n) if rng.random() < restart_probability else (indices[i - 1] + 1) % n
        score = probability_metrics(y.iloc[indices].reset_index(drop=True), p.iloc[indices].reset_index(drop=True)).get(metric)
        if isinstance(score, (int, float)) and np.isfinite(score):
            values.append(float(score))
    if not values:
        return {"reps": 0, "low": np.nan, "median": np.nan, "high": np.nan}
    low, median, high = np.quantile(values, [0.025, 0.5, 0.975])
    return {"reps": len(values), "low": float(low), "median": float(median), "high": float(high)}


def deflated_sharpe_ratio(
    observed_sharpe: float,
    n_observations: int,
    n_trials: int,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
    periods_per_year: int = TRADING_DAYS,
) -> dict[str, float | int]:
    """Probability that Sharpe exceeds the multiple-testing expected maximum."""
    n_trials = max(1, int(n_trials))
    n_observations = max(2, int(n_observations))
    normal = NormalDist()
    gamma = 0.5772156649015329
    if n_trials == 1:
        expected_max_z = 0.0
    else:
        z1 = normal.inv_cdf(1.0 - 1.0 / n_trials)
        z2 = normal.inv_cdf(1.0 - 1.0 / (n_trials * exp(1.0)))
        expected_max_z = (1.0 - gamma) * z1 + gamma * z2
    daily_sharpe = observed_sharpe / sqrt(periods_per_year)
    daily_variance = (
        1.0 - skewness * daily_sharpe
        + ((kurtosis - 1.0) / 4.0) * daily_sharpe**2
    ) / (n_observations - 1)
    standard_error = sqrt(max(periods_per_year * daily_variance, 1e-12))
    expected_max = expected_max_z * sqrt(periods_per_year / (n_observations - 1))
    test_stat = (observed_sharpe - expected_max) / standard_error
    return {
        "observed_sharpe": float(observed_sharpe),
        "expected_max_sharpe": float(expected_max),
        "deflated_sharpe_probability": float(normal.cdf(test_stat)),
        "n_observations": n_observations,
        "n_trials": n_trials,
    }


def _dm_value(value: float) -> float | None:
    """Coerce a Diebold-Mariano scalar to a JSON-safe float (NaN -> None)."""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None


def incremental_logistic_test(
    target: pd.Series,
    baseline: pd.DataFrame,
    candidate: pd.Series,
    train_fraction: float = 0.7,
    embargo: int = 20,
) -> dict[str, object]:
    """Chronological baseline-vs-baseline+candidate incremental event test."""
    from sklearn.linear_model import LogisticRegression

    data = pd.concat([target.rename("y"), baseline, candidate.rename("candidate")], axis=1).dropna()
    split = int(len(data) * train_fraction)
    train = data.iloc[:max(0, split - embargo)]
    test = data.iloc[min(len(data), split + embargo):]
    if len(train) < 100 or len(test) < 50 or train["y"].nunique() < 2 or test["y"].nunique() < 2:
        return {"status": "insufficient_sample", "n_train": len(train), "n_test": len(test)}
    base_cols = list(baseline.columns)
    results: dict[str, object] = {"status": "ok", "n_train": len(train), "n_test": len(test), "embargo": embargo}
    oos_probability: dict[str, pd.Series] = {}
    for label, columns in (("baseline", base_cols), ("augmented", base_cols + ["candidate"])):
        x_train = train[columns].to_numpy(dtype=float)
        x_test = test[columns].to_numpy(dtype=float)
        mean = x_train.mean(axis=0)
        scale = x_train.std(axis=0)
        scale[scale < 1e-8] = 1.0
        # Some sklearn/numpy combinations emit spurious BLAS overflow warnings
        # for finite, standardized liblinear inputs.  The fitted values remain
        # finite; keep the runner output clean while retaining explicit checks.
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=RuntimeWarning, module=r"sklearn\..*")
            model = LogisticRegression(max_iter=2000, solver="liblinear").fit(
                (x_train - mean) / scale, train["y"].astype(int)
            )
            probability = model.predict_proba((x_test - mean) / scale)[:, 1]
        if not np.isfinite(probability).all():
            raise ValueError(f"Non-finite logistic probabilities for {label}")
        oos_probability[label] = pd.Series(probability, index=test.index, name=label)
        results[label] = {
            **probability_metrics(test["y"], oos_probability[label]),
            "coefficients": {column: float(value) for column, value in zip(columns, model.coef_[0])},
        }
    base_result = results["baseline"]
    aug_result = results["augmented"]
    assert isinstance(base_result, dict) and isinstance(aug_result, dict)
    # Diebold-Mariano on OOS log-loss. Convention: pa=augmented, pb=baseline;
    # negative mean_diff -> augmented is more accurate. This is the §7.5
    # incremental significance gate (pass_criteria: DM p < 0.05).
    dm = diebold_mariano_logloss(
        test["y"],
        oos_probability["augmented"],
        oos_probability["baseline"],
    )
    results["delta"] = {
        "roc_auc": float(aug_result["roc_auc"] - base_result["roc_auc"]),
        "pr_auc": float(aug_result["pr_auc"] - base_result["pr_auc"]),
        "brier_improvement": float(base_result["brier"] - aug_result["brier"]),
        # mean_diff<0 -> augmented better; p_value is two-sided DM significance.
        "diebold_mariano": {
            "n": int(dm["n"]),
            "mean_diff": _dm_value(dm["mean_diff"]),
            "dm_stat": _dm_value(dm["dm_stat"]),
            "p_value": _dm_value(dm["p_value"]),
        },
    }
    return results


def chronological_isotonic_calibration(
    target: pd.Series,
    raw_probability: pd.Series,
    train_fraction: float = 0.6,
    embargo: int = 20,
) -> pd.Series:
    """Fit isotonic calibration on an early window and emit held-out values."""
    from sklearn.isotonic import IsotonicRegression

    aligned = pd.concat([target.rename("y"), raw_probability.rename("p")], axis=1).dropna()
    output = pd.Series(np.nan, index=raw_probability.index, name="isotonic_probability")
    split = int(len(aligned) * train_fraction)
    train = aligned.iloc[:max(0, split - embargo)]
    test = aligned.iloc[min(len(aligned), split + embargo):]
    if len(train) < 100 or test.empty or train["y"].nunique() < 2:
        return output
    calibrator = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
    calibrator.fit(train["p"].to_numpy(dtype=float), train["y"].astype(int).to_numpy())
    output.loc[test.index] = calibrator.predict(test["p"].to_numpy(dtype=float))
    return output


def sticky_regime_probability(score: pd.Series, persistence: float = 0.97) -> pd.Series:
    """Backward-compatible alias for the fixed-mean sticky filter."""
    return sticky_filter_probability(score, persistence=persistence)


def sticky_filter_probability(score: pd.Series, persistence: float = 0.97) -> pd.Series:
    """Fixed-emission sticky three-state filter (fast baseline comparator)."""
    z = causal_robust_zscore(score, window=756, min_periods=252, clip=None)
    means = np.array([-0.75, 0.25, 1.75])
    sigma = np.array([0.8, 0.8, 1.0])
    transition = np.full((3, 3), (1.0 - persistence) / 2.0)
    np.fill_diagonal(transition, persistence)
    posterior = np.ones(3) / 3.0
    output = np.full(len(z), np.nan)
    for i, value in enumerate(z.to_numpy(dtype=float)):
        if not np.isfinite(value):
            continue
        prior = posterior @ transition
        likelihood = np.exp(-0.5 * ((value - means) / sigma) ** 2) / sigma
        posterior = prior * likelihood
        total = posterior.sum()
        if total <= 0:
            posterior = np.ones(3) / 3.0
        else:
            posterior /= total
        output[i] = posterior[2] + 0.5 * posterior[1]
    return pd.Series(output, index=score.index, name="sticky_filter_probability")


def _sticky_transmat(n_states: int, stickiness: float) -> np.ndarray:
    """Dirichlet-style sticky prior mean: diagonal boosted by *stickiness*."""
    alpha = np.ones((n_states, n_states), dtype=float)
    np.fill_diagonal(alpha, 1.0 + max(stickiness, 0.0))
    return alpha / alpha.sum(axis=1, keepdims=True)


def _forward_state_proba(
    values: np.ndarray,
    means: np.ndarray,
    covars: np.ndarray,
    transmat: np.ndarray,
    startprob: np.ndarray,
) -> np.ndarray:
    """Causal forward algorithm; returns posterior at the final observation."""
    log_trans = np.log(np.clip(transmat, 1e-12, 1.0))
    log_start = np.log(np.clip(startprob, 1e-12, 1.0))
    log_alpha = log_start.copy()
    for value in values:
        if not np.isfinite(value):
            continue
        log_emit = -0.5 * (
            np.log(2.0 * np.pi * covars) + (value - means) ** 2 / covars
        )
        log_alpha = log_emit + np.logaddexp.reduce(log_alpha[:, None] + log_trans, axis=0)
    log_alpha -= np.logaddexp.reduce(log_alpha)
    return np.exp(log_alpha)


def sticky_gaussian_hmm_probability(
    score: pd.Series,
    n_states: int = 3,
    stickiness: float = 25.0,
    *,
    refit_every: int = 63,
    min_fit: int = 252,
    max_fit_window: int = 1008,
) -> pd.Series:
    """Causal sticky Gaussian HMM stress probability via hmmlearn + forward filter.

    Transition matrix is initialized from a sticky Dirichlet prior mean and
    re-estimated only on past data. Forward posteriors never use future obs.
    Returns P(highest-mean state) + 0.5 * P(middle state) as stress score.
    """
    from hmmlearn.hmm import GaussianHMM

    z = causal_robust_zscore(score, window=756, min_periods=min_fit, clip=None)
    values = z.to_numpy(dtype=float)
    output = np.full(len(values), np.nan)
    model: GaussianHMM | None = None
    last_refit = -10**9
    observed = 0
    stress_order: np.ndarray | None = None
    log_alpha: np.ndarray | None = None

    for i, value in enumerate(values):
        if not np.isfinite(value):
            continue
        observed += 1
        if observed >= min_fit and (model is None or observed - last_refit >= refit_every):
            start = max(0, i + 1 - max_fit_window)
            train = values[start:i]
            train = train[np.isfinite(train)].reshape(-1, 1)
            if len(train) < min_fit:
                continue
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                candidate = GaussianHMM(
                    n_components=n_states,
                    covariance_type="diag",
                    n_iter=50,
                    tol=1e-3,
                    init_params="mc",
                    params="stmc",
                    random_state=1729,
                )
                candidate.transmat_ = _sticky_transmat(n_states, stickiness)
                candidate.startprob_ = np.full(n_states, 1.0 / n_states)
                try:
                    candidate.fit(train)
                except Exception:
                    continue
            prior = _sticky_transmat(n_states, stickiness)
            candidate.transmat_ = 0.7 * candidate.transmat_ + 0.3 * prior
            candidate.transmat_ /= candidate.transmat_.sum(axis=1, keepdims=True)
            model = candidate
            stress_order = np.argsort(model.means_.reshape(-1))
            log_alpha = np.log(np.clip(model.startprob_, 1e-12, 1.0))
            last_refit = observed
        if model is None or stress_order is None or log_alpha is None:
            continue
        means = model.means_.reshape(-1)
        covars = np.clip(model.covars_.reshape(-1), 1e-8, None)
        log_trans = np.log(np.clip(model.transmat_, 1e-12, 1.0))
        log_emit = -0.5 * (np.log(2.0 * np.pi * covars) + (value - means) ** 2 / covars)
        log_alpha = log_emit + np.logaddexp.reduce(log_alpha[:, None] + log_trans, axis=0)
        log_alpha = log_alpha - np.logaddexp.reduce(log_alpha)
        post = np.exp(log_alpha)
        high = int(stress_order[-1])
        mid = int(stress_order[-2]) if n_states >= 2 else high
        output[i] = float(post[high] + 0.5 * post[mid])
    return pd.Series(output, index=score.index, name="sticky_gaussian_hmm_probability")


def jump_cluster_regime_probability(
    score: pd.Series,
    *,
    jump_penalty: float = 8.0,
    min_fit: int = 126,
    refit_every: int = 21,
    max_fit_window: int = 756,
) -> pd.Series:
    """Two-regime statistical jump model (Nystrup-style) with jump penalty.

    Expanding/trailing fit minimizes within-regime SSE + ``jump_penalty`` × jumps
    via dynamic programming on past data only; the current point's soft stress
    assignment is the distance to the calm vs stress regime means.
    """
    z = causal_robust_zscore(score, window=756, min_periods=min_fit, clip=None)
    values = z.to_numpy(dtype=float)
    output = np.full(len(values), np.nan)
    means = (0.0, 1.0)
    last_refit = -10**9
    observed = 0

    def _fit_jump_means(sample: np.ndarray) -> tuple[float, float]:
        n = len(sample)
        if n < 10:
            return float(np.nanmean(sample)), float(np.nanmean(sample) + 1.0)
        # DP path cost for 2 means estimated as running averages after each jump.
        # Practical approximation: threshold split at median of upper/lower thirds.
        lo = float(np.nanpercentile(sample, 35))
        hi = float(np.nanpercentile(sample, 75))
        if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
            mu = float(np.nanmean(sample))
            return mu, mu + 1.0
        # Refine with one pass of jump-penalized assignment.
        calm, stress = lo, hi
        state = 0
        for _ in range(3):
            c_vals: list[float] = []
            s_vals: list[float] = []
            state = 0
            for value in sample:
                cost_stay = (value - (calm if state == 0 else stress)) ** 2
                alt = 1 - state
                alt_mean = calm if alt == 0 else stress
                cost_jump = (value - alt_mean) ** 2 + jump_penalty
                if cost_jump < cost_stay:
                    state = alt
                (c_vals if state == 0 else s_vals).append(value)
            if c_vals:
                calm = float(np.mean(c_vals))
            if s_vals:
                stress = float(np.mean(s_vals))
            if stress < calm:
                calm, stress = stress, calm
        return calm, stress

    for i, value in enumerate(values):
        if not np.isfinite(value):
            continue
        observed += 1
        if observed >= min_fit and observed - last_refit >= refit_every:
            start = max(0, i + 1 - max_fit_window)
            sample = values[start:i]
            sample = sample[np.isfinite(sample)]
            if len(sample) >= min_fit:
                means = _fit_jump_means(sample)
                last_refit = observed
        calm, stress = means
        # Soft assignment to stress regime (logistic on distance differential).
        d0 = (value - calm) ** 2
        d1 = (value - stress) ** 2
        output[i] = float(1.0 / (1.0 + exp(0.5 * (d1 - d0))))
    return pd.Series(output, index=score.index, name="jump_cluster_regime_probability")


def rolling_first_factor(
    frame: pd.DataFrame,
    window: int = TRADING_DAYS,
    min_periods: int = 126,
    step: int = 5,
) -> pd.Series:
    """Causal rolling PCA first factor; sign anchored so stress (high mean) is positive."""
    numeric = frame.apply(pd.to_numeric, errors="coerce")
    result = pd.Series(np.nan, index=numeric.index, name="rolling_first_factor")
    for end in range(min_periods, len(numeric) + 1, max(1, step)):
        sample = numeric.iloc[max(0, end - window):end].dropna(axis=0, how="any")
        if sample.shape[0] < min_periods or sample.shape[1] < 2:
            continue
        centered = sample.to_numpy(dtype=float)
        centered = centered - centered.mean(axis=0)
        try:
            _, _, vt = np.linalg.svd(centered, full_matrices=False)
        except np.linalg.LinAlgError:
            continue
        loading = vt[0]
        latest = numeric.iloc[end - 1].to_numpy(dtype=float)
        if not np.isfinite(latest).all():
            continue
        score = float((latest - sample.mean().to_numpy()) @ loading)
        # Anchor: factor should move with cross-sectional mean stress.
        mean_stress = float(np.nanmean(latest))
        if np.isfinite(mean_stress) and score * mean_stress < 0:
            score = -score
        result.iloc[end - 1] = score
    return result.ffill(limit=max(1, step - 1))


def dynamic_factor_score(
    frame: pd.DataFrame,
    *,
    k_factors: int = 1,
    min_periods: int = 126,
) -> pd.Series:
    """Single dynamic factor via statsmodels DynamicFactorMQ when feasible.

    Falls back to ``rolling_first_factor`` when the sample is too short or the
    optimizer fails. Fit uses the full available history up to each month-end
    block for tractability; within a block the filtered factor is one-sided.
    """
    from statsmodels.tsa.statespace.dynamic_factor_mq import DynamicFactorMQ

    numeric = frame.apply(pd.to_numeric, errors="coerce").dropna(how="all")
    if numeric.shape[1] < 2 or numeric.dropna().shape[0] < min_periods:
        return rolling_first_factor(frame, min_periods=min_periods)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = DynamicFactorMQ(numeric, factors=k_factors, factor_orders=1, standardize=True)
            result = model.fit(disp=False, maxiter=100)
        factor = result.factors.filtered.iloc[:, 0]
        # Sign anchor to cross-sectional mean.
        aligned = pd.concat([factor.rename("f"), numeric.mean(axis=1).rename("m")], axis=1).dropna()
        if len(aligned) >= 20 and float(aligned["f"].corr(aligned["m"])) < 0:
            factor = -factor
        return factor.reindex(frame.index).rename("dynamic_factor")
    except Exception:
        return rolling_first_factor(frame, min_periods=min_periods)

def continuous_position(
    stress_probability: pd.Series,
    returns: pd.Series,
    quality_cap: pd.Series | float = 1.0,
    target_volatility: float = 0.10,
    ewma_span: int = 20,
) -> pd.DataFrame:
    """Volatility target times (1 - stress probability), capped by quality."""
    ret = pd.to_numeric(returns, errors="coerce")
    volatility = ret.ewm(span=ewma_span, adjust=False, min_periods=ewma_span).std() * sqrt(TRADING_DAYS)
    vol_multiplier = (target_volatility / volatility.where(volatility > 0.0)).clip(upper=1.0)
    vol_multiplier = vol_multiplier.where(volatility.notna(), np.nan).fillna(
        volatility.notna().astype(float)
    )
    quality = pd.Series(float(quality_cap), index=ret.index) if np.isscalar(quality_cap) else quality_cap.reindex(ret.index)
    position = quality.clip(0.0, 1.0) * vol_multiplier * (1.0 - stress_probability.reindex(ret.index).clip(0.0, 1.0))
    return pd.DataFrame(
        {"estimated_volatility": volatility, "volatility_multiplier": vol_multiplier,
         "stress_probability": stress_probability.reindex(ret.index), "quality_cap": quality,
         "position": position.clip(0.0, 1.0)},
        index=ret.index,
    )


def _first(frame: pd.DataFrame, names: tuple[str, ...]) -> pd.Series | None:
    for name in names:
        if name in frame.columns:
            return pd.to_numeric(frame[name], errors="coerce")
    return None
