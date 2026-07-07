"""Tests for workbench.evidence_dashboard — pure helpers."""
from __future__ import annotations

import pandas as pd
import pytest

import workbench.evidence_dashboard as ed


# ---------------------------------------------------------------------------
# _fmt
# ---------------------------------------------------------------------------

class TestFmt:
    def test_none_returns_na(self):
        assert ed._fmt(None) == "n/a"

    def test_float_three_decimals(self):
        assert ed._fmt(1.23456) == "1.235"

    def test_zero_float(self):
        assert ed._fmt(0.0) == "0.000"

    def test_string_passthrough(self):
        assert ed._fmt("hello") == "hello"

    def test_int_as_string(self):
        assert ed._fmt(42) == "42"


# ---------------------------------------------------------------------------
# _source_lookup
# ---------------------------------------------------------------------------

class TestSourceLookup:
    def _registry(self, sources):
        return {"sources": sources}

    def test_basic_lookup_by_source_series_id(self):
        registry = self._registry([{
            "provider": "fred",
            "series": [{"source_series_id": "NFCI", "url": "https://fred.stl.org/NFCI"}],
        }])
        lookup = ed._source_lookup(registry)
        assert "NFCI" in lookup
        assert lookup["NFCI"]["url"] == "https://fred.stl.org/NFCI"

    def test_falls_back_to_series_id(self):
        registry = self._registry([{
            "series": [{"series_id": "VIXCLS"}],
        }])
        lookup = ed._source_lookup(registry)
        assert "VIXCLS" in lookup

    def test_empty_sources(self):
        assert ed._source_lookup({"sources": []}) == {}

    def test_missing_sources_key(self):
        assert ed._source_lookup({}) == {}

    def test_multiple_series_per_source(self):
        registry = self._registry([{
            "series": [
                {"source_series_id": "A"},
                {"source_series_id": "B"},
            ],
        }])
        lookup = ed._source_lookup(registry)
        assert "A" in lookup
        assert "B" in lookup

    def test_series_without_id_skipped(self):
        registry = self._registry([{"series": [{"no_id_here": True}]}])
        lookup = ed._source_lookup(registry)
        assert lookup == {}


# ---------------------------------------------------------------------------
# _point_at_or_before
# ---------------------------------------------------------------------------

class TestPointAtOrBefore:
    def _frame(self, rows):
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        df["value"] = df["value"].astype(float)
        return df

    def test_returns_last_value_at_date(self):
        df = self._frame([
            {"date": "2026-01-01", "value": 1.0},
            {"date": "2026-02-01", "value": 2.0},
            {"date": "2026-03-01", "value": 3.0},
        ])
        cutoff = pd.Timestamp("2026-02-15")
        result = ed._point_at_or_before(df, cutoff)
        assert result == pytest.approx(2.0)

    def test_exact_date_match(self):
        df = self._frame([
            {"date": "2026-04-01", "value": 7.5},
        ])
        result = ed._point_at_or_before(df, pd.Timestamp("2026-04-01"))
        assert result == pytest.approx(7.5)

    def test_all_after_cutoff_returns_none(self):
        df = self._frame([
            {"date": "2026-06-01", "value": 99.0},
        ])
        result = ed._point_at_or_before(df, pd.Timestamp("2026-01-01"))
        assert result is None

    def test_empty_frame_returns_none(self):
        df = pd.DataFrame({"date": pd.Series([], dtype="datetime64[ns]"), "value": pd.Series([], dtype=float)})
        result = ed._point_at_or_before(df, pd.Timestamp("2026-05-01"))
        assert result is None

    def test_nan_values_excluded(self):
        import numpy as np
        df = self._frame([
            {"date": "2026-01-01", "value": np.nan},
            {"date": "2026-02-01", "value": 5.0},
        ])
        result = ed._point_at_or_before(df, pd.Timestamp("2026-03-01"))
        assert result == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# _series_summary — missing series
# ---------------------------------------------------------------------------

class TestSeriesSummaryMissing:
    def test_returns_missing_status_when_not_in_panel(self):
        panel = pd.DataFrame(columns=["series_id", "date", "value", "unit", "frequency",
                                       "source_id", "source_series_id", "quality_flag"])
        result = ed._series_summary(panel, "UNKNOWN", {}, {})
        assert result["series_id"] == "UNKNOWN"
        assert result["status"] == "missing"
        assert result["latest_value"] is None

    def test_uses_freshness_reason_when_missing(self):
        panel = pd.DataFrame(columns=["series_id", "date", "value", "unit", "frequency",
                                       "source_id", "source_series_id", "quality_flag"])
        freshness = {"TEDRATE": {"freshness_status": "retired_or_unavailable",
                                  "retired_reason": "Series discontinued."}}
        result = ed._series_summary(panel, "TEDRATE", {}, freshness)
        assert result["retired_reason"] == "Series discontinued."


class TestSeriesSummaryAvailable:
    def test_matches_provider_prefixed_canonical_id(self):
        panel = pd.DataFrame([
            {
                "series_id": "CBOE:MOVE",
                "date": "2026-05-01",
                "value": 12.22,
                "unit": "index",
                "frequency": "daily",
                "source_id": "cboe",
                "source_series_id": "VXTLT",
                "quality_flag": "ok",
            }
        ])
        freshness = {
            "MOVE": {
                "freshness_status": "fresh",
                "observation_date": "2026-05-01",
                "vintage_date": "2026-05-01",
            }
        }

        result = ed._series_summary(panel, "MOVE", {"VXTLT": {"provider": "cboe"}}, freshness)

        assert result["status"] == "available"
        assert result["latest_value"] == pytest.approx(12.22)
        assert result["provider_payload"]["source_series_id"] == "VXTLT"
