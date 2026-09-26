"""Pure panel transformations owned by the Harvester normalization boundary."""
from __future__ import annotations

from typing import Any

import pandas as pd


def build_complete_benchmark_panel(
    acquired: pd.DataFrame,
    *,
    external_indicators: pd.DataFrame | None = None,
    derived_panel: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Combine acquired, external, and derived series into one panel."""
    pieces = [acquired]
    if external_indicators is not None and not external_indicators.empty:
        pieces.append(external_indicators)
    if derived_panel is not None and not derived_panel.empty:
        pieces.append(derived_panel)
    if len(pieces) == 1:
        return normalize_release_panel(acquired)
    combined = pd.concat(pieces, ignore_index=True)
    combined = combined.sort_values(["series_id", "date"]).reset_index(drop=True)
    return normalize_release_panel(combined)


def normalize_release_panel(panel: pd.DataFrame) -> pd.DataFrame:
    """Normalize mixed acquired/derived panels before release serialization."""
    out = panel.copy()
    if "quality_flag" in out:
        out["quality_flag"] = out["quality_flag"].map(_quality_flag_label).astype("string")
    for column in (
        "series_id",
        "source_id",
        "source_series_id",
        "unit",
        "frequency",
        "vintage_date",
    ):
        if column in out:
            out[column] = out[column].astype(str)
    if "value" in out:
        out["value"] = pd.to_numeric(out["value"], errors="coerce")
    if "date" in out:
        out["date"] = pd.to_datetime(out["date"], errors="coerce")
    return out


def _quality_flag_label(value: Any) -> str:
    if value in {0, "0", "ok"}:
        return "observed"
    if value in {1, "1"}:
        return "fallback"
    if value in {2, "2"}:
        return "error"
    if value in {None, ""}:
        return "unknown"
    return str(value)


def build_proxy_candidate_panel(
    derived_panel: pd.DataFrame,
    *,
    acquired: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build the non-authoritative proxy candidate panel."""
    del acquired  # retained for compatibility with older callers
    from harvester.core.proxy_measurement import PROXY_SERIES_IDS

    candidates = derived_panel[
        derived_panel["source_series_id"].isin(PROXY_SERIES_IDS)
    ].copy()
    return candidates.sort_values(["series_id", "date"]).reset_index(drop=True)


__all__ = [
    "build_complete_benchmark_panel",
    "build_proxy_candidate_panel",
    "normalize_release_panel",
]
