"""PCA-based factor model for the Workbench ML layer.

Reads a frozen Harvester evidence panel, decomposes into principal factors,
and emits a workbench.ml_signal.v1 JSON (signal_type='factor') via
ml_signal_writer.

sklearn.decomposition.PCA is used when available; numpy SVD otherwise.

Isolation:
  - Reads only from the frozen Harvester export path supplied at call time.
  - Writes only to Output/state/ml_signals/ via ml_signal_writer.write_signal().
  - Never modifies Data/ or any Harvester release artifact.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

_FACTOR_LABELS = [
    "credit_spread",
    "liquidity",
    "volatility_regime",
    "term_structure",
    "risk_appetite",
]


# ---------------------------------------------------------------------------
# Feature extraction (shared with regime_detector logic)
# ---------------------------------------------------------------------------

def _build_feature_matrix(
    panel: Any,
    feature_cols: list[str] | None = None,
) -> tuple[np.ndarray, list[str]]:
    numeric = panel.select_dtypes(include=[np.number])
    if feature_cols:
        cols = [c for c in feature_cols if c in numeric.columns]
    else:
        exclude = {"date", "series_id", "source_id", "source_series_id",
                   "quality_flag", "vintage_date", "frequency"}
        cols = [c for c in numeric.columns if c not in exclude]
    if not cols:
        raise ValueError("No numeric feature columns found in evidence panel.")
    mat = numeric[cols].ffill().bfill().fillna(0.0).values
    return mat, cols


# ---------------------------------------------------------------------------
# PCA
# ---------------------------------------------------------------------------

def _fit_sklearn_pca(X: np.ndarray, n_components: int):
    from sklearn.decomposition import PCA  # type: ignore
    pca = PCA(n_components=n_components, random_state=42)
    scores = pca.fit_transform(X)
    loadings = pca.components_
    explained = pca.explained_variance_ratio_
    return scores, loadings, explained


def _fit_numpy_pca(X: np.ndarray, n_components: int):
    centered = X - X.mean(axis=0)
    _, s, Vt = np.linalg.svd(centered, full_matrices=False)
    scores = centered @ Vt[:n_components].T
    loadings = Vt[:n_components]
    var = s[:n_components] ** 2 / (len(X) - 1)
    explained = var / (var.sum() + 1e-300)
    return scores, loadings, explained


def _label_factor(idx: int) -> str:
    if idx < len(_FACTOR_LABELS):
        return _FACTOR_LABELS[idx]
    return f"factor_{idx + 1}"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def extract_factors(
    panel_path: Path,
    source_release: str,
    source_created_at: str,
    *,
    n_components: int = 5,
    output_root: Path | None = None,
    feature_cols: list[str] | None = None,
    write: bool = True,
) -> dict[str, Any]:
    """Run PCA, emit factor signal JSON.

    Returns the signal payload dict. Writes to Output/state/ml_signals/ if write=True.
    """
    import pandas as pd

    if panel_path.suffix.lower() == ".parquet":
        panel = pd.read_parquet(panel_path)
    else:
        panel = pd.read_csv(panel_path, low_memory=False)

    X, used_cols = _build_feature_matrix(panel, feature_cols)
    n_comp = min(n_components, X.shape[1], X.shape[0] - 1)

    try:
        scores, loadings, explained = _fit_sklearn_pca(X, n_comp)
        method = f"pca_{n_comp}_sklearn"
    except Exception:
        scores, loadings, explained = _fit_numpy_pca(X, n_comp)
        method = f"pca_{n_comp}_numpy"

    # Latest observation scores
    latest_scores = scores[-1] if len(scores) > 0 else scores[0]
    factors = []
    for i in range(n_comp):
        factors.append({
            "id": f"pc{i + 1}",
            "label": _label_factor(i),
            "score": round(float(latest_scores[i]), 6),
            "loading": round(float(explained[i]), 6),
        })

    date_range: dict[str, str] = {}
    if "date" in panel.columns:
        dates = pd.to_datetime(panel["date"], errors="coerce").dropna()
        if not dates.empty:
            date_range = {
                "start": str(dates.min().date()),
                "end": str(dates.max().date()),
            }

    payload: dict[str, Any] = {
        "schema_version": "workbench.ml_signal.v1",
        "signal_type": "factor",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source_release": source_release,
        "method": method,
        "factors": factors,
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
        },
    }

    if write:
        from ml.ml_signal_writer import write_signal
        write_signal(payload, output_root=output_root)

    return payload
