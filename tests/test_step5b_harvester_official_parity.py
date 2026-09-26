"""Bounded Step 5B facade and failure-parity audit."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd
from harvester.official import (
    _carry_forward_missing_series,
    fetch_official_series_from_registry,
    normalize_release_panel,
)
from harvester.providers import ProviderError
from harvester.providers.base import ProviderResult
from harvester.registry import RegistrySeries, SeriesRegistry


def _registry(*series_ids: str) -> SeriesRegistry:
    return SeriesRegistry(
        schema_version="1.0",
        series={
            series_id: RegistrySeries(
                canonical_id=series_id,
                source_series_id=series_id,
                provider_priority=("fake",),
                measurement_block="step5b",
                structural_role="fixture",
                frequency="daily",
            )
            for series_id in series_ids
        },
        providers={},
    )


def _run_registry(
    tmp_path: Path,
    registry: SeriesRegistry,
    provider_factory: object,
) -> pd.DataFrame:
    with (
        patch("harvester.registry.load_registry", return_value=registry),
        patch("harvester.official.build_provider", provider_factory),
    ):
        return fetch_official_series_from_registry(
            data_root=str(tmp_path),
            providers=["fake"],
            cache=False,
        )


def test_normal_provider_success_uses_acquisition_owner(tmp_path: Path) -> None:
    class Provider:
        source_id = "fake"

        def fetch_series(self, series_ids: list[str]) -> list[ProviderResult]:
            return [
                ProviderResult(
                    "fake",
                    series_ids[0],
                    pd.DataFrame({"date": ["2026-08-01"], "value": [1.0]}),
                )
            ]

    panel = _run_registry(tmp_path, _registry("OK"), Mock(return_value=Provider()))
    assert not panel.empty
    assert panel.attrs["provider_outcome"]["status"] == "refreshed"


def test_missing_credential_is_fail_closed(tmp_path: Path) -> None:
    panel = _run_registry(
        tmp_path,
        _registry("NEEDS_KEY"),
        Mock(side_effect=ProviderError("FRED_API_KEY missing")),
    )
    assert panel.empty
    assert panel.attrs["provider_outcome"]["status"] == "provider_failed_no_acceptable_fallback"


def test_provider_unavailable_is_visible(tmp_path: Path) -> None:
    class Provider:
        source_id = "fake"

        def fetch_series(self, series_ids: list[str]) -> list[ProviderResult]:
            return [
                ProviderResult(
                    "fake",
                    series_ids[0],
                    pd.DataFrame(),
                    fetch_error="provider unavailable",
                )
            ]

    panel = _run_registry(tmp_path, _registry("DOWN"), Mock(return_value=Provider()))
    assert panel.empty
    outcome = panel.attrs["provider_outcome"]
    assert outcome["status"] == "provider_failed_no_acceptable_fallback"
    assert "DOWN" in outcome["failed_series"]


def test_stale_fallback_preserves_failure_and_marks_reuse(tmp_path: Path) -> None:
    exports = tmp_path / "exports"
    previous_dir = exports / "2026-08-09-r1" / "data"
    previous_dir.mkdir(parents=True)
    previous = pd.DataFrame(
        {
            "date": ["2026-08-01"],
            "series_id": ["FRED:OPTIONAL"],
            "source_id": ["fred"],
            "source_series_id": ["OPTIONAL"],
            "value": [1.0],
            "unit": [""],
            "frequency": ["daily"],
            "vintage_date": ["2026-08-09"],
            "quality_flag": [0],
        }
    )
    previous.to_parquet(previous_dir / "benchmark_panel.parquet", index=False)
    current = previous.iloc[0:0].copy()
    current.attrs["provider_outcome"] = {
        "status": "partial_provider_success",
        "provider": "harvester.registry",
        "requested_count": 1,
        "succeeded_count": 0,
        "failed_count": 1,
        "failed_series": ["OPTIONAL"],
        "retrieved_at": "2026-08-10T00:00:00Z",
    }
    registry = SimpleNamespace(
        required_series=lambda: [],
        active_series=lambda: [
            RegistrySeries(
                canonical_id="OPTIONAL",
                source_series_id="OPTIONAL",
                provider_priority=("fake",),
                measurement_block="step5b",
                structural_role="fixture",
                frequency="daily",
            )
        ],
    )
    with patch("harvester.registry.load_registry", return_value=registry):
        fixed = _carry_forward_missing_series(
            current,
            exports_root=exports,
            exclude_release_id="2026-08-10-r1",
        )
    assert "FRED:OPTIONAL" in set(fixed["series_id"])
    assert fixed.attrs["provider_outcome"]["status"] == "partial_provider_success"


def test_schema_anomaly_is_normalized_by_canonical_owner() -> None:
    normalized = normalize_release_panel(
        pd.DataFrame(
            {
                "date": ["not-a-date"],
                "series_id": ["FAKE:BAD"],
                "source_id": ["fake"],
                "source_series_id": ["BAD"],
                "value": ["not-a-number"],
                "quality_flag": [0],
            }
        )
    )
    assert pd.isna(normalized.loc[0, "date"])
    assert pd.isna(normalized.loc[0, "value"])


def test_partial_acquisition_preserves_failed_series(tmp_path: Path) -> None:
    class Provider:
        source_id = "fake"

        def fetch_series(self, series_ids: list[str]) -> list[ProviderResult]:
            series_id = series_ids[0]
            if series_id == "OK":
                return [
                    ProviderResult(
                        "fake",
                        series_id,
                        pd.DataFrame({"date": ["2026-08-01"], "value": [1.0]}),
                    )
                ]
            return [ProviderResult("fake", series_id, pd.DataFrame(), fetch_error="fixture failure")]

    panel = _run_registry(
        tmp_path,
        _registry("OK", "BAD"),
        Mock(return_value=Provider()),
    )
    outcome = panel.attrs["provider_outcome"]
    assert outcome["status"] == "partial_provider_success"
    assert outcome["failed_series"] == ["BAD"]
