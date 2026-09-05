from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd


def residualize_series(target: pd.Series, controls: Mapping[str, pd.Series]) -> pd.Series:
    """OLS residuals of target after projecting on available controls."""
    y = pd.to_numeric(target, errors="coerce").rename("__target__")
    if not controls:
        out = pd.Series(index=y.index, dtype=float, name=f"{target.name or 'target'}_resid")
        out.loc[y.dropna().index] = y.dropna()
        return out
    X = pd.concat({name: pd.to_numeric(series, errors="coerce") for name, series in controls.items()}, axis=1)
    frame = pd.concat([y, X], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    out = pd.Series(index=y.index, dtype=float, name=f"{target.name or 'target'}_resid")
    if frame.empty or X.empty:
        out.loc[y.dropna().index] = y.dropna()
        return out
    x = frame.drop(columns=["__target__"]).to_numpy(dtype=float)
    x = np.column_stack([np.ones(len(x)), x])
    beta, *_ = np.linalg.lstsq(x, frame["__target__"].to_numpy(dtype=float), rcond=None)
    out.loc[frame.index] = frame["__target__"].to_numpy(dtype=float) - x @ beta
    return out


def latest_residual_value(target: pd.Series, controls: Mapping[str, pd.Series]) -> float | None:
    resid = residualize_series(target, controls).dropna()
    if resid.empty:
        return None
    return float(resid.iloc[-1])


def zscore(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
    mean = values.expanding(min_periods=3).mean()
    std = values.expanding(min_periods=3).std(ddof=0).replace(0.0, np.nan)
    return ((values - mean) / std).replace([np.inf, -np.inf], np.nan)
