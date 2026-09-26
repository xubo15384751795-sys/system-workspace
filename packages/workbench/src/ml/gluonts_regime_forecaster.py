"""Probabilistic regime signal via GluonTS forecasting.

Generates a forecast distribution over a configurable horizon and derives
regime probabilities from quantile breach risk (current value vs forecast
interval), tail probability, and calibrated risk probability.

Emits the same ``workbench.ml_signal.v1`` shape as :mod:`ml.regime_detector`
and :mod:`ml.tft_regime_detector`, with
``method: gluonts_seasonal_naive_regime`` (or
``numpy_quantile_regime_fallback`` when GluonTS is unavailable).

**Regime redefinition (vs HMM/TFT)**
Instead of a hard classification into compression/volatile/crisis, this
module outputs:

- *forecast_intervals*: 50%/80%/95% prediction intervals for each horizon step
- *tail_probability*: probability that the current value lies in the forecast
  distribution's lower/upper tail
- *calibrated_risk_probability*: probability of crossing a user-defined
  threshold within the forecast horizon (computed from sample paths)
- *regime.current* / *regime.probability* / *regime.state_probs*: softmax
  mapping from tail/risk probabilities into the 3-regime lexicon for
  backward-compatible consumers

**Isolation contract (identical to HMM/TFT)**
- Reads only the frozen Harvester evidence panel path supplied at call time.
- Writes only to Output/state/ml_signals/ via ml_signal_writer.write_signal().
- Never modifies Data/ or any Harvester release artifact.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import numpy as np

_STATE_LABELS = ["compression", "volatile", "crisis"]
_GLUONTS_AVAILABLE: bool | None = None


def _check_gluonts() -> bool:
    global _GLUONTS_AVAILABLE
    if _GLUONTS_AVAILABLE is None:
        try:
            import gluonts  # noqa: F401
            from gluonts.dataset.pandas import PandasDataset  # noqa: F401
            from gluonts.model.seasonal_naive import SeasonalNaivePredictor  # noqa: F401

            _GLUONTS_AVAILABLE = True
        except Exception:
            _GLUONTS_AVAILABLE = False
    return _GLUONTS_AVAILABLE


# ---------------------------------------------------------------------------
# Fallback: numpy-only quantile-based regime classifier
# ---------------------------------------------------------------------------


def _numpy_fallback_probs(
    feats: np.ndarray, target_col_idx: int = 0
) -> dict[str, Any]:
    """Rolling quantile-breach heuristic matching the 3-regime lexicon."""
    if feats.ndim != 2 or feats.shape[0] < 20:
        p = np.ones(3) / 3.0
        return {
            "state_probs": {lbl: round(float(p[i]), 6) for i, lbl in enumerate(_STATE_LABELS)},
            "current": "volatile",
            "probability": round(float(p[1]), 6),
            "tail_probability_lower": None,
            "tail_probability_upper": None,
            "calibrated_risk_probability": None,
            "method": "numpy_quantile_regime_fallback",
        }

    series = feats[:, target_col_idx]
    lookback = min(60, len(series))
    recent = series[-lookback:]
    cur = float(series[-1])

    p25 = float(np.percentile(recent, 25))
    p75 = float(np.percentile(recent, 75))
    iqr = p75 - p25 + 1e-9

    tail_lower = 0.0 if cur >= p25 else float(np.clip((p25 - cur) / (iqr * 2), 0, 1))
    tail_upper = 0.0 if cur <= p75 else float(np.clip((cur - p75) / (iqr * 2), 0, 1))

    # Map to regime lexicon: low tail → compression, mixed → volatile, high tail → crisis
    crisis_prob = float(np.clip(tail_lower + tail_upper * 0.5, 0, 1))
    compression_prob = float(np.clip(1.0 - tail_lower - tail_upper * 0.3, 0, 1))
    volatile_prob = float(np.clip(1.0 - crisis_prob - compression_prob, 0, 1))
    total = crisis_prob + volatile_prob + compression_prob
    probs = np.array([compression_prob, volatile_prob, crisis_prob]) / (total + 1e-9)
    current_idx = int(np.argmax(probs))

    return {
        "state_probs": {lbl: round(float(probs[i]), 6) for i, lbl in enumerate(_STATE_LABELS)},
        "current": _STATE_LABELS[current_idx],
        "probability": round(float(probs[current_idx]), 6),
        "tail_probability_lower": round(tail_lower, 6),
        "tail_probability_upper": round(tail_upper, 6),
        "calibrated_risk_probability": round(float(crisis_prob), 6),
        "method": "numpy_quantile_regime_fallback",
    }


# ---------------------------------------------------------------------------
# GluonTS SeasonalNaive forecast → regime probabilities
# ---------------------------------------------------------------------------


def _season_length_for_freq(freq: str) -> int:
    normalized = freq.strip().upper()
    if normalized.startswith("B") or normalized.startswith("D"):
        return 7
    if normalized.startswith("W"):
        return 52
    if normalized.startswith("M"):
        return 12
    if normalized.startswith("Q"):
        return 4
    return 1


def _residual_bootstrap_samples(
    history: np.ndarray,
    baseline: np.ndarray,
    *,
    season_length: int,
    num_samples: int,
) -> np.ndarray:
    """Turn deterministic SeasonalNaive forecasts into empirical sample paths."""
    if len(history) > season_length:
        residuals = history[season_length:] - history[:-season_length]
    else:
        residuals = history - float(np.mean(history))
    residuals = residuals[np.isfinite(residuals)]
    if residuals.size == 0 or float(np.std(residuals)) == 0.0:
        scale = float(np.std(history)) or 1e-6
        residuals = np.array([-scale, 0.0, scale], dtype=float)

    rng = np.random.default_rng(7)
    noise = rng.choice(residuals, size=(num_samples, len(baseline)), replace=True)
    return cast(np.ndarray, np.asarray(baseline.reshape(1, -1) + noise, dtype=float))


def _gluonts_forecast_regime(
    panel: Any,
    target_col: str,
    freq: str = "D",
    prediction_length: int = 30,
    context_length: int = 252,
    num_samples: int = 200,
) -> dict[str, Any]:
    """Run SeasonalNaive on a single target series, compute tail/risk probabilities."""
    import pandas as pd
    from gluonts.dataset.pandas import PandasDataset
    from gluonts.model.seasonal_naive import SeasonalNaivePredictor

    df = pd.DataFrame({"date": pd.to_datetime(panel["date"]), "value": panel[target_col].astype(float)})
    df = df.dropna(subset=["value"]).sort_values("date").set_index("date")
    if len(df) < max(20, prediction_length + 2):
        return _numpy_fallback_probs(panel.select_dtypes(include=[np.number]).to_numpy(dtype=float))

    gts = PandasDataset(
        df,
        target="value",
        freq=freq,
    )

    season_length = max(1, min(_season_length_for_freq(freq), len(df) - 1))
    predictor = SeasonalNaivePredictor(
        prediction_length=prediction_length,
        season_length=season_length,
    )

    forecast_it = predictor.predict(gts)
    forecast = next(iter(forecast_it), None)
    if forecast is None:
        return _numpy_fallback_probs(panel.select_dtypes(include=[np.number]).to_numpy(dtype=float))

    baseline = np.asarray(forecast.mean, dtype=float)
    if baseline.ndim != 1 or baseline.size == 0:
        return _numpy_fallback_probs(panel.select_dtypes(include=[np.number]).to_numpy(dtype=float))
    samples = _residual_bootstrap_samples(
        df["value"].to_numpy(dtype=float),
        baseline,
        season_length=season_length,
        num_samples=num_samples,
    )

    current_val = float(df["value"].iloc[-1])

    # Forecast intervals at each horizon step
    intervals: dict[str, dict[str, list[float]]] = {}
    for pct in [50, 80, 95]:
        low = np.percentile(samples, (100 - pct) / 2, axis=0).tolist()
        high = np.percentile(samples, 100 - (100 - pct) / 2, axis=0).tolist()
        intervals[f"{pct}pct"] = {"lower": low, "upper": high}

    # Tail probability: fraction of sample paths where step-1 value is more extreme than current
    step1 = samples[:, 0]
    tail_lower = float(np.mean(step1 < current_val)) if current_val < np.median(step1) else 0.0
    tail_upper = float(np.mean(step1 > current_val)) if current_val > np.median(step1) else 0.0

    # Calibrated risk: probability of crossing a crisis threshold within horizon
    # Crisis threshold = 2.5 std below mean of sample paths (approximating tail event)
    crisis_threshold = float(np.mean(samples) - 2.5 * np.std(samples))
    breach_paths = np.any(samples <= crisis_threshold, axis=1)
    calibrated_risk = float(np.mean(breach_paths)) if crisis_threshold < current_val else 0.5

    # Map to 3-regime lexicon
    crisis_prob = float(np.clip(tail_lower + tail_upper * 0.5 + calibrated_risk * 0.3, 0, 1))
    compression_prob = float(np.clip(1.0 - tail_lower - tail_upper * 0.3 - calibrated_risk * 0.2, 0, 1))
    volatile_prob = float(np.clip(1.0 - crisis_prob - compression_prob, 0, 1))
    total = crisis_prob + volatile_prob + compression_prob + 1e-9
    probs = np.array([compression_prob, volatile_prob, crisis_prob]) / total
    current_idx = int(np.argmax(probs))

    return {
        "state_probs": {lbl: round(float(probs[i]), 6) for i, lbl in enumerate(_STATE_LABELS)},
        "current": _STATE_LABELS[current_idx],
        "probability": round(float(probs[current_idx]), 6),
        "forecast_intervals": intervals,
        "tail_probability_lower": round(tail_lower, 6),
        "tail_probability_upper": round(tail_upper, 6),
        "calibrated_risk_probability": round(calibrated_risk, 6),
        "method": "gluonts_seasonal_naive_regime",
    }


# ---------------------------------------------------------------------------
# Main entry point (same signature as detect_regime / detect_regime_tft)
# ---------------------------------------------------------------------------


def detect_regime_gluonts(
    panel_path: Path,
    source_release: str,
    source_created_at: str,
    *,
    target_col: str = "value",
    freq: str = "D",
    prediction_length: int = 30,
    context_length: int = 252,
    output_root: Path | None = None,
    feature_cols: list[str] | None = None,
    write: bool = True,
) -> dict[str, Any]:
    """Emit a probabilistic regime signal via GluonTS SeasonalNaive forecast.

    Falls back to numpy quantile heuristic when gluonts is unavailable
    or training fails.
    """
    import pandas as pd

    if panel_path.suffix.lower() == ".parquet":
        panel = pd.read_parquet(panel_path)
    else:
        panel = pd.read_csv(panel_path, low_memory=False)

    # Auto-select target column: prefer value, then first numeric column
    cols = panel.select_dtypes(include=[np.number]).columns.tolist()
    if target_col == "value" and "value" not in cols and cols:
        target_col = cols[0]
    if target_col not in cols:
        if cols:
            target_col = cols[0]
        else:
            raise ValueError("No numeric columns found in panel; cannot run GluonTS forecaster.")

    used_cols: list[str] = [target_col] if feature_cols is None else feature_cols

    # Date range
    date_range: dict[str, str] = {}
    if "date" in panel.columns:
        dates = pd.to_datetime(panel["date"], errors="coerce").dropna()
        if not dates.empty:
            date_range = {"start": str(dates.min().date()), "end": str(dates.max().date())}

    min_forecast_rows = max(20, prediction_length + 2)
    if _check_gluonts() and len(panel) >= min_forecast_rows:
        try:
            regime_result = _gluonts_forecast_regime(
                panel,
                target_col=target_col,
                freq=freq,
                prediction_length=prediction_length,
                context_length=context_length,
            )
        except Exception:
            feats = panel.select_dtypes(include=[np.number]).to_numpy(dtype=float)
            regime_result = _numpy_fallback_probs(feats)
    else:
        feats = panel.select_dtypes(include=[np.number]).to_numpy(dtype=float)
        regime_result = _numpy_fallback_probs(feats)

    payload: dict[str, Any] = {
        "schema_version": "workbench.ml_signal.v1",
        "signal_type": "regime",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source_release": source_release,
        "method": regime_result.pop("method"),
        "regime": {
            "current": regime_result.pop("current"),
            "probability": regime_result.pop("probability"),
            "state_probs": regime_result.pop("state_probs"),
        },
        "freshness_gate": {
            "source_created_at": source_created_at,
            "signal_valid": True,
            "stale_if_release_changes": True,
        },
        "provenance": {
            "input_panel_path": str(panel_path),
            "input_row_count": len(panel),
            "input_date_range": date_range,
            "feature_columns": used_cols,
            "target_column": target_col,
            "forecast_freq": freq,
            "prediction_length": prediction_length,
            "gluonts_backend": "gluonts_seasonal_naive" if _check_gluonts() else "numpy_fallback",
        },
    }

    # Attach GluonTS-specific probability fields (only when meaningful)
    for extra_key in (
        "forecast_intervals",
        "tail_probability_lower",
        "tail_probability_upper",
        "calibrated_risk_probability",
    ):
        val = regime_result.get(extra_key)
        if val is not None:
            payload[extra_key] = val

    if write:
        from ml.ml_signal_writer import write_signal

        write_signal(payload, output_root=output_root, artifact_basename="regime_gluonts")

    return payload


def attach_conformal_to_payload(payload: dict[str, Any], *, alpha: float = 0.10) -> dict[str, Any]:
    """Merge conformal summary from :mod:`ml.conformal_wrapper` into *payload*."""
    from ml.conformal_wrapper import conformal_regime_sets

    out = dict(payload)
    reg = out.get("regime", {})
    probs = dict(reg.get("state_probs") or {})
    conf = conformal_regime_sets(probs, alpha=alpha)
    out["conformal"] = conf
    prov = dict(out.get("provenance") or {})
    prov["conformal"] = conf
    out["provenance"] = prov
    return out
