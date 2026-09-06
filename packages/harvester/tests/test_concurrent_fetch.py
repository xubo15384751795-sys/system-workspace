from __future__ import annotations

import threading
import time
from unittest.mock import patch

import pandas as pd
from harvester.core.concurrent_policy import FRED_MAX_WORKERS, family_for_priority
from harvester.providers.base import ProviderResult
from harvester.registry import RegistrySeries, SeriesRegistry


def _registry(*series: RegistrySeries) -> SeriesRegistry:
    return SeriesRegistry(
        schema_version="1.0",
        series={item.canonical_id: item for item in series},
        providers={},
    )


def _spec(canonical_id: str, *providers: str) -> RegistrySeries:
    return RegistrySeries(
        canonical_id=canonical_id,
        source_series_id=canonical_id,
        provider_priority=providers,
        measurement_block="test",
        structural_role="test",
        frequency="daily",
    )


def test_family_split_matches_provider_groups() -> None:
    assert family_for_priority(("fred", "openbb_fred")) == "fred"
    assert family_for_priority(("etf_provider_chain",)) == "etf"
    assert family_for_priority(("sec",)) == "other"


def test_concurrent_switch_off_keeps_serial_outcome(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("SYSTEM_HARVESTER_CONCURRENT", raising=False)
    registry = _registry(_spec("OK", "fred"), _spec("BAD", "fred"))

    class FakeProvider:
        source_id = "fred"

        def fetch_series(self, series_ids: list[str]) -> list[ProviderResult]:
            series_id = series_ids[0]
            if series_id == "OK":
                return [ProviderResult("fred", series_id, pd.DataFrame({"date": ["2026-08-01"], "value": [1.0]}))]
            return [ProviderResult("fred", series_id, pd.DataFrame(), fetch_error="boom")]

    from harvester.official import fetch_official_series_from_registry

    with (
        patch("harvester.registry.load_registry", return_value=registry),
        patch("harvester.official.build_provider", return_value=FakeProvider()),
    ):
        panel = fetch_official_series_from_registry(
            data_root=str(tmp_path),
            providers=["fred"],
            cache=False,
        )
    assert panel.attrs["provider_outcome"]["succeeded_count"] == 1
    assert panel.attrs["provider_outcome"]["failed_series"] == ["BAD"]
    assert "carry_forward_reason" not in panel.attrs["provider_outcome"]


def test_deadline_skips_remaining_and_stamps_reason(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SYSTEM_HARVESTER_CONCURRENT", "1")
    registry = _registry(_spec("ONE", "fred"), _spec("TWO", "fred"))

    class FakeProvider:
        source_id = "fred"

        def fetch_series(self, series_ids: list[str]) -> list[ProviderResult]:
            raise AssertionError("deadline must skip provider calls")

    from harvester.official import fetch_official_series_from_registry

    with (
        patch("harvester.registry.load_registry", return_value=registry),
        patch("harvester.official.build_provider", return_value=FakeProvider()),
    ):
        panel = fetch_official_series_from_registry(
            data_root=str(tmp_path),
            providers=["fred"],
            cache=False,
            deadline_monotonic=time.monotonic() - 1,
        )
    outcome = panel.attrs["provider_outcome"]
    assert outcome["carry_forward_reason"] == "deadline"
    assert set(outcome["deadline_skipped_series"]) == {"ONE", "TWO"}
    assert set(outcome["failed_series"]) == {"ONE", "TWO"}


def test_fred_inflight_never_exceeds_cap(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SYSTEM_HARVESTER_CONCURRENT", "1")
    specs = [_spec(f"S{i}", "fred") for i in range(3)]
    registry = _registry(*specs)
    inflight = 0
    peak = 0
    lock = threading.Lock()

    class FakeProvider:
        source_id = "fred"

        def fetch_series(self, series_ids: list[str]) -> list[ProviderResult]:
            nonlocal inflight, peak
            with lock:
                inflight += 1
                peak = max(peak, inflight)
            time.sleep(0.05)
            with lock:
                inflight -= 1
            series_id = series_ids[0]
            return [ProviderResult("fred", series_id, pd.DataFrame({"date": ["2026-08-01"], "value": [1.0]}))]

    from harvester.official import fetch_official_series_from_registry

    with (
        patch("harvester.registry.load_registry", return_value=registry),
        patch("harvester.official.build_provider", return_value=FakeProvider()),
    ):
        panel = fetch_official_series_from_registry(
            data_root=str(tmp_path),
            providers=["fred"],
            cache=False,
        )
    assert peak <= FRED_MAX_WORKERS
    assert panel.attrs["provider_outcome"]["succeeded_count"] == 3
