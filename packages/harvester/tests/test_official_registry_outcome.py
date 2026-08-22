from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from harvester.providers.base import ProviderResult
from harvester.registry import RegistrySeries, SeriesRegistry


def test_optional_external_timeout_is_bounded(monkeypatch) -> None:
    from harvester.official import _external_indicator_timeout_seconds

    monkeypatch.setenv("HARVESTER_EXTERNAL_TIMEOUT_SEC", "999")
    assert _external_indicator_timeout_seconds() == 30
    monkeypatch.setenv("HARVESTER_EXTERNAL_TIMEOUT_SEC", "0")
    assert _external_indicator_timeout_seconds() == 1
    monkeypatch.setenv("HARVESTER_EXTERNAL_TIMEOUT_SEC", "invalid")
    assert _external_indicator_timeout_seconds() == 10


def test_registry_fetch_records_partial_provider_outcome(tmp_path) -> None:
    registry = SeriesRegistry(
        schema_version="1.0",
        series={
            "OK_SERIES": RegistrySeries(
                canonical_id="OK_SERIES",
                source_series_id="OK_SERIES",
                provider_priority=("fake",),
                measurement_block="test",
                structural_role="test",
                frequency="daily",
            ),
            "BAD_SERIES": RegistrySeries(
                canonical_id="BAD_SERIES",
                source_series_id="BAD_SERIES",
                provider_priority=("fake",),
                measurement_block="test",
                structural_role="test",
                frequency="daily",
            ),
        },
        providers={},
    )

    class FakeProvider:
        source_id = "fake"

        def fetch_series(self, series_ids: list[str]) -> list[ProviderResult]:
            results: list[ProviderResult] = []
            for series_id in series_ids:
                if series_id == "OK_SERIES":
                    frame = pd.DataFrame({"date": ["2026-08-01"], "value": [1.0]})
                    results.append(ProviderResult("fake", series_id, frame))
                else:
                    results.append(
                        ProviderResult(
                            "fake",
                            series_id,
                            pd.DataFrame(),
                            fetch_error="fixture provider failure",
                        )
                    )
            return results

    from harvester.official import fetch_official_series_from_registry

    with (
        patch("harvester.registry.load_registry", return_value=registry),
        patch("harvester.official.build_provider", return_value=FakeProvider()),
    ):
        panel = fetch_official_series_from_registry(
            data_root=str(tmp_path),
            providers=["fake"],
            cache=False,
        )

    outcome = panel.attrs["provider_outcome"]
    assert outcome["status"] == "partial_provider_success"
    assert outcome["provider"] == "harvester.registry"
    assert outcome["requested_count"] == 2
    assert outcome["succeeded_count"] == 1
    assert outcome["failed_count"] == 1
    assert outcome["failed_series"] == ["BAD_SERIES"]


def test_registry_fetch_leaves_external_managed_series_to_external_provider(tmp_path) -> None:
    registry = SeriesRegistry(
        schema_version="1.0",
        series={
            "OK_SERIES": RegistrySeries(
                canonical_id="OK_SERIES",
                source_series_id="OK_SERIES",
                provider_priority=("fake",),
                measurement_block="test",
                structural_role="test",
                frequency="daily",
            ),
            "EXTERNAL_SERIES": RegistrySeries(
                canonical_id="EXTERNAL_SERIES",
                source_series_id="EXTERNAL_SERIES",
                provider_priority=("external_public",),
                measurement_block="test",
                structural_role="test",
                frequency="daily",
            ),
        },
        providers={},
    )

    class FakeProvider:
        source_id = "fake"

        def fetch_series(self, series_ids: list[str]) -> list[ProviderResult]:
            assert series_ids == ["OK_SERIES"]
            return [
                ProviderResult(
                    "fake",
                    "OK_SERIES",
                    pd.DataFrame({"date": ["2026-08-01"], "value": [1.0]}),
                )
            ]

    from harvester.official import fetch_official_series_from_registry

    with (
        patch("harvester.registry.load_registry", return_value=registry),
        patch("harvester.official.build_provider", return_value=FakeProvider()),
    ):
        panel = fetch_official_series_from_registry(
            data_root=str(tmp_path),
            providers=["fake"],
            cache=False,
        )

    outcome = panel.attrs["provider_outcome"]
    assert outcome["requested_count"] == 1
    assert outcome["succeeded_count"] == 1
    assert outcome["failed_count"] == 0
    assert outcome["failed_series"] == []


def test_registry_outcome_does_not_classify_mixed_benchmark_as_etf_route(tmp_path) -> None:
    registry = SeriesRegistry(
        schema_version="1.0",
        series={
            "ETF_SERIES": RegistrySeries(
                canonical_id="ETF_SERIES",
                source_series_id="ETF_SERIES",
                provider_priority=("tiingo",),
                measurement_block="test",
                structural_role="test",
                frequency="daily",
            ),
            "MACRO_SERIES": RegistrySeries(
                canonical_id="MACRO_SERIES",
                source_series_id="MACRO_SERIES",
                provider_priority=("fred",),
                measurement_block="test",
                structural_role="test",
                frequency="daily",
            ),
        },
        providers={},
    )

    class FakeProvider:
        source_id = "tiingo"

        def fetch_series(self, series_ids: list[str]) -> list[ProviderResult]:
            return [
                ProviderResult(
                    "tiingo",
                    series_id,
                    pd.DataFrame({"date": ["2026-08-01"], "value": [1.0]}),
                )
                for series_id in series_ids
            ]

    from harvester.official import fetch_official_series_from_registry

    with (
        patch("harvester.registry.load_registry", return_value=registry),
        patch("harvester.official.build_provider", return_value=FakeProvider()),
    ):
        panel = fetch_official_series_from_registry(
            data_root=str(tmp_path),
            providers=["tiingo", "fred"],
            cache=False,
        )

    assert "route_policy" not in panel.attrs["provider_outcome"]


def test_manual_external_series_are_reported_without_becoming_unavailable() -> None:
    from harvester.official import _merge_external_provider_outcome

    outcome = _merge_external_provider_outcome(
        None,
        requested_series={"CFTC_TFF_LEV_SP"},
        succeeded_series={"CFTC_TFF_LEV_SP": "cftc"},
        failed_series={},
        manual_series={"SRISK": "manual_refresh_required", "COVAR": "cached"},
    )

    assert outcome is not None
    assert outcome["status"] == "refreshed"
    assert outcome["requested_count"] == 1
    assert outcome["failed_count"] == 0
    assert outcome["failed_series"] == []
    assert outcome["manual_series"] == {
        "COVAR": "cached",
        "SRISK": "manual_refresh_required",
    }


def test_complete_release_propagates_provider_outcome_to_artifacts(tmp_path) -> None:
    from harvester.official import stage_complete_release

    outcome = {
        "status": "partial_provider_success",
        "provider": "harvester.registry",
        "requested_count": 2,
        "succeeded_count": 1,
        "failed_count": 1,
        "failed_series": ["BAD_SERIES"],
        "retrieved_at": "2026-08-01T00:00:00Z",
    }
    panel = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-08-01"]),
            "series_id": ["FAKE:OK_SERIES"],
            "source_id": ["fake"],
            "source_series_id": ["OK_SERIES"],
            "value": [1.0],
            "unit": [""],
            "frequency": ["daily"],
            "vintage_date": ["2026-08-01"],
            "quality_flag": [0],
        }
    )
    panel.attrs["provider_outcome"] = outcome
    registry = SimpleNamespace(
        active_series=lambda: [],
        derived_series=lambda: [],
    )
    gate = SimpleNamespace(
        state="rejected",
        passed=False,
        blockers=["fixture provider failure"],
        warnings=[],
    )

    with (
        patch("harvester.registry.load_registry", return_value=registry),
        patch("harvester.official.fetch_official_series_from_registry", return_value=panel),
        patch(
            "harvester.cross_asset_panel.stage_cross_asset_panel",
            return_value={
                "data_path": "",
                "row_count": 252,
                "symbol_count": 1,
                "provider_outcome": {
                    "status": "refreshed",
                    "provider": "fixture",
                    "requested_count": 1,
                    "succeeded_count": 1,
                    "failed_count": 0,
                    "failed_series": [],
                    "retrieved_at": "2026-08-01T00:00:00Z",
                },
            },
        ),
        patch("harvester.promotion.run_promotion_gate", return_value=gate),
        patch("harvester.promotion.write_gate_report"),
    ):
        result = stage_complete_release(
            release_id="2026-08-01-r1",
            as_of_date="2026-08-01",
            vintage_date="2026-08-01",
            exports_root=str(tmp_path / "exports"),
            include_external=False,
        )

    release = tmp_path / "exports" / "2026-08-01-r1"
    manifest = json.loads(
        (release / "manifests" / "benchmark_panel.manifest.json").read_text()
    )
    provenance = json.loads(
        (release / "provenance" / "benchmark_panel.provenance.json").read_text()
    )
    quality = json.loads(
        (release / "quality_reports" / "benchmark_panel.quality.json").read_text()
    )
    chain_path = release / "provenance" / "benchmark_panel.canonical_chains.jsonl"
    chains = [json.loads(line) for line in chain_path.read_text().splitlines() if line.strip()]
    from system_runtime.canonical_ids import validate_chain

    assert len(chains) == 1
    validate_chain(chains[0])
    assert chains[0]["claim"]["status"] == "WATCH"
    assert chains[0]["claim"]["provenance"]["promotion_allowed"] is False

    assert result["gate_passed"] is False
    assert manifest["provider_outcome"] == outcome
    assert provenance["provider_outcome"] == outcome
    assert provenance["canonical_chain_count"] == 1
    assert quality["provider_outcome"] == outcome

    proxy_spec_path = release / "provenance" / "proxy_candidate_panel.measurement_spec.json"
    proxy_provenance = json.loads(
        (release / "provenance" / "proxy_candidate_panel.provenance.json").read_text()
    )
    assert proxy_spec_path.exists()
    proxy_spec = json.loads(proxy_spec_path.read_text())
    assert proxy_spec["derivation"] == "PROXY_DERIVED"
    assert proxy_spec["promotion_allowed"] is False
    assert proxy_spec["claim_ceiling"] == "diagnostic_proxy_candidate_only"
    assert "canonical_chain_path" not in proxy_provenance
    assert proxy_provenance["measurement_spec_path"] == (
        "provenance/proxy_candidate_panel.measurement_spec.json"
    )
