"""Pandera-owned table shape and null checks.

This module deliberately contains no calendar, trading-session, provider
availability, or revision logic.  The content-clock evaluator is in
``content_freshness``; this file remains the compatibility import surface for
older callers that imported that evaluator from here.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pandas as pd

try:
    import pandera.pandas as pa
except ImportError:  # pragma: no cover
    pa = None  # type: ignore[assignment]


def _read_table(path: Path) -> pd.DataFrame:
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


def validate_frame(frame: pd.DataFrame, date_column: str) -> list[str]:
    """Return Pandera/schema errors for the dated input frame."""
    if date_column not in frame.columns:
        return [f"missing_column:{date_column}"]

    if pa is None:
        return []

    schema = pa.DataFrameSchema(
        {date_column: pa.Column(nullable=False)},
        coerce=True,
        strict=False,
    )
    try:
        schema.validate(frame[[date_column]], lazy=True)
    except Exception as exc:  # noqa: BLE001 - return typed validation failure
        return [f"pandera:{exc}"]
    return []


def evaluate_content_clock(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Compatibility wrapper; canonical owner is ``content_freshness``."""
    from orchestration.quality.content_freshness import (
        evaluate_content_clock as evaluator,
    )

    return cast(dict[str, Any], evaluator(*args, **kwargs))


def evaluate_all_content_clocks(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    """Compatibility wrapper; canonical owner is ``content_freshness``."""
    from orchestration.quality.content_freshness import (
        evaluate_all_content_clocks as evaluator,
    )

    return cast(list[dict[str, Any]], evaluator(*args, **kwargs))
