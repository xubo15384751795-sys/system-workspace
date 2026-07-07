"""Incremental-information tests for the structural Sigma signal.

Implements P3 of the empirical roadmap. Each test answers a sharp question:

  Test A - Information regression
    Y_{t+h} = a + b1*NFCI_t + b2*KCFSI_t + b3*STLFSI_t + g*Sigma_t + e
    Does Sigma have a coefficient that is significant *after* controlling for
    other public stress indices? Reports HAC-Newey-West standard errors and
    incremental R-squared.

  Test B - Out-of-sample forecast comparison
    Train on a fixed early window, evaluate on a held-out late window.
    Compare three models: signal-only, controls-only, signal+controls.
    Report OOS R^2, RMSE, and (for binary targets) Brier and AUC.

  Test C - Regime classification lead/lag
    Cross-correlate Sigma against a known stress regime (e.g. NBER recession,
    VIX>30, NFCI>0). Report the lag with peak correlation and the lead-time
    distribution.

  Test D - Mechanism specificity
    For a labelled case window, identify which of M / D / K / X is the
    leading channel and compare against the case's expected mechanism.

Pure functions on numeric pandas inputs - no I/O, no fitting frameworks
heavier than numpy + scikit-learn.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping

import numpy as np
import pandas as pd

try:
    from sklearn.linear_model import LinearRegression, LogisticRegression
    from sklearn.metrics import roc_auc_score
    _SKLEARN_OK = True
except Exception:
    _SKLEARN_OK = False


# --------------------------------------------------------------------------
# Test A - information regression with HAC standard errors
# --------------------------------------------------------------------------

def _build_design(target: pd.Series, regressors: Mapping[str, pd.Series]) -> tuple[np.ndarray, np.ndarray, list[str], pd.DatetimeIndex]:
    frame = pd.concat({name: pd.to_numeric(s, errors="coerce") for name, s in regressors.items()}, axis=1)
    frame["__target__"] = pd.to_numeric(target, errors="coerce")
    frame = frame.dropna()
    y = frame["__target__"].to_numpy(dtype=float)
    names = [c for c in frame.columns if c != "__target__"]
    X = frame[names].to_numpy(dtype=float)
    X = np.column_stack([np.ones(len(X)), X])
    names = ["__intercept__"] + names
    return X, y, names, frame.index


def _hac_newey_west(X: np.ndarray, residuals: np.ndarray, lags: int) -> np.ndarray:
    """Newey-West heteroskedasticity-and-autocorrelation-consistent covariance."""
    n, k = X.shape
    if n <= k:
        return np.full((k, k), np.nan)
    XtX_inv = np.linalg.pinv(X.T @ X)
    u = residuals.reshape(-1, 1)
    Xu = X * u
    S = Xu.T @ Xu
    for lag in range(1, lags + 1):
        weight = 1.0 - lag / (lags + 1)
        gamma = Xu[lag:].T @ Xu[:-lag]
        S = S + weight * (gamma + gamma.T)
    return n * XtX_inv @ S @ XtX_inv / max(n - k, 1)


@dataclass(frozen=True)
class RegressionTermStat:
    name: str
    coefficient: float
    hac_std_error: float
    t_stat: float
    p_value: float


@dataclass(frozen=True)
class InformationRegressionResult:
    target_name: str
    horizon: int
    n_obs: int
    r_squared: float
    r_squared_controls_only: float
    incremental_r_squared: float
    terms: tuple[RegressionTermStat, ...]
    notes: str = ""

    def signal_term(self, signal_name: str) -> RegressionTermStat | None:
        for term in self.terms:
            if term.name == signal_name:
                return term
        return None


def _t_two_sided_p(t: float, df: int) -> float:
    if df <= 0 or not np.isfinite(t):
        return float("nan")
    try:
        from scipy.stats import t as student_t

        return float(2.0 * (1.0 - student_t.cdf(abs(t), df)))
    except Exception:
        return float(2.0 * (1.0 - _normal_cdf(abs(t))))


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _ols_with_hac(X: np.ndarray, y: np.ndarray, names: list[str], hac_lags: int) -> tuple[np.ndarray, list[RegressionTermStat], float]:
    beta, _residuals_unused, rank, _ = np.linalg.lstsq(X, y, rcond=None)
    residuals = y - X @ beta
    cov = _hac_newey_west(X, residuals, lags=hac_lags)
    se = np.sqrt(np.clip(np.diag(cov), 0.0, None))
    df = max(len(y) - rank, 1)
    terms: list[RegressionTermStat] = []
    for i, name in enumerate(names):
        b = float(beta[i])
        s = float(se[i]) if np.isfinite(se[i]) else float("nan")
        t = b / s if s and np.isfinite(s) and s > 0 else float("nan")
        p = _t_two_sided_p(t, df)
        terms.append(RegressionTermStat(name=name, coefficient=b, hac_std_error=s, t_stat=t, p_value=p))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    ss_res = float(np.sum(residuals ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return beta, terms, r2


def information_regression(
    target: pd.Series,
    signal: pd.Series,
    controls: Mapping[str, pd.Series],
    horizon: int = 30,
    hac_lags: int | None = None,
    signal_name: str | None = None,
) -> InformationRegressionResult:
    target_name = target.name or "target"
    sig_name = signal_name or signal.name or "signal"
    fwd_target = pd.to_numeric(target, errors="coerce").shift(-horizon).rolling(horizon, min_periods=1).max()

    full_regressors: dict[str, pd.Series] = {**{name: s for name, s in controls.items()}, sig_name: signal}
    X_full, y, names_full, idx = _build_design(fwd_target, full_regressors)
    if len(y) < max(20, len(names_full) * 2):
        return InformationRegressionResult(
            target_name=str(target_name),
            horizon=horizon,
            n_obs=len(y),
            r_squared=0.0,
            r_squared_controls_only=0.0,
            incremental_r_squared=0.0,
            terms=tuple(),
            notes="Insufficient observations after alignment",
        )

    if hac_lags is None:
        hac_lags = max(1, int(np.floor(4 * (len(y) / 100) ** (2 / 9))))

    _, terms_full, r2_full = _ols_with_hac(X_full, y, names_full, hac_lags=hac_lags)

    X_ctrl, _, names_ctrl, _ = _build_design(fwd_target, dict(controls))
    if X_ctrl.shape[1] >= 2:
        _, _, r2_ctrl = _ols_with_hac(X_ctrl, y, names_ctrl, hac_lags=hac_lags)
    else:
        r2_ctrl = 0.0

    return InformationRegressionResult(
        target_name=str(target_name),
        horizon=horizon,
        n_obs=len(y),
        r_squared=float(r2_full),
        r_squared_controls_only=float(r2_ctrl),
        incremental_r_squared=float(r2_full - r2_ctrl),
        terms=tuple(terms_full),
        notes=f"forward {horizon}-period max of {target_name}, HAC lags={hac_lags}",
    )


# --------------------------------------------------------------------------
# Test B - out-of-sample forecast comparison
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class OOSForecastResult:
    target_name: str
    horizon: int
    train_end: pd.Timestamp
    eval_start: pd.Timestamp
    eval_end: pd.Timestamp
    n_train: int
    n_eval: int
    metrics_per_model: dict[str, dict[str, float]]
    winner: str = ""

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.metrics_per_model).T


def structural_model_comparison(
    outcome: pd.Series,
    nfci: pd.Series,
    sigma: pd.Series,
    components: pd.DataFrame,
    residualized_components: pd.DataFrame | None = None,
    horizon: int = 30,
    binary_threshold: float | None = None,
    train_end: str = "2018-12-31",
    eval_start: str = "2019-01-01",
    eval_end: str | None = None,
) -> OOSForecastResult:
    """Compare the paper protocol models A-D without treating Sigma as a trading signal.

    Model A: outcome ~ NFCI
    Model B: outcome ~ NFCI + Sigma_t
    Model C: outcome ~ NFCI + M + D + K + X
    Model D: outcome ~ NFCI + residualized components
    """
    if not _SKLEARN_OK:
        raise RuntimeError("scikit-learn is required for structural_model_comparison")
    needed = [col for col in ("M", "D", "K", "X") if col in components.columns]
    if len(needed) != 4:
        raise ValueError("components must contain M, D, K, X columns")
    target_name = outcome.name or "outcome"
    fwd_target = pd.to_numeric(outcome, errors="coerce").shift(-horizon).rolling(horizon, min_periods=1).max()
    is_binary = binary_threshold is not None
    if is_binary:
        fwd_target = (fwd_target >= binary_threshold).astype(float)

    base = pd.concat(
        [
            fwd_target.rename("__y__"),
            pd.to_numeric(nfci, errors="coerce").rename("NFCI"),
            pd.to_numeric(sigma, errors="coerce").rename("Sigma_t"),
            components[["M", "D", "K", "X"]].apply(pd.to_numeric, errors="coerce"),
        ],
        axis=1,
    )
    if residualized_components is not None:
        resid = residualized_components.copy()
        resid.columns = [f"resid_{c}" for c in resid.columns]
        base = pd.concat([base, resid.apply(pd.to_numeric, errors="coerce")], axis=1)
    full = base.dropna()
    if full.empty:
        raise ValueError("No overlapping observations across outcome, NFCI, Sigma, and components")

    train_end_ts = pd.Timestamp(train_end)
    eval_start_ts = pd.Timestamp(eval_start)
    eval_end_ts = pd.Timestamp(eval_end) if eval_end else full.index.max()
    train_mask, eval_mask = _split(full.index, train_end_ts, eval_start_ts, eval_end_ts)
    if train_mask.sum() < 50 or eval_mask.sum() < 20:
        raise ValueError(f"Train/eval windows too small: train={int(train_mask.sum())}, eval={int(eval_mask.sum())}")

    feature_sets = {
        "Model_A_NFCI": ["NFCI"],
        "Model_B_NFCI_plus_Sigma": ["NFCI", "Sigma_t"],
        "Model_C_NFCI_plus_MDKX": ["NFCI", "M", "D", "K", "X"],
    }
    resid_cols = [c for c in full.columns if c.startswith("resid_")]
    if resid_cols:
        feature_sets["Model_D_NFCI_plus_residualized_components"] = ["NFCI"] + resid_cols

    y_train = full.loc[train_mask, "__y__"].to_numpy()
    y_eval = full.loc[eval_mask, "__y__"].to_numpy()
    train_mean = float(y_train.mean())
    eval_baseline = np.full_like(y_eval, train_mean, dtype=float)
    metrics_per_model: dict[str, dict[str, float]] = {}
    for label, cols in feature_sets.items():
        Xtr = full.loc[train_mask, cols].to_numpy()
        Xev = full.loc[eval_mask, cols].to_numpy()
        try:
            if is_binary:
                clf = LogisticRegression(max_iter=1000, solver="lbfgs")
                clf.fit(Xtr, y_train)
                p = clf.predict_proba(Xev)[:, 1]
                metrics = _metrics_binary(y_eval, p)
                metrics.update(_classification_operating_metrics(y_eval, p))
            else:
                reg = LinearRegression()
                reg.fit(Xtr, y_train)
                yhat = reg.predict(Xev)
                metrics = _metrics_continuous(y_eval, yhat, baseline=eval_baseline)
            metrics_per_model[label] = metrics
        except Exception as exc:
            metrics_per_model[label] = {"error": str(exc)}

    winner_metric = "auc" if is_binary else "oos_r2"
    winner = max(metrics_per_model, key=lambda label: metrics_per_model[label].get(winner_metric, float("-inf")))
    return OOSForecastResult(
        target_name=str(target_name),
        horizon=horizon,
        train_end=train_end_ts,
        eval_start=eval_start_ts,
        eval_end=eval_end_ts,
        n_train=int(train_mask.sum()),
        n_eval=int(eval_mask.sum()),
        metrics_per_model=metrics_per_model,
        winner=winner,
    )


def _split(idx: pd.DatetimeIndex, train_end: pd.Timestamp, eval_start: pd.Timestamp, eval_end: pd.Timestamp) -> tuple[np.ndarray, np.ndarray]:
    train_mask = idx <= train_end
    eval_mask = (idx >= eval_start) & (idx <= eval_end)
    return train_mask, eval_mask


def _metrics_continuous(y_true: np.ndarray, y_pred: np.ndarray, baseline: np.ndarray | None = None) -> dict[str, float]:
    if len(y_true) == 0:
        return {"oos_r2": 0.0, "rmse": 0.0, "mae": 0.0}
    rmse = float(np.sqrt(np.mean((y_true - y_pred) ** 2)))
    mae = float(np.mean(np.abs(y_true - y_pred)))
    base = baseline if baseline is not None else np.full_like(y_true, y_true.mean())
    ss_res = float(np.sum((y_true - y_pred) ** 2))
    ss_tot = float(np.sum((y_true - base) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return {"oos_r2": float(r2), "rmse": rmse, "mae": mae}


def _metrics_binary(y_true: np.ndarray, p_pred: np.ndarray) -> dict[str, float]:
    p = np.clip(p_pred, 1e-6, 1 - 1e-6)
    brier = float(np.mean((p - y_true) ** 2))
    out: dict[str, float] = {"brier": brier}
    if len(np.unique(y_true)) > 1 and _SKLEARN_OK:
        try:
            out["auc"] = float(roc_auc_score(y_true, p))
        except (ValueError, RuntimeError):
            pass
    return out


def _classification_operating_metrics(y_true: np.ndarray, p_pred: np.ndarray, threshold: float = 0.5) -> dict[str, float]:
    y_hat = (p_pred >= threshold).astype(float)
    tp = float(np.sum((y_hat == 1) & (y_true == 1)))
    fp = float(np.sum((y_hat == 1) & (y_true == 0)))
    fn = float(np.sum((y_hat == 0) & (y_true == 1)))
    tn = float(np.sum((y_hat == 0) & (y_true == 0)))
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    false_alarm_rate = fp / (fp + tn) if (fp + tn) else 0.0
    hit_rate = recall
    log_loss = float(-np.mean(y_true * np.log(np.clip(p_pred, 1e-6, 1.0)) + (1.0 - y_true) * np.log(np.clip(1.0 - p_pred, 1e-6, 1.0))))
    return {
        "precision": float(precision),
        "recall": float(recall),
        "false_alarm_rate": float(false_alarm_rate),
        "hit_rate": float(hit_rate),
        "log_loss": log_loss,
    }


def out_of_sample_forecast(
    target: pd.Series,
    signal: pd.Series,
    controls: Mapping[str, pd.Series],
    horizon: int = 30,
    train_end: str = "2018-12-31",
    eval_start: str = "2019-01-01",
    eval_end: str | None = None,
    binary_threshold: float | None = None,
) -> OOSForecastResult:
    if not _SKLEARN_OK:
        raise RuntimeError("scikit-learn is required for out_of_sample_forecast")

    target_name = target.name or "target"
    fwd_target = pd.to_numeric(target, errors="coerce").shift(-horizon).rolling(horizon, min_periods=1).max()

    is_binary = binary_threshold is not None
    if is_binary:
        fwd_target = (fwd_target >= binary_threshold).astype(float)

    sig = pd.to_numeric(signal, errors="coerce").rename("__signal__")
    ctrl_frame = pd.concat({name: pd.to_numeric(s, errors="coerce") for name, s in controls.items()}, axis=1)
    full = pd.concat([fwd_target.rename("__y__"), sig, ctrl_frame], axis=1).dropna()
    if full.empty:
        raise ValueError("No overlapping observations across target/signal/controls")

    train_end_ts = pd.Timestamp(train_end)
    eval_start_ts = pd.Timestamp(eval_start)
    eval_end_ts = pd.Timestamp(eval_end) if eval_end else full.index.max()

    train_mask = full.index <= train_end_ts
    eval_mask = (full.index >= eval_start_ts) & (full.index <= eval_end_ts)
    if train_mask.sum() < 50 or eval_mask.sum() < 20:
        raise ValueError(f"Train/eval windows too small: train={int(train_mask.sum())}, eval={int(eval_mask.sum())}")

    y_train = full.loc[train_mask, "__y__"].to_numpy()
    y_eval = full.loc[eval_mask, "__y__"].to_numpy()
    train_mean = float(y_train.mean())
    eval_baseline = np.full_like(y_eval, train_mean, dtype=float)

    feature_sets = {
        "signal_only": ["__signal__"],
        "controls_only": list(ctrl_frame.columns),
        "signal_plus_controls": ["__signal__"] + list(ctrl_frame.columns),
    }

    metrics_per_model: dict[str, dict[str, float]] = {}
    for label, cols in feature_sets.items():
        if not cols:
            continue
        Xtr = full.loc[train_mask, cols].to_numpy()
        Xev = full.loc[eval_mask, cols].to_numpy()
        if is_binary:
            try:
                clf = LogisticRegression(max_iter=1000, solver="lbfgs")
                clf.fit(Xtr, y_train)
                p = clf.predict_proba(Xev)[:, 1]
                metrics_per_model[label] = _metrics_binary(y_eval, p)
            except Exception as exc:
                metrics_per_model[label] = {"error": str(exc)}
        else:
            try:
                reg = LinearRegression()
                reg.fit(Xtr, y_train)
                yhat = reg.predict(Xev)
                metrics_per_model[label] = _metrics_continuous(y_eval, yhat, baseline=eval_baseline)
            except Exception as exc:
                metrics_per_model[label] = {"error": str(exc)}

    winner_metric = "auc" if is_binary else "oos_r2"
    winner = ""
    best_score = float("-inf")
    for label, m in metrics_per_model.items():
        score = m.get(winner_metric, float("-inf"))
        if score > best_score:
            best_score = score
            winner = label

    return OOSForecastResult(
        target_name=str(target_name),
        horizon=horizon,
        train_end=train_end_ts,
        eval_start=eval_start_ts,
        eval_end=eval_end_ts,
        n_train=int(train_mask.sum()),
        n_eval=int(eval_mask.sum()),
        metrics_per_model=metrics_per_model,
        winner=winner,
    )


# --------------------------------------------------------------------------
# Test C - regime classification lead/lag
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class RegimeLeadLagResult:
    signal_name: str
    regime_name: str
    best_lag: int
    best_correlation: float
    cross_correlation: pd.Series
    median_lead_days: float
    n_regimes: int


def regime_lead_lag(
    signal: pd.Series,
    regime: pd.Series,
    max_lag: int = 60,
) -> RegimeLeadLagResult:
    sig = pd.to_numeric(signal, errors="coerce")
    reg = pd.to_numeric(regime, errors="coerce").astype(float)
    aligned = pd.concat([sig.rename("sig"), reg.rename("reg")], axis=1).dropna()
    if aligned.empty:
        return RegimeLeadLagResult(
            signal_name=str(signal.name or "signal"),
            regime_name=str(regime.name or "regime"),
            best_lag=0,
            best_correlation=0.0,
            cross_correlation=pd.Series(dtype=float),
            median_lead_days=float("nan"),
            n_regimes=0,
        )

    s = aligned["sig"]
    r = aligned["reg"]
    lags = range(-max_lag, max_lag + 1)
    correlations: dict[int, float] = {}
    for lag in lags:
        if lag < 0:
            corr = s.shift(-lag).corr(r)
        else:
            corr = s.corr(r.shift(lag))
        correlations[lag] = float(corr) if pd.notna(corr) else 0.0

    cc_series = pd.Series(correlations).sort_index()
    best_lag = int(cc_series.idxmax())
    best_corr = float(cc_series.max())

    regime_bool = (r > 0).astype(int)
    starts = regime_bool[(regime_bool == 1) & (regime_bool.shift(1, fill_value=0) == 0)].index
    leads: list[float] = []
    for start in starts:
        prior = s.loc[: start - pd.Timedelta(days=1)] if hasattr(start, "to_pydatetime") else s.loc[:start]
        if prior.empty:
            continue
        threshold = prior.expanding().quantile(0.85).iloc[-1]
        crossings = prior[prior >= threshold]
        if crossings.empty:
            continue
        last_cross = crossings.index[-1]
        if hasattr(start, "to_pydatetime"):
            lead = (start - last_cross).days
        else:
            lead = float(start - last_cross)
        leads.append(float(lead))

    median_lead = float(np.median(leads)) if leads else float("nan")
    return RegimeLeadLagResult(
        signal_name=str(signal.name or "signal"),
        regime_name=str(regime.name or "regime"),
        best_lag=best_lag,
        best_correlation=best_corr,
        cross_correlation=cc_series,
        median_lead_days=median_lead,
        n_regimes=int(len(starts)),
    )


# --------------------------------------------------------------------------
# Test D - mechanism specificity
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class MechanismSpecificityResult:
    case_name: str
    window_start: pd.Timestamp
    window_end: pd.Timestamp
    expected_leading_channel: str
    observed_leading_channel: str
    channel_dominance: dict[str, float]
    matches_expectation: bool
    sigma_at_event: float
    leading_channel_share: float


def mechanism_specificity(
    case_name: str,
    channels: pd.DataFrame,
    sigma: pd.Series,
    window_start: str,
    window_end: str,
    expected_channel: str,
) -> MechanismSpecificityResult:
    if not {"M", "D", "K", "X"}.issubset(channels.columns):
        raise ValueError("channels frame must have M, D, K, X columns")
    start = pd.Timestamp(window_start)
    end = pd.Timestamp(window_end)
    sub = channels.loc[start:end].copy()
    if sub.empty:
        return MechanismSpecificityResult(
            case_name=case_name,
            window_start=start,
            window_end=end,
            expected_leading_channel=expected_channel,
            observed_leading_channel="UNKNOWN",
            channel_dominance={"M": 0.0, "D": 0.0, "K": 0.0, "X": 0.0},
            matches_expectation=False,
            sigma_at_event=0.0,
            leading_channel_share=0.0,
        )

    abs_sub = sub.copy()
    abs_sub["D"] = -sub["D"]
    abs_sub = abs_sub[["M", "D", "K", "X"]].clip(lower=0.0)
    totals = abs_sub.sum(axis=0)
    grand = float(totals.sum())
    dominance = {ch: float(totals[ch] / grand) if grand > 0 else 0.0 for ch in ("M", "D", "K", "X")}
    observed = max(dominance, key=lambda k: dominance[k])
    sigma_event = float(pd.to_numeric(sigma.reindex(sub.index), errors="coerce").fillna(0.0).iloc[-1]) if not sub.empty else 0.0

    return MechanismSpecificityResult(
        case_name=case_name,
        window_start=start,
        window_end=end,
        expected_leading_channel=expected_channel,
        observed_leading_channel=observed,
        channel_dominance=dominance,
        matches_expectation=observed == expected_channel,
        sigma_at_event=sigma_event,
        leading_channel_share=dominance[observed],
    )


# --------------------------------------------------------------------------
# Convenience wrapper
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class IncrementalInformationReport:
    test_a: tuple[InformationRegressionResult, ...]
    test_b: tuple[OOSForecastResult, ...]
    test_c: tuple[RegimeLeadLagResult, ...]
    test_d: tuple[MechanismSpecificityResult, ...]

    def to_summary_frame(self) -> pd.DataFrame:
        rows: list[dict[str, object]] = []
        for r in self.test_a:
            sig = next((t for t in r.terms if t.name not in ("__intercept__",) and "SIGMA" in t.name.upper()), None)
            rows.append({
                "test": "A_information_regression",
                "target": r.target_name,
                "horizon": r.horizon,
                "incremental_r2": round(r.incremental_r_squared, 4),
                "signal_t_stat": round(sig.t_stat, 3) if sig else None,
                "signal_p_value": round(sig.p_value, 4) if sig else None,
                "n_obs": r.n_obs,
            })
        for r in self.test_b:
            best = r.metrics_per_model.get(r.winner, {})
            rows.append({
                "test": "B_oos_forecast",
                "target": r.target_name,
                "horizon": r.horizon,
                "winner": r.winner,
                "winner_metric": next(iter(best.values())) if best else None,
                "n_train": r.n_train,
                "n_eval": r.n_eval,
            })
        for r in self.test_c:
            rows.append({
                "test": "C_regime_lead_lag",
                "signal": r.signal_name,
                "regime": r.regime_name,
                "best_lag": r.best_lag,
                "best_corr": round(r.best_correlation, 3),
                "median_lead_days": r.median_lead_days,
                "n_regimes": r.n_regimes,
            })
        for r in self.test_d:
            rows.append({
                "test": "D_mechanism_specificity",
                "case": r.case_name,
                "expected": r.expected_leading_channel,
                "observed": r.observed_leading_channel,
                "match": r.matches_expectation,
                "leading_share": round(r.leading_channel_share, 3),
                "sigma_at_event": round(r.sigma_at_event, 3),
            })
        return pd.DataFrame(rows)


__all__ = [
    "IncrementalInformationReport",
    "InformationRegressionResult",
    "MechanismSpecificityResult",
    "OOSForecastResult",
    "RegimeLeadLagResult",
    "RegressionTermStat",
    "information_regression",
    "mechanism_specificity",
    "out_of_sample_forecast",
    "regime_lead_lag",
    "structural_model_comparison",
]
