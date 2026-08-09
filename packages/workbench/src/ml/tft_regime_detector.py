"""Parallel regime signal using a lightweight temporal forecaster-style head.

Full Temporal Fusion Transformer training is optional (``pytorch-forecasting``).
When unavailable, this module falls back to a **numpy-only** multi-horizon
momentum/volatility classifier that emits the same ``workbench.ml_signal.v1``
shape as :mod:`ml.regime_detector` with ``method: tft_regime`` (or
``tft_regime_numpy_fallback`` when the heavy stack is missing).

Reads only the frozen Harvester evidence panel path supplied at call time.
Writes via :func:`ml.ml_signal_writer.write_signal` to ``regime_tft.json``.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

_STATE_LABELS = ["compression", "volatile", "crisis"]


def _softmax(x: np.ndarray) -> np.ndarray:
    x = x - np.max(x)
    e = np.exp(x)
    return e / (e.sum() + 1e-9)


def _build_feature_matrix(panel: Any, feature_cols: list[str] | None = None) -> tuple[np.ndarray, list[str]]:

    numeric = panel.select_dtypes(include=[np.number])
    if feature_cols:
        cols = [c for c in feature_cols if c in numeric.columns]
    else:
        exclude = {"date", "series_id", "source_id", "source_series_id", "quality_flag", "vintage_date", "frequency"}
        cols = [c for c in numeric.columns if c not in exclude]
    if not cols:
        raise ValueError("No numeric feature columns found in evidence panel.")
    sub = numeric[cols].ffill().bfill().fillna(0.0)
    return sub.to_numpy(dtype=float), cols


def _numpy_tft_proxy_probs(feats: np.ndarray) -> tuple[np.ndarray, str]:
    """Return softmax logits over three regimes using rolling vol / drift heuristics."""
    if feats.ndim != 2 or feats.shape[0] < 8:
        p = np.ones(3) / 3.0
        return p, "tft_regime_numpy_fallback"

    # Use first principal component of recent window as a coarse macro factor
    w = min(252, feats.shape[0])
    tail = feats[-w:]
    tail = tail - tail.mean(axis=0, keepdims=True)
    if tail.shape[1] == 1:
        score = tail[:, 0]
    else:
        u, _, _ = np.linalg.svd(tail, full_matrices=False)
        score = u[:, 0] * np.sign(np.corrcoef(tail[:, 0], u[:, 0])[0, 1] or 1.0)

    ret = np.diff(score, prepend=score[0])
    vol = float(np.std(ret[-60:]) + 1e-9)
    mu = float(np.mean(ret[-60:]))
    vol_norm = vol / (np.std(score) + 1e-9)

    # Logits: compression = low vol stable; crisis = high vol + negative drift
    logits = np.array(
        [-vol_norm, abs(mu) - 0.5 * vol_norm, vol_norm - 0.8 * mu],
        dtype=float,
    )
    probs = _softmax(logits)
    # Map ordering roughly to compression / volatile / crisis
    return probs, "tft_regime_numpy_fallback"


def detect_regime_tft(
    panel_path: Path,
    source_release: str,
    source_created_at: str,
    model_path: Path | None = None,
    *,
    output_root: Path | None = None,
    feature_cols: list[str] | None = None,
    write: bool = True,
) -> dict[str, Any]:
    """Emit a regime signal JSON parallel to HMM (``regime_tft.json``)."""
    _ = model_path  # reserved for future torch checkpoint loading
    import pandas as pd

    if panel_path.suffix.lower() == ".parquet":
        panel = pd.read_parquet(panel_path)
    else:
        panel = pd.read_csv(panel_path, low_memory=False)

    feats, used_cols = _build_feature_matrix(panel, feature_cols)
    probs, method = _numpy_tft_proxy_probs(feats)

    current_idx = int(np.argmax(probs))
    current_label = _STATE_LABELS[current_idx]

    state_probs_by_label = {lbl: float(probs[i]) for i, lbl in enumerate(_STATE_LABELS)}
    total = sum(state_probs_by_label.values())
    if total > 0:
        state_probs_by_label = {k: round(v / total, 6) for k, v in state_probs_by_label.items()}

    date_range: dict[str, str] = {}
    if "date" in panel.columns:
        dates = pd.to_datetime(panel["date"], errors="coerce").dropna()
        if not dates.empty:
            date_range = {"start": str(dates.min().date()), "end": str(dates.max().date())}

    payload: dict[str, Any] = {
        "schema_version": "workbench.ml_signal.v1",
        "signal_type": "regime",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source_release": source_release,
        "method": method,
        "regime": {
            "current": current_label,
            "probability": state_probs_by_label[current_label],
            "state_probs": state_probs_by_label,
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
            "tft_backend": method,
        },
    }

    if write:
        from ml.ml_signal_writer import write_signal

        write_signal(payload, output_root=output_root, artifact_basename="regime_tft")

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
