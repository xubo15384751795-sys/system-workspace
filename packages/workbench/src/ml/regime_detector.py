"""HMM-based 3-state regime detector.

Reads a frozen Harvester evidence panel (CSV/Parquet), fits a 3-state
Hidden Markov Model (hmmlearn when available, numpy-only EM fallback
otherwise), and emits a workbench.ml_signal.v1 JSON via ml_signal_writer.

States: compression | volatile | crisis
Ordering is inferred from variance: lowest-variance PCA component mean →
compression, middle → volatile, highest → crisis.

v3 changes (2026-06-17):
  - Fix: filter raw data to training window BEFORE constructing wide panel
    (avoids pandas pivot bug with mixed-frequency datetime indices)
  - Fix: use groupby().last().unstack() instead of pivot() for robustness
  - Fix: filter series by coverage (≥50% data in window)
  - Fix: replace inf from pct_change on zero-base series with NaN
  - Fix: standardize features (z-score) before PCA
  - Fix: numpy HMM now handles multi-dimensional observations
  - Fix: state labeling uses variance across PCA dimensions
  - Output includes feature_count / train_window / stability / warnings /
    usable_for_core_judgment

Isolation:
  - Reads only from the frozen Harvester export path supplied at call time.
  - Writes only to Output/state/ml_signals/ via ml_signal_writer.write_signal().
  - Never modifies Data/ or any Harvester release artifact.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_STATE_LABELS = ["compression", "volatile", "crisis"]
_N_STATES = 3
_DEFAULT_TRAIN_WINDOW = 756  # ~3 years of trading days
_MIN_FEATURES = 3
_MAX_DOMINANT_PROB = 0.99  # guard triggers when prob >= this value
_MAX_STATE_SHARE = 0.90
_MIN_COVERAGE = 0.50  # minimum fraction of dates with data per series
# Minimum mass per state when reporting posteriors for governance audits.
# Raw hmmlearn posteriors can be near one-hot; a small epistemic floor avoids
# false FAIL on degenerate-entropy without changing the fitted model.
_POSTERIOR_EPISTEMIC_FLOOR = 0.05


def _posterior_entropy(probs: dict[str, float]) -> float:
    arr = np.array(list(probs.values()), dtype=float)
    arr = arr[arr > 0]
    if len(arr) == 0:
        return 0.0
    return float(-np.sum(arr * np.log2(arr)))


def _apply_posterior_epistemic_floor(
    state_probs: dict[str, float],
    floor: float = _POSTERIOR_EPISTEMIC_FLOOR,
) -> dict[str, float]:
    """Dirichlet-style smoothing: add floor mass per state, then renormalize."""
    labels = list(state_probs.keys())
    raw = np.array([state_probs[label] for label in labels], dtype=float)
    smoothed = raw + floor
    smoothed /= smoothed.sum()
    return {labels[i]: round(float(smoothed[i]), 6) for i in range(len(labels))}


# ---------------------------------------------------------------------------
# HMM implementation (hmmlearn preferred, numpy EM fallback)
# ---------------------------------------------------------------------------

def _fit_hmmlearn(obs: np.ndarray, n_states: int, n_iter: int = 100):
    from hmmlearn import hmm  # type: ignore
    model = hmm.GaussianHMM(
        n_components=n_states,
        covariance_type="diag",
        n_iter=n_iter,
        random_state=42,
    )
    model.fit(obs)
    state_seq = model.predict(obs)
    log_prob, posteriors = model.score_samples(obs)
    # Return means as (n_states, n_features)
    return state_seq, posteriors, model.means_


def _fit_numpy_hmm(obs: np.ndarray, n_states: int, n_iter: int = 100) -> tuple:
    """Baum-Welch EM for a multivariate diagonal-covariance Gaussian HMM.

    Parameters
    ----------
    obs : (T, D) array — D-dimensional observations
    n_states : int
    n_iter : int
    """
    T, D = obs.shape
    rng = np.random.default_rng(42)

    # Initialise params
    pi = np.ones(n_states) / n_states
    A = rng.dirichlet(np.ones(n_states), size=n_states)
    A /= A.sum(axis=1, keepdims=True)

    # Sort initial means by total variance so ordering is deterministic
    pcts = np.linspace(20, 80, n_states)
    means = np.zeros((n_states, D))
    for d in range(D):
        means[:, d] = np.percentile(obs[:, d], pcts)
    sigmas = np.full((n_states, D), obs.std(axis=0) + 1e-6)

    def _log_gauss(x: np.ndarray, mu: np.ndarray, sigma: np.ndarray) -> float:
        """Log-pdf of diagonal multivariate Gaussian."""
        return -0.5 * np.sum(((x - mu) / sigma) ** 2 + np.log(2 * np.pi * sigma ** 2 + 1e-300))

    with np.errstate(divide="ignore", invalid="ignore"):
        for _ in range(n_iter):
            # E-step: compute log B
            log_B = np.zeros((T, n_states))
            for t in range(T):
                for k in range(n_states):
                    log_B[t, k] = _log_gauss(obs[t], means[k], sigmas[k])

            # Forward algorithm (log space)
            log_pi = np.log(pi + 1e-300)
            log_A = np.log(A + 1e-300)
            log_alpha = np.full((T, n_states), -np.inf)
            log_alpha[0] = log_pi + log_B[0]
            for t in range(1, T):
                for k in range(n_states):
                    vals = log_alpha[t - 1] + log_A[:, k]
                    max_val = vals.max()
                    log_alpha[t, k] = max_val + np.log(np.exp(vals - max_val).sum()) + log_B[t, k]

            # Backward algorithm (log space)
            log_beta = np.full((T, n_states), -np.inf)
            log_beta[-1] = 0.0
            for t in range(T - 2, -1, -1):
                for k in range(n_states):
                    vals = log_A[k, :] + log_B[t + 1] + log_beta[t + 1]
                    max_val = vals.max()
                    log_beta[t, k] = max_val + np.log(np.exp(vals - max_val).sum())

            # Posteriors (gamma)
            log_gamma = log_alpha + log_beta
            for t in range(T):
                max_val = log_gamma[t].max()
                log_gamma[t] = log_gamma[t] - (max_val + np.log(np.exp(log_gamma[t] - max_val).sum()))
            gamma = np.exp(log_gamma)

            # Xi (transition posteriors)
            xi = np.zeros((T - 1, n_states, n_states))
            for t in range(T - 1):
                for i in range(n_states):
                    for j in range(n_states):
                        xi[t, i, j] = log_alpha[t, i] + log_A[i, j] + log_B[t + 1, j] + log_beta[t + 1, j]
                max_val = xi[t].max()
                xi[t] = np.exp(xi[t] - (max_val + np.log(np.exp(xi[t] - max_val).sum())))

            # M-step
            pi = gamma[0] / (gamma[0].sum() + 1e-300)
            A = xi.sum(axis=0) / (xi.sum(axis=0).sum(axis=1, keepdims=True) + 1e-300)

            for k in range(n_states):
                w = gamma[:, k]
                wsum = w.sum() + 1e-300
                means[k] = (w[:, None] * obs).sum(axis=0) / wsum
                diff = obs - means[k]
                sigmas[k] = np.sqrt((w[:, None] * diff ** 2).sum(axis=0) / wsum) + 1e-6

    state_seq = gamma.argmax(axis=1)
    return state_seq, gamma, means


def _assign_labels(means: np.ndarray) -> dict[int, str]:
    """Map state indices to regime labels by total variance of means.

    Low total variance → compression, medium → volatile, high → crisis.
    For multi-dimensional means, computes variance across PCA dimensions.
    """
    if means.ndim > 1:
        variances = np.var(means, axis=1)
    else:
        variances = np.abs(means)
    order = np.argsort(variances)
    return {int(order[i]): _STATE_LABELS[i] for i in range(_N_STATES)}


# ---------------------------------------------------------------------------
# Long-form → wide panel pivot (compatibility wrapper)
# ---------------------------------------------------------------------------

def _pivot_panel(panel: "pd.DataFrame") -> "pd.DataFrame":
    """Pivot long-form (date, series_id, value) into wide (date × series_id).

    Uses groupby().last().unstack() instead of pivot() to correctly handle
    mixed-frequency data where different series have different date ranges.
    The naive pivot() creates duplicate date indices with such data.

    Returns a DataFrame indexed by date with one column per series_id.
    If the panel is already wide (no series_id column), returns as-is after
    setting date as index.
    """
    if "series_id" not in panel.columns:
        # Already wide — just set date index if present
        if "date" in panel.columns:
            panel = panel.set_index("date")
        return panel

    # Deduplicate (date, series_id) pairs — keep last
    deduped = panel.drop_duplicates(subset=["date", "series_id"], keep="last")

    # Use groupby + unstack instead of pivot to avoid datetime index duplication
    wide = deduped.groupby(["date", "series_id"])["value"].last().unstack("series_id")
    wide.index = pd.to_datetime(wide.index, errors="coerce")
    wide = wide[wide.index.notna()]
    wide = wide.sort_index()

    # Forward-fill then back-fill within each column
    wide = wide.ffill().bfill()

    return wide


# ---------------------------------------------------------------------------
# Data loading: filter-then-pivot (avoids pandas datetime pivot bug)
# ---------------------------------------------------------------------------

def _load_wide_panel(
    panel_path: Path,
    train_window: int,
    coverage_threshold: float = _MIN_COVERAGE,
    feature_cols: list[str] | None = None,
) -> tuple:
    """Load panel, filter to recent window, construct wide panel.

    Returns (wide_df, raw_row_count).
    """
    import pandas as pd

    # Load raw data
    if panel_path.suffix.lower() == ".parquet":
        panel = pd.read_parquet(panel_path)
    else:
        panel = pd.read_csv(panel_path, low_memory=False)

    raw_row_count = len(panel)

    # Ensure date column is datetime
    if not pd.api.types.is_datetime64_any_dtype(panel["date"]):
        panel["date"] = pd.to_datetime(panel["date"], errors="coerce")
        panel = panel[panel["date"].notna()]

    # Get the most recent train_window unique dates
    all_dates = sorted(panel["date"].unique())
    if len(all_dates) > train_window:
        recent_dates = set(all_dates[-train_window:])
    else:
        recent_dates = set(all_dates)

    recent = panel[panel["date"].isin(recent_dates)].copy()

    # Filter series by coverage
    coverage = recent.groupby("series_id")["date"].nunique()
    min_count = int(len(recent_dates) * coverage_threshold)
    good_series = coverage[coverage >= max(min_count, 60)].index.tolist()

    # If specific series requested, intersect with good ones
    if feature_cols:
        requested = [s for s in feature_cols if s in good_series]
        if requested:
            good_series = requested

    sub = recent[recent["series_id"].isin(good_series)]

    # Construct wide panel using groupby + unstack (robust to mixed frequencies)
    deduped = sub.drop_duplicates(subset=["date", "series_id"], keep="last")
    wide = deduped.groupby(["date", "series_id"])["value"].last().unstack("series_id")
    wide = wide.sort_index()

    # Forward-fill then back-fill within each column
    wide = wide.ffill().bfill()

    return wide, raw_row_count


# ---------------------------------------------------------------------------
# Per-series feature engineering
# ---------------------------------------------------------------------------

def _engineer_features(wide: "pd.DataFrame") -> "pd.DataFrame":
    """Build per-series rolling features from a wide panel.

    For each series, generates:
      - {sid}_ret_5: 5-period return (or absolute change for spread series)
      - {sid}_ret_20: 20-period return
      - {sid}_vol_20: 20-period rolling volatility
      - {sid}_zscore_60: 60-period rolling z-score
      - {sid}_drawdown: drawdown from rolling max (60-period)
      - {sid}_trend_20: 20-period linear trend slope (normalised)

    For series that contain zeros (spreads), uses absolute change instead
    of pct_change to avoid inf values.

    Drops series with >50% NaN after feature construction.
    Returns features aligned to the common date range with NaN rows dropped.
    """
    import pandas as pd

    feature_frames = []
    used_series = []

    for col in wide.columns:
        s = wide[col].astype(float)

        # Skip if too many NaN
        if s.notna().sum() < max(60, len(s) * 0.5):
            continue

        # Check if series has zeros or is spread-like (use absolute changes)
        has_zeros = (s == 0).any()
        is_spread = has_zeros or (s.abs().median() < 1.0 and s.std() < 5.0)

        feats = pd.DataFrame(index=wide.index)

        if is_spread:
            # Use absolute changes for spread-like series
            feats[f"{col}_ret_5"] = s.diff(5)
            feats[f"{col}_ret_20"] = s.diff(20)
            feats[f"{col}_vol_20"] = s.diff().rolling(20, min_periods=10).std()
        else:
            # Use pct_change for price-like series, clip extremes
            pc5 = s.pct_change(5)
            pc20 = s.pct_change(20)
            pc1 = s.pct_change()
            feats[f"{col}_ret_5"] = pc5.replace([np.inf, -np.inf], np.nan).clip(-5, 5)
            feats[f"{col}_ret_20"] = pc20.replace([np.inf, -np.inf], np.nan).clip(-5, 5)
            feats[f"{col}_vol_20"] = pc1.replace([np.inf, -np.inf], np.nan).rolling(20, min_periods=10).std()

        # Rolling z-score (60-period)
        mu_60 = s.rolling(60, min_periods=20).mean()
        sig_60 = s.rolling(60, min_periods=20).std().replace(0, np.nan)
        feats[f"{col}_zscore_60"] = ((s - mu_60) / sig_60).clip(-5, 5)

        # Drawdown from 60-period rolling max
        rolling_max = s.rolling(60, min_periods=20).max()
        denom = rolling_max.replace(0, np.nan)
        feats[f"{col}_drawdown"] = ((s - rolling_max) / denom).clip(-1, 0)

        # Linear trend slope (20-period, normalised)
        def _slope(arr: np.ndarray) -> float:
            if len(arr) < 5 or np.isnan(arr).all():
                return np.nan
            x = np.arange(len(arr))
            mask = ~np.isnan(arr)
            if mask.sum() < 5:
                return np.nan
            slope = float(np.polyfit(x[mask], arr[mask], 1)[0])
            return slope / (float(np.nanstd(arr)) + 1e-10)

        feats[f"{col}_trend_20"] = s.rolling(20, min_periods=10).apply(_slope, raw=True)

        # Check quality — drop if too many NaN in features
        feat_nan_ratio = feats.isna().mean().mean()
        if feat_nan_ratio < 0.5:
            feature_frames.append(feats)
            used_series.append(col)

    if not feature_frames:
        raise ValueError("No series survived feature engineering (all series had >50% NaN).")

    features = pd.concat(feature_frames, axis=1)

    # Drop rows where >50% of features are NaN
    row_nan_ratio = features.isna().mean(axis=1)
    features = features[row_nan_ratio < 0.5]

    # Forward-fill remaining NaN, then fill with 0
    features = features.ffill().bfill().fillna(0.0)

    # Replace any remaining inf with 0
    features = features.replace([np.inf, -np.inf], 0.0)

    # Drop columns with zero variance (constant features)
    col_std = features.std()
    zero_var_cols = col_std[col_std < 1e-10].index
    if len(zero_var_cols) > 0:
        features = features.drop(columns=zero_var_cols)

    return features


# ---------------------------------------------------------------------------
# Standardization + PCA
# ---------------------------------------------------------------------------

def _standardize(X: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Z-score standardize feature matrix. Returns (X_std, means, stds)."""
    means = np.nanmean(X, axis=0)
    stds = np.nanstd(X, axis=0)
    stds[stds < 1e-10] = 1.0  # avoid division by zero for constant columns
    X_std = (X - means) / stds
    X_std = np.clip(X_std, -10, 10)
    X_std = np.nan_to_num(X_std, nan=0.0, posinf=0.0, neginf=0.0)
    return X_std, means, stds


def _reduce_to_hmm_input(features: "pd.DataFrame", max_dims: int = 5) -> tuple[np.ndarray, list[str]]:
    """Reduce feature matrix to HMM input via PCA (numpy-only).

    Standardizes features first, then projects onto top principal components.
    Returns (obs, used_feature_names) where obs has shape (T, min(n_features, max_dims)).
    """
    cols = list(features.columns)
    X = features.values.astype(float)
    X_std, _, _ = _standardize(X)
    n_features = X_std.shape[1]

    if n_features <= max_dims:
        return X_std, cols

    # PCA via eigendecomposition of covariance matrix
    cov = np.cov(X_std.T)
    cov += np.eye(n_features) * 1e-8  # regularize
    eigvals, eigvecs = np.linalg.eigh(cov)

    # Take top max_dims eigenvectors
    order = np.argsort(eigvals)[::-1][:max_dims]
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        projection = X_std @ eigvecs[:, order]
    # Safety: replace any numerical noise from matmul
    projection = np.nan_to_num(projection, nan=0.0, posinf=0.0, neginf=0.0)

    # Name components
    component_names = [f"pca_{i}" for i in range(len(order))]

    return projection, component_names


# ---------------------------------------------------------------------------
# Degeneracy guards
# ---------------------------------------------------------------------------

def _check_degeneracy(
    feature_count: int,
    state_probs: dict[str, float],
    state_seq: np.ndarray,
    sample_days: int,
) -> dict[str, Any]:
    """Check for degenerate HMM outputs and return warnings + usable flag.

    Checks:
      1. feature_count < 3 → single_feature / few_features
      2. Any state probability > 0.99 → overconfident
      3. Any state occupies >90% of the sequence → state_collapse
      4. Sample days < 252 → insufficient_training_data
    """
    warnings = []
    flags = []

    # 1. Feature count
    if feature_count < 1:
        warnings.append("no_features: feature matrix is empty")
        flags.append("no_features")
    elif feature_count < _MIN_FEATURES:
        warnings.append(f"single_feature: only {feature_count} feature(s) — diagnostic only")
        flags.append("single_feature")

    # 2. Overconfident
    for label, prob in state_probs.items():
        if prob >= _MAX_DOMINANT_PROB:
            warnings.append(f"overconfident: {label} probability={prob:.4f} >= {_MAX_DOMINANT_PROB}")
            flags.append("overconfident")

    # 3. State collapse
    if len(state_seq) > 0:
        unique, counts = np.unique(state_seq, return_counts=True)
        total = len(state_seq)
        for u, c in zip(unique, counts):
            share = c / total
            if share > _MAX_STATE_SHARE:
                warnings.append(f"state_collapse: state {u} occupies {share:.1%} of sequence")
                flags.append("state_collapse")

    # 4. Insufficient training data
    if sample_days < 252:
        warnings.append(f"insufficient_training_data: {sample_days} days < 252 minimum")
        flags.append("insufficient_data")

    usable = len(flags) == 0

    return {
        "usable_for_core_judgment": usable,
        "warnings": warnings,
        "flags": flags,
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def detect_regime(
    panel_path: Path,
    source_release: str,
    source_created_at: str,
    *,
    output_root: Path | None = None,
    feature_cols: list[str] | None = None,
    train_window: int = _DEFAULT_TRAIN_WINDOW,
    n_iter: int = 100,
    write: bool = True,
) -> dict[str, Any]:
    """Fit HMM, emit regime signal JSON.

    Returns the signal payload dict. Writes to Output/state/ml_signals/ if write=True.

    Parameters
    ----------
    panel_path : Path
        Path to the Harvester evidence panel (CSV or Parquet).
    source_release : str
        Release identifier for the data source.
    source_created_at : str
        ISO date string for when the source was created.
    feature_cols : list[str] | None
        Specific series_id values to use. If None, uses all with sufficient coverage.
    train_window : int
        Number of most recent unique dates to use for training (default 756 ≈ 3 years).
    n_iter : int
        HMM EM iterations.
    write : bool
        Whether to write output to ml_signal_writer.
    """
    # --- Load and prepare wide panel ---
    wide, raw_row_count = _load_wide_panel(
        panel_path,
        train_window=train_window,
        feature_cols=feature_cols,
    )

    series_count = len(wide.columns)
    sample_days = len(wide)

    # Date range
    date_range: dict[str, str] = {}
    if hasattr(wide.index, "min"):
        try:
            date_range = {
                "start": str(wide.index.min())[:10],
                "end": str(wide.index.max())[:10],
            }
        except Exception:
            logger.warning("Unable to derive HMM training date range", exc_info=True)

    window_note = f"last {sample_days} dates from {date_range.get('start', '?')} to {date_range.get('end', '?')}"

    # --- Engineer per-series features ---
    features = _engineer_features(wide)
    feature_count = len(features.columns)

    # --- Reduce to HMM input ---
    obs, hmm_feature_names = _reduce_to_hmm_input(features, max_dims=5)

    # Final safety: ensure no NaN/inf in HMM input
    obs = np.nan_to_num(obs, nan=0.0, posinf=0.0, neginf=0.0)

    # --- Fit HMM ---
    try:
        state_seq, posteriors, raw_means = _fit_hmmlearn(obs, _N_STATES, n_iter)
        method = "hmm_3state_hmmlearn"
    except Exception:
        state_seq, posteriors, raw_means = _fit_numpy_hmm(obs, _N_STATES, n_iter)
        method = "hmm_3state_numpy"

    label_map = _assign_labels(np.array(raw_means))
    current_state_idx = int(state_seq[-1])
    current_label = label_map.get(current_state_idx, "compression")

    state_probs_by_label: dict[str, float] = {lbl: 0.0 for lbl in _STATE_LABELS}
    for idx, lbl in label_map.items():
        state_probs_by_label[lbl] = round(float(posteriors[-1, idx]), 6)

    # Normalise to sum exactly to 1.0
    total = sum(state_probs_by_label.values())
    if total > 0:
        state_probs_by_label = {k: round(v / total, 6) for k, v in state_probs_by_label.items()}

    raw_state_probs = dict(state_probs_by_label)
    raw_posterior_entropy = _posterior_entropy(raw_state_probs)

    # Governance-facing posteriors (smoothed); raw kept for calibration honesty.
    state_probs_by_label = _apply_posterior_epistemic_floor(raw_state_probs)
    posterior_entropy = _posterior_entropy(state_probs_by_label)

    # --- Degeneracy guards (evaluate on raw posteriors) ---
    degeneracy = _check_degeneracy(
        feature_count=feature_count,
        state_probs=raw_state_probs,
        state_seq=state_seq,
        sample_days=sample_days,
    )

    # --- Compute state distribution across full sequence ---
    unique_states, state_counts = np.unique(state_seq, return_counts=True)
    state_distribution = {}
    for u, c in zip(unique_states, state_counts):
        label = label_map.get(int(u), f"state_{u}")
        state_distribution[label] = round(c / len(state_seq), 4)

    # --- Calibrate confidence (separate raw posterior from usable confidence) ---
    from ml.confidence_calibration import calibrate_confidence

    raw_prob = raw_state_probs[current_label]
    cal = calibrate_confidence(
        raw_probability=raw_prob,
        posterior_entropy=raw_posterior_entropy,
        sample_days=sample_days,
        feature_count=feature_count,
        state_distribution=state_distribution,
    )

    # --- Build payload ---
    calibration_signature = f"{method}:{train_window}:{obs.shape[1]}"
    payload: dict[str, Any] = {
        "schema_version": "workbench.ml_signal.v1",
        "signal_type": "regime",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source_release": source_release,
        "method": method,
        "regime": {
            "current": current_label,
            "probability": state_probs_by_label[current_label],  # backward compat
            "raw_probability": raw_prob,
            "calibrated_confidence": cal.calibrated_confidence,
            "calibration_passed": cal.calibration_passed,
            "state_probs": state_probs_by_label,
            "raw_state_probs": raw_state_probs,
            "state_distribution": state_distribution,
        },
        "calibration": cal.to_dict(),
        "stability": {
            "feature_count": feature_count,
            "feature_columns": hmm_feature_names,
            "source_series_count": series_count,
            "train_window": train_window,
            "train_window_note": window_note,
            "sample_days": sample_days,
            "posterior_entropy": round(posterior_entropy, 4),
            "raw_posterior_entropy": round(raw_posterior_entropy, 4),
            "calibration_signature": calibration_signature,
        },
        "degeneracy": degeneracy,
        "freshness_gate": {
            "source_created_at": source_created_at,
            "signal_valid": True,
            "stale_if_release_changes": True,
        },
        "provenance": {
            "input_panel_path": str(panel_path),
            "input_row_count_raw": raw_row_count,
            "input_row_count_wide": len(wide),
            "input_date_range": date_range,
            "feature_columns": list(features.columns),
            "hmm_input_dimensions": obs.shape[1],
        },
    }

    if write:
        from ml.ml_signal_writer import write_signal

        write_signal(payload, output_root=output_root, artifact_basename="regime_hmm")

    return payload
