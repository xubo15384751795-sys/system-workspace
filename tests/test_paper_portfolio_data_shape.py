from __future__ import annotations

import pandas as pd
import pytest

from scripts.strategy_lab.paper_portfolio import _deduplicate_datetime_index, _scalar_at


def test_paper_boundary_deduplicates_daily_index_before_scalar_lookup() -> None:
    index = pd.to_datetime(["2026-08-18", "2026-08-18"])
    series = pd.Series([0.25, 0.50], index=index)

    deduped = _deduplicate_datetime_index(series)

    assert deduped.index.is_unique
    assert _scalar_at(deduped, pd.Timestamp("2026-08-18"), name="overlay") == 0.50


def test_scalar_lookup_reports_duplicate_shape_if_called_without_guard() -> None:
    index = pd.to_datetime(["2026-08-18", "2026-08-18"])
    series = pd.Series([0.25, 0.50], index=index)

    with pytest.raises(ValueError, match="non-unique decision index"):
        _scalar_at(series, pd.Timestamp("2026-08-18"), name="overlay")
