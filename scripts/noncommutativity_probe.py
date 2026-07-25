#!/usr/bin/env python3
"""Preregistered T4 threshold-VAR impulse-order comparison (research only)."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/system-t4-matplotlib")
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PANEL = ROOT / "Output/sandbox/structural_replay_v2/all_signals.parquet"
DEFAULT_OUTPUT = ROOT / "Output/validation/noncommutativity_probe"
DEFAULT_PROTOCOL = ROOT / "governance/routing_decisions/2026-07-18-t4-noncommutativity-protocol.yaml"
VARIABLES = ("channel_M", "channel_K")
TRAIN_START = "2000-01-01"
TRAIN_END = "2019-08-31"
EVENTS = {
    "repo_2019": ("2019-09-16", "2019-09-20"),
    "treasury_2020": ("2020-03-09", "2020-03-23"),
}
HORIZON = 20
BOOTSTRAPS = 500
SEED = 20260718


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class TVAR:
    low: np.ndarray
    high: np.ndarray
    threshold: float
    mean: np.ndarray
    scale: np.ndarray


def design(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    levels = (
        frame.loc[TRAIN_START:TRAIN_END, list(VARIABLES)]
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
        .astype(float)
    )
    changes = levels.diff().dropna()
    lagged = changes.shift(1).dropna()
    response = changes.loc[lagged.index].to_numpy()
    x = np.column_stack([np.ones(len(lagged)), lagged.to_numpy()])
    mean = levels.mean().to_numpy()
    scale = levels.std(ddof=0).replace(0.0, 1.0).to_numpy()
    regime_score = ((levels.shift(1).loc[lagged.index].to_numpy() - mean) / scale).max(axis=1)
    return x, response, regime_score, mean, scale


def fit_regime(x: np.ndarray, y: np.ndarray, ridge: float = 1e-8) -> np.ndarray:
    if not (np.isfinite(x).all() and np.isfinite(y).all()):
        raise ValueError("non-finite threshold-VAR design")
    penalty = np.eye(x.shape[1]) * np.sqrt(ridge)
    penalty[0, 0] = 0.0
    augmented_x = np.vstack([x, penalty])
    augmented_y = np.vstack([y, np.zeros((x.shape[1], y.shape[1]))])
    coefficients = np.linalg.lstsq(augmented_x, augmented_y, rcond=None)[0].T
    if not np.isfinite(coefficients).all():
        raise ValueError("non-finite threshold-VAR coefficients")
    return coefficients


def fit_tvar(frame: pd.DataFrame, sample_indices: tuple[np.ndarray, np.ndarray] | None = None) -> tuple[TVAR, dict[str, np.ndarray]]:
    x, y, score, mean, scale = design(frame)
    threshold = float(np.quantile(score, 0.75))
    low_idx = np.flatnonzero(score <= threshold)
    high_idx = np.flatnonzero(score > threshold)
    if sample_indices is not None:
        low_idx, high_idx = sample_indices
    if len(low_idx) < 30 or len(high_idx) < 30:
        raise ValueError("insufficient observations in a threshold regime")
    model = TVAR(
        low=fit_regime(x[low_idx], y[low_idx]),
        high=fit_regime(x[high_idx], y[high_idx]),
        threshold=threshold,
        mean=mean,
        scale=scale,
    )
    return model, {"x": x, "y": y, "score": score, "low_idx": low_idx, "high_idx": high_idx}


def event_impulses(frame: pd.DataFrame, start: str, end: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    levels = frame[list(VARIABLES)].replace([np.inf, -np.inf], np.nan).dropna().astype(float)
    window = levels.loc[start:end]
    if len(window) < 2:
        raise ValueError(f"event window {start}:{end} has fewer than two observations")
    changes = window.diff().dropna()
    magnitudes = []
    for column in VARIABLES:
        positive = changes[column][changes[column] > 0]
        magnitude = float(positive.max()) if len(positive) else float(changes[column].abs().max())
        magnitudes.append(magnitude)
    initial = levels.loc[:start].iloc[-1].to_numpy()
    return initial, np.array([magnitudes[0], 0.0]), np.array([0.0, magnitudes[1]])


def simulate(model: TVAR, initial: np.ndarray, first: np.ndarray, second: np.ndarray, horizon: int = HORIZON) -> np.ndarray:
    level = initial.astype(float).copy()
    delta = np.zeros(2, dtype=float)
    path = []
    for step in range(horizon):
        score = float(np.max((level - model.mean) / model.scale))
        coefficients = model.high if score > model.threshold else model.low
        delta = coefficients[:, 0] + coefficients[:, 1:] @ delta
        if step == 0:
            delta = delta + first
        elif step == 1:
            delta = delta + second
        level = level + delta
        if not (np.isfinite(level).all() and np.isfinite(delta).all()):
            raise ValueError("non-finite simulated path")
        path.append(level.copy())
    return np.asarray(path)


def order_result(model: TVAR, initial: np.ndarray, m_impulse: np.ndarray, k_impulse: np.ndarray) -> tuple[float, np.ndarray, np.ndarray]:
    mk = simulate(model, initial, m_impulse, k_impulse)
    km = simulate(model, initial, k_impulse, m_impulse)
    distance = float(np.sqrt(np.mean(np.sum((mk - km) ** 2, axis=1))))
    return distance, mk, km


def bootstrap(frame: pd.DataFrame, event_inputs: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]], reps: int, seed: int) -> np.ndarray:
    _, arrays = fit_tvar(frame)
    rng = np.random.default_rng(seed)
    differences = np.empty(reps, dtype=float)
    for i in range(reps):
        low = rng.choice(arrays["low_idx"], size=len(arrays["low_idx"]), replace=True)
        high = rng.choice(arrays["high_idx"], size=len(arrays["high_idx"]), replace=True)
        fitted, _ = fit_tvar(frame, (low, high))
        values = {}
        for name, (initial, m_impulse, k_impulse) in event_inputs.items():
            values[name] = order_result(fitted, initial, m_impulse, k_impulse)[0]
        differences[i] = values["treasury_2020"] - values["repo_2019"]
    return differences


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--bootstrap-reps", type=int, default=BOOTSTRAPS)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.protocol.is_file():
        raise SystemExit(f"frozen protocol missing: {args.protocol}")
    frame = pd.read_parquet(args.panel).sort_index()
    model, arrays = fit_tvar(frame)
    event_inputs = {name: event_impulses(frame, *window) for name, window in EVENTS.items()}
    rows = []
    distances = {}
    paths = {}
    for name, inputs in event_inputs.items():
        distance, mk, km = order_result(model, *inputs)
        distances[name] = distance
        paths[name] = (mk, km)
        for step in range(HORIZON):
            rows.append({
                "event": name,
                "step": step + 1,
                "mk_M": mk[step, 0], "mk_K": mk[step, 1],
                "km_M": km[step, 0], "km_K": km[step, 1],
            })
    draws = bootstrap(frame, event_inputs, args.bootstrap_reps, SEED)
    primary = distances["treasury_2020"] - distances["repo_2019"]
    p_value = float(np.mean(draws <= 0.0))
    verdict = "SUPPORTED" if primary > 0.0 and p_value < 0.05 else "NOT_SUPPORTED"
    args.output.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(args.output / "order_paths.csv", index=False)
    pd.DataFrame({"delta_2020_minus_2019": draws}).to_csv(args.output / "bootstrap.csv", index=False)
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2), sharex=True)
    for axis, name in zip(axes, EVENTS):
        mk, km = paths[name]
        axis.plot(np.arange(1, HORIZON + 1), np.linalg.norm(mk, axis=1), label="M then K")
        axis.plot(np.arange(1, HORIZON + 1), np.linalg.norm(km, axis=1), label="K then M", linestyle="--")
        axis.set_title(f"{name}: Delta_NC={distances[name]:.4f}")
        axis.set_xlabel("simulation day")
        axis.grid(alpha=0.2)
    axes[0].set_ylabel("simulated state norm")
    axes[1].legend(frameon=False)
    fig.tight_layout()
    fig.savefig(args.output / "order_paths.png", dpi=220)
    plt.close(fig)
    result = {
        "schema_version": "t4.noncommutativity_verdict.v1",
        "status": verdict,
        "research_only": True,
        "panel_sha256": sha256(args.panel),
        "protocol_sha256": sha256(args.protocol),
        "train_window": [TRAIN_START, TRAIN_END],
        "variables": list(VARIABLES),
        "regime_threshold": model.threshold,
        "regime_counts": {"low": int(len(arrays["low_idx"])), "high": int(len(arrays["high_idx"]))},
        "horizon_days": HORIZON,
        "bootstrap_reps": args.bootstrap_reps,
        "seed": SEED,
        "delta_nc": distances,
        "primary_difference": primary,
        "bootstrap_ci_95": [float(np.quantile(draws, 0.025)), float(np.quantile(draws, 0.975))],
        "one_sided_p_value": p_value,
        "paper_wording": (
            "The preregistered prototype supports greater impulse-order dependence in March 2020 than September 2019."
            if verdict == "SUPPORTED" else
            "The preregistered prototype does not support greater impulse-order dependence in March 2020; non-commutativity remains an open question."
        ),
    }
    (args.output / "verdict.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
