from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.validation.unconditional_evaluator import evaluate_binary_signal, metrics_to_dict


@dataclass(frozen=True)
class WalkForwardConfig:
    train_window: int = 252
    test_window: int = 63
    threshold_quantile: float = 0.8
    min_train: int = 126


def rolling_origin_oos_validate(
    signal: pd.Series,
    target: pd.Series,
    config: WalkForwardConfig = WalkForwardConfig(),
) -> pd.DataFrame:
    if not assert_no_future_index_leakage(signal, target):
        raise ValueError("future index leakage guard failed for walk-forward inputs")
    aligned = pd.concat([signal.rename("signal"), target.rename("target")], axis=1).dropna()
    rows: list[dict[str, object]] = []
    start = config.min_train
    while start < len(aligned):
        train_start = max(0, start - config.train_window)
        train = aligned.iloc[train_start:start]
        test = aligned.iloc[start : start + config.test_window]
        if train.empty or test.empty:
            break
        threshold = float(train["signal"].quantile(config.threshold_quantile))
        metrics = evaluate_binary_signal(test["signal"], test["target"].astype(bool), threshold)
        rows.append(
            {
                "train_start": train.index[0],
                "train_end": train.index[-1],
                "test_start": test.index[0],
                "test_end": test.index[-1],
                "threshold": threshold,
                **metrics_to_dict(metrics),
            }
        )
        start += config.test_window
    return pd.DataFrame.from_records(rows)


def assert_no_future_index_leakage(signal: pd.Series, target: pd.Series) -> bool:
    if signal.index.empty or target.index.empty:
        return True
    signal_index = pd.DatetimeIndex(signal.index)
    target_index = pd.DatetimeIndex(target.index)
    return bool(
        signal_index.is_monotonic_increasing
        and target_index.is_monotonic_increasing
        and signal_index.min() <= target_index.min()
    )


def thresholds_shift_by_origin(results: pd.DataFrame) -> bool:
    if results.empty or "threshold" not in results:
        return False
    return bool(np.nanstd(pd.to_numeric(results["threshold"], errors="coerce")) > 0.0)
