"""Provider parity and source-drift checks for normalized observations."""
from __future__ import annotations

from typing import Any, Mapping

import pandas as pd


def compare_source_signatures(
    previous: Mapping[str, Mapping[str, Any]],
    current: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Report per-series source/normalization changes without hiding them."""
    changed: dict[str, dict[str, Any]] = {}
    for series in sorted(set(previous) | set(current)):
        before = dict(previous.get(series, {}))
        after = dict(current.get(series, {}))
        fields = {
            field: {"previous": before.get(field), "current": after.get(field)}
            for field in ("provider", "normalization_profile", "adjusted", "timestamp_basis")
            if before.get(field) != after.get(field)
        }
        if fields:
            changed[str(series)] = fields
    return {
        "status": "SOURCE_DRIFT" if changed else "PARITY",
        "changed_series": changed,
        "checked_series": len(set(previous) | set(current)),
    }


def compare_normalized_frames(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    key: tuple[str, ...] = ("date",),
    value_columns: tuple[str, ...] = ("value", "close", "open", "high", "low", "volume"),
    rtol: float = 1e-6,
    atol: float = 1e-8,
) -> dict[str, Any]:
    """Compare overlapping normalized provider rows with explicit shape checks."""
    required = set(key)
    if not required.issubset(left.columns) or not required.issubset(right.columns):
        return {"status": "SCHEMA_CHANGED", "reason": "comparison_key_missing"}
    common_values = [column for column in value_columns if column in left.columns and column in right.columns]
    if not common_values:
        return {"status": "SCHEMA_CHANGED", "reason": "no_common_value_columns"}
    left_keys = left.duplicated(list(key), keep=False)
    right_keys = right.duplicated(list(key), keep=False)
    if bool(left_keys.any()) or bool(right_keys.any()):
        return {
            "status": "SCHEMA_CHANGED",
            "reason": "non_unique_comparison_key",
            "left_duplicate_rows": int(left_keys.sum()),
            "right_duplicate_rows": int(right_keys.sum()),
        }
    merged = left[list(key) + common_values].merge(
        right[list(key) + common_values],
        on=list(key),
        how="inner",
        suffixes=("_left", "_right"),
    )
    if merged.empty:
        return {"status": "NO_OVERLAP", "overlap_rows": 0}
    mismatches: dict[str, int] = {}
    for column in common_values:
        lvalue = pd.to_numeric(merged[f"{column}_left"], errors="coerce")
        rvalue = pd.to_numeric(merged[f"{column}_right"], errors="coerce")
        equal = (lvalue.isna() & rvalue.isna()) | (
            lvalue.notna() & rvalue.notna() & pd.Series(
                (lvalue.to_numpy() - rvalue.to_numpy()).__abs__()
                <= atol + rtol * rvalue.abs().to_numpy(),
                index=merged.index,
            )
        )
        if not bool(equal.all()):
            mismatches[column] = int((~equal).sum())
    return {
        "status": "SOURCE_DRIFT" if mismatches else "PARITY",
        "overlap_rows": int(len(merged)),
        "mismatches": mismatches,
        "rtol": float(rtol),
        "atol": float(atol),
    }


__all__ = ["compare_normalized_frames", "compare_source_signatures"]
