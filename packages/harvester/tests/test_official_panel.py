from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pandas as pd
import pytest

import harvester.http_gateway as gateway_module
from harvester.http_gateway import OwnedHTTPGateway
from harvester.core.manifest import load_schema as load_manifest_schema
from harvester.core.provenance import load_schema as load_provenance_schema
from harvester.official import (
    DEFAULT_OFFICIAL_PROVIDERS,
    OFFICIAL_SERIES_MAP,
    fetch_official_series,
    make_manifest,
    make_provenance,
    save_processed_panel,
    stage_release,
)


def _mock_fred_response():
    return {
        "units": "Percent",
        "frequency": "Daily",
        "observations": [
            {"date": "2026-01-02", "value": "4.25"},
            {"date": "2026-01-05", "value": "4.27"},
        ],
    }


def _mock_treasury_response():
    return {
        "data": [
            {"record_date": "2026-01-02", "tot_pub_debt_out_amt": "35000000000000.00"},
        ]
    }


def _mock_sec_response():
    return {
        "cik": "0000072971",
        "filings": {
            "recent": {
                "filingDate": ["2026-01-15", "2026-01-15"],
                "form": ["10-Q", "8-K"],
                "accessionNumber": ["a1", "a2"],
                "reportDate": ["2025-12-31", "2025-12-31"],
                "primaryDocument": ["d1.htm", "d2.htm"],
            }
        },
    }


def _mock_response(json_data: dict):
    return httpx.Response(200, content=json.dumps(json_data).encode("utf-8"))


def _gateway(response: httpx.Response) -> OwnedHTTPGateway:
    return OwnedHTTPGateway(transport=httpx.MockTransport(lambda _request: response))


@pytest.fixture(autouse=True)
def _allow_fake_gateway_hosts(monkeypatch):
    monkeypatch.setattr(gateway_module, "validate_outbound_url", lambda url: url)


class TestOfficialPanelIntegration:
    def test_fetch_official_series_all_providers(self, tmp_path) -> None:
        with _gateway(_mock_response(_mock_fred_response())) as gateway:
            with patch("harvester.providers.fred.OwnedHTTPGateway", return_value=gateway):
                panel = fetch_official_series(
                    as_of_date="2026-04-30",
                    data_root=str(tmp_path),
                    providers=["fred"],
                    cache=False,
                    api_keys={"fred": "test_key"},
                )

            assert not panel.empty
            assert "date" in panel.columns
            assert "series_id" in panel.columns
            assert "source_id" in panel.columns
            assert "source_series_id" in panel.columns
            assert "value" in panel.columns
            assert "unit" in panel.columns
            assert "frequency" in panel.columns
            assert "vintage_date" in panel.columns
            assert "quality_flag" in panel.columns

            assert panel["date"].dtype.kind == "M"  # datetime
            assert panel["quality_flag"].dtype.kind in ("i", "u")  # int

            series_ids = panel["series_id"].unique()
            assert any(s.startswith("FRED:") for s in series_ids)

    def test_long_panel_column_order(self, tmp_path) -> None:
        expected_columns = [
            "date", "series_id", "source_id", "source_series_id",
            "value", "unit", "frequency", "vintage_date", "quality_flag",
        ]
        with _gateway(_mock_response(_mock_fred_response())) as gateway:
            with patch("harvester.providers.fred.OwnedHTTPGateway", return_value=gateway):
                panel = fetch_official_series(
                    as_of_date="2026-04-30",
                    data_root=str(tmp_path),
                    providers=["fred"],
                    cache=False,
                    api_keys={"fred": "test_key"},
                )
            for col in expected_columns:
                assert col in panel.columns, f"missing column: {col}"

    def test_no_providers_returns_empty(self, tmp_path) -> None:
        panel = fetch_official_series(
            as_of_date="2026-04-30",
            data_root=str(tmp_path),
            providers=[],
            cache=False,
        )
        assert panel.empty
        for col in ["date", "series_id", "source_id", "value", "quality_flag"]:
            assert col in panel.columns

    def test_save_processed_panel(self, tmp_path) -> None:
        panel = pd.DataFrame({
            "date": pd.to_datetime(["2026-01-01"]),
            "series_id": ["TEST:FOO"],
            "source_id": ["test"],
            "source_series_id": ["FOO"],
            "value": [1.0],
            "unit": ["pct"],
            "frequency": ["daily"],
            "vintage_date": ["2026-04-30"],
            "quality_flag": [0],
        })
        path = save_processed_panel(panel, str(tmp_path))
        assert path.exists()
        assert path.suffix == ".parquet"
        loaded = pd.read_parquet(path)
        assert len(loaded) == 1
        assert loaded["series_id"].iloc[0] == "TEST:FOO"


class TestManifestProvenance:
    def test_make_manifest_meets_schema(self, tmp_path) -> None:
        panel = pd.DataFrame({
            "date": pd.to_datetime(["2026-01-01"]),
            "series_id": ["FRED:T10Y2Y"],
            "source_id": ["fred"],
            "source_series_id": ["T10Y2Y"],
            "value": [4.25],
            "unit": ["pct"],
            "frequency": ["daily"],
            "vintage_date": ["2026-04-30"],
            "quality_flag": [0],
        })
        data_path = tmp_path / "data" / "official_panel.parquet"
        data_path.parent.mkdir(parents=True, exist_ok=True)
        panel.to_parquet(data_path, index=False)

        manifest = make_manifest(
            dataset_id="official_panel",
            release_id="2026-04-30-r1",
            as_of_date="2026-04-30",
            vintage_date="2026-04-30",
            data_path=data_path,
            provider="harvester.official",
            source_url="https://api.stlouisfed.org/fred",
            row_count=1,
        )

        assert manifest["dataset_id"] == "official_panel"
        assert manifest["release_id"] == "2026-04-30-r1"
        assert "sha256" in manifest["data_file"]
        assert len(manifest["data_file"]["sha256"]) == 64
        assert manifest["data_file"]["byte_size"] > 0
        assert manifest["data_file"]["row_count"] == 1

        manifest_schema = load_manifest_schema()
        from jsonschema import Draft202012Validator, FormatChecker

        validator = Draft202012Validator(manifest_schema, format_checker=FormatChecker())
        errors = list(validator.iter_errors(manifest))
        assert not errors, f"manifest validation errors: {errors}"

    def test_make_provenance_meets_schema(self, tmp_path) -> None:
        provenance = make_provenance(
            dataset_id="official_panel",
            release_id="2026-04-30-r1",
            method="api_client",
            source_identifier="harvester.providers",
            final_sha256=hashlib.sha256(b"test data").hexdigest(),
            raw_sha256="f" * 64,
        )

        assert provenance["dataset_id"] == "official_panel"
        assert provenance["release_id"] == "2026-04-30-r1"
        assert provenance["acquisition"]["method"] == "api_client"
        assert "final_sha256" in provenance["checksums"]
        assert "raw_sha256" in provenance["checksums"]

        prov_schema = load_provenance_schema()
        from jsonschema import Draft202012Validator, FormatChecker

        validator = Draft202012Validator(prov_schema, format_checker=FormatChecker())
        errors = list(validator.iter_errors(provenance))
        assert not errors, f"provenance validation errors: {errors}"

    def test_stage_release(self, tmp_path) -> None:
        panel = pd.DataFrame({
            "date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "series_id": ["FRED:T10Y2Y", "FRED:T10Y2Y"],
            "source_id": ["fred", "fred"],
            "source_series_id": ["T10Y2Y", "T10Y2Y"],
            "value": [4.25, 4.27],
            "unit": ["pct", "pct"],
            "frequency": ["daily", "daily"],
            "vintage_date": ["2026-04-30", "2026-04-30"],
            "quality_flag": [0, 0],
        })

        info = stage_release(
            panel,
            release_id="2026-04-30-r1",
            as_of_date="2026-04-30",
            vintage_date="2026-04-30",
            exports_root=str(tmp_path),
        )

        assert info["release_id"] == "2026-04-30-r1"
        assert info["row_count"] == 2
        assert Path(info["data_path"]).exists()
        assert Path(info["manifest_path"]).exists()
        assert Path(info["provenance_path"]).exists()
        observation_path = Path(info["provenance_path"]).parent / "official_panel.canonical_observations.jsonl"
        chain_path = Path(info["provenance_path"]).parent / "official_panel.canonical_chains.jsonl"
        assert observation_path.exists()
        assert chain_path.exists()
        from system_runtime.canonical_ids import validate_chain, validate_observation

        observations = [json.loads(line) for line in observation_path.read_text().splitlines() if line.strip()]
        chains = [json.loads(line) for line in chain_path.read_text().splitlines() if line.strip()]
        assert len(observations) == len(chains) == 2
        for observation in observations:
            validate_observation(observation)
        for chain in chains:
            validate_chain(chain)
            assert chain["claim"]["provenance"]["statement_kind"] == "recorded_observation"
            assert chain["claim"]["provenance"]["promotion_allowed"] is False

        manifest = json.loads(Path(info["manifest_path"]).read_text())
        assert manifest["dataset_id"] == "official_panel"
        assert manifest["data_file"]["sha256"] is not None

        provenance = json.loads(Path(info["provenance_path"]).read_text())
        assert provenance["checksums"]["final_sha256"] == manifest["data_file"]["sha256"]
        assert provenance["canonical_observation_count"] == 2
        assert provenance["canonical_chain_count"] == 2

    def test_manifest_sha256_matches_file(self, tmp_path) -> None:
        panel = pd.DataFrame({
            "date": pd.to_datetime(["2026-01-01"]),
            "series_id": ["FRED:T10Y2Y"],
            "source_id": ["fred"],
            "source_series_id": ["T10Y2Y"],
            "value": [4.25],
            "unit": ["pct"],
            "frequency": ["daily"],
            "vintage_date": ["2026-04-30"],
            "quality_flag": [0],
        })
        data_path = tmp_path / "test.parquet"
        panel.to_parquet(data_path, index=False)

        manifest = make_manifest(
            dataset_id="official_panel",
            release_id="2026-04-30-r1",
            as_of_date="2026-04-30",
            vintage_date="2026-04-30",
            data_path=data_path,
            provider="harvester.official",
            source_url="test",
        )

        expected_sha = hashlib.sha256(data_path.read_bytes()).hexdigest()
        assert manifest["data_file"]["sha256"] == expected_sha

    def test_official_series_map_completeness(self) -> None:
        required_providers = {"fred", "h41", "treasury", "sec", "openbb_fred", "cboe_direct", "openbb_tiingo", "openbb_yfinance", "etf_provider_chain"}
        assert set(DEFAULT_OFFICIAL_PROVIDERS) == required_providers
        assert required_providers.issubset(set(OFFICIAL_SERIES_MAP.keys()))

        assert len(OFFICIAL_SERIES_MAP["fred"]["series"]) >= 5
        assert len(OFFICIAL_SERIES_MAP["h41"]["series"]) == 3
        assert len(OFFICIAL_SERIES_MAP["treasury"]["series"]) == 2
        assert len(OFFICIAL_SERIES_MAP["sec"]["series"]) == 1
        assert "MOVE" in OFFICIAL_SERIES_MAP["cboe_direct"]["series"]
        assert "TYVIX" in OFFICIAL_SERIES_MAP["cboe_direct"]["series"]
        assert "VXTLT" in OFFICIAL_SERIES_MAP["cboe_direct"]["series"]
        assert "HYG" in OFFICIAL_SERIES_MAP["openbb_tiingo"]["series"]
        assert "HYG" in OFFICIAL_SERIES_MAP["etf_provider_chain"]["series"]
        assert "SPY" in OFFICIAL_SERIES_MAP["openbb_yfinance"]["series"]
        assert "STLFSI4" in OFFICIAL_SERIES_MAP["openbb_fred"]["series"]
        assert "HYG" in OFFICIAL_SERIES_MAP["openbb_tiingo"]["series"]

        for provider, config in OFFICIAL_SERIES_MAP.items():
            for sid in config["series"]:
                assert sid in config["desc"], f"missing description for {provider}/{sid}"
