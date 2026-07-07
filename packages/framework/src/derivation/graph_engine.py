from __future__ import annotations

import numpy as np
import pandas as pd


PROXY_COLUMNS = ["M", "D", "K", "X"]


class GraphEngine:
    """
    Lightweight graph derivation helper for UI exploration.
    This keeps graph-oriented transformations in derivation layer.
    """

    def proxy_corr(self, history: pd.DataFrame) -> pd.DataFrame:
        if history.empty:
            return pd.DataFrame(columns=PROXY_COLUMNS, index=PROXY_COLUMNS)
        cols = [c for c in PROXY_COLUMNS if c in history.columns]
        if not cols:
            return pd.DataFrame(columns=PROXY_COLUMNS, index=PROXY_COLUMNS)
        corr = history[cols].corr()
        return corr.reindex(index=PROXY_COLUMNS, columns=PROXY_COLUMNS)

    def coupling_bands(self, history: pd.DataFrame) -> pd.DataFrame:
        corr = self.proxy_corr(history)
        bands = corr.apply(lambda column: column.map(coupling_band))
        for proxy in PROXY_COLUMNS:
            if proxy in bands.index and proxy in bands.columns:
                bands.loc[proxy, proxy] = "Self"
        return bands

    def coupling_codes(self, history: pd.DataFrame) -> pd.DataFrame:
        bands = self.coupling_bands(history)
        return bands.apply(lambda column: column.map(coupling_code))


COUPLING_BAND_CODES: dict[str, int] = {
    "Inverse Coupling": -2,
    "Tension": -1,
    "Decoupled": 0,
    "Coupled": 1,
    "Synchronized": 2,
    "Self": 0,
}


COUPLING_BAND_MEANINGS: dict[str, str] = {
    "Inverse Coupling": "Channels move in strong opposition.",
    "Tension": "Opposing movement is present but not dominant.",
    "Decoupled": "No stable structural relation is active in this window.",
    "Coupled": "Channels move together enough to monitor.",
    "Synchronized": "Strong co-movement suggests possible regime compression.",
    "Self": "Reference channel.",
}


def coupling_code(label: str) -> int:
    return COUPLING_BAND_CODES.get(label, 0)


def coupling_band(value: float | None) -> str:
    if value is None or not np.isfinite(value):
        return "Decoupled"
    if value <= -0.65:
        return "Inverse Coupling"
    if value <= -0.25:
        return "Tension"
    if value < 0.25:
        return "Decoupled"
    if value < 0.65:
        return "Coupled"
    return "Synchronized"
