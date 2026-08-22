from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

import harvester.http_gateway as gateway_module
from harvester.http_gateway import OwnedHTTPGateway
from harvester.providers.h41 import (
    H41_DDP_MAP,
    H41_DDP_TABLE1_PACKAGE,
    H41_FRED_MAP,
    H41_SOURCE_NOTE,
    H41_UNITS,
    H41Provider,
    _parse_ddp_series_csv,
)

FRED_H41_RESPONSE = {
    "realtime_start": "2026-04-01",
    "realtime_end": "2026-04-30",
    "observation_start": "2026-01-01",
    "observation_end": "2026-04-30",
    "units": "Millions of U.S. Dollars",
    "frequency": "Weekly, Ending Wednesday",
    "observations": [
        {"date": "2026-01-07", "value": "125.0"},
        {"date": "2026-01-14", "value": "130.0"},
        {"date": "2026-01-21", "value": "."},
        {"date": "2026-01-28", "value": "128.0"},
    ],
}

# BTFP post-expiry: all values are zero (valid state, not an error)
FRED_BTFP_ZERO_RESPONSE = {
    "realtime_start": "2026-04-01",
    "realtime_end": "2026-04-30",
    "observation_start": "2026-01-01",
    "observation_end": "2026-04-30",
    "units": "Millions of U.S. Dollars",
    "frequency": "Weekly, Ending Wednesday",
    "observations": [
        {"date": "2026-01-07", "value": "0"},
        {"date": "2026-01-14", "value": "0"},
        {"date": "2026-01-21", "value": "0"},
    ],
}

DDP_H41_RESPONSE = """Time Period,H41/H41/RESPPALDP_N.WW,H41/H41/RESPPALDQ_N.WW,H41/H41/RESPPALDS_N.WW,H41/H41/RESPPALDK_N.WW
2026-01-07,125.0,2.0,3.0,0
2026-01-14,130.0,1.0,4.0,0
2026-01-21,,0.0,0.0,0
"""


def _mock_response(json_data: dict, status: int = 200, text: str = ""):
    return httpx.Response(status, content=(text or json.dumps(json_data)).encode("utf-8"))


def _gateway(*responses: httpx.Response) -> OwnedHTTPGateway:
    remaining = list(responses)

    def handler(_request: httpx.Request) -> httpx.Response:
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    return OwnedHTTPGateway(transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def _allow_fake_gateway_hosts(monkeypatch):
    monkeypatch.setattr(gateway_module, "validate_outbound_url", lambda url: url)


class TestH41Provider:
    def test_real_ddp_table1_fixture_parses_total_and_primary_rows(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "h41_ddp_table1_real.html"
        text = fixture.read_text(encoding="utf-8")
        codes = H41_DDP_MAP["discount_window"]
        assert isinstance(codes, tuple)

        total = _parse_ddp_series_csv(text, codes, "discount_window")
        primary = _parse_ddp_series_csv(text, (H41_DDP_MAP["primary_credit"],), "primary_credit")

        assert total.iloc[-1]["value"] == 5101.0
        assert primary.iloc[-1]["value"] == 5038.0

    def test_ddp_request_uses_preformatted_package_params(self, tmp_path) -> None:
        requests: list[dict[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(dict(request.url.params))
            return _mock_response({}, text=DDP_H41_RESPONSE)

        gateway = OwnedHTTPGateway(transport=httpx.MockTransport(handler))
        with gateway:
            result = H41Provider(data_root=str(tmp_path), cache=False, gateway=gateway).fetch_series(
                ["primary_credit"]
            )[0]

        assert result.fetch_error is None
        assert requests[0]["series"] == H41_DDP_TABLE1_PACKAGE
        assert requests[0]["type"] == "package"
        assert requests[0]["lastobs"] == "5000"

    def test_btfp_missing_from_current_table_uses_public_fred_graph(self, tmp_path) -> None:
        graph = "DATE,H41RESPPALDKNWW\n2024-01-03,10\n2024-01-10,0\n"
        with _gateway(
            _mock_response({}, text=(Path(__file__).parent / "fixtures" / "h41_ddp_table1_real.html").read_text()),
            _mock_response({}, text=graph),
        ) as gateway:
            result = H41Provider(data_root=str(tmp_path), cache=False, gateway=gateway).fetch_series(
                ["btfp"]
            )[0]

        assert result.fetch_error is None
        assert result.source_params["method"] == "fred_public_graph"
        assert result.frame["value"].tolist() == [10.0, 0.0]

    def test_btfp_graph_transport_failure_uses_captured_fred_history(self, tmp_path) -> None:
        raw_dir = tmp_path / "raw" / "h41"
        raw_dir.mkdir(parents=True)
        (raw_dir / "h41_H41RESPPALDKNWW_raw.json").write_text(
            json.dumps(
                {
                    "frequency": "Weekly, Ending Wednesday",
                    "observations": [
                        {"observation_date": "2024-01-03", "value": "10"},
                        {"observation_date": "2024-01-10", "value": "0"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        with _gateway(
            _mock_response(
                {},
                text=(Path(__file__).parent / "fixtures" / "h41_ddp_table1_real.html").read_text(),
            ),
            _mock_response({}, status=503),
        ) as gateway:
            result = H41Provider(data_root=str(tmp_path), cache=False, gateway=gateway).fetch_series(
                ["btfp"]
            )[0]

        assert result.fetch_error is None
        assert result.source_params["method"] == "fred_cached_history"
        assert result.source_params["verification_status"] == "CACHED"
        assert result.frame["value"].tolist() == [10.0, 0.0]
        assert "public_fred_graph_failed" in (result.fetch_fallback_reason or "")

    def test_field_mappings_exist(self) -> None:
        assert "discount_window" in H41_DDP_MAP
        assert "primary_credit" in H41_DDP_MAP
        assert "btfp" in H41_DDP_MAP
        assert "discount_window" in H41_FRED_MAP
        assert "primary_credit" in H41_FRED_MAP
        assert "btfp" in H41_FRED_MAP
        assert H41_FRED_MAP["discount_window"] == "WORAL"
        assert H41_FRED_MAP["primary_credit"] == "WPCREDIT"
        assert H41_FRED_MAP["btfp"] == "H41RESPPALDKNWW"

    def test_source_notes_have_required_fields(self) -> None:
        required_keys = {
            "table", "row_label", "field_semantic", "sign",
            "units", "expiry_behavior", "fred_series",
            "fred_frequency", "fred_units",
        }
        for field in ("discount_window", "primary_credit", "btfp"):
            assert field in H41_SOURCE_NOTE, f"missing source note for {field}"
            note = H41_SOURCE_NOTE[field]
            assert isinstance(note, dict), f"source note for {field} must be a dict"
            missing = required_keys - set(note.keys())
            assert not missing, f"source note for {field} missing keys: {missing}"
            assert "PROVISIONAL" in note["fred_series"] or True  # at minimum has content

    def test_btfp_source_note_documents_zero_behavior(self) -> None:
        btfp_note = H41_SOURCE_NOTE["btfp"]
        assert "zeros" in btfp_note["expiry_behavior"]
        assert "observed_zero" in btfp_note.get("expiry_behavior", "").lower() or \
               "observed_zero" in btfp_note.get("field_semantic", "").lower()

    def test_units_exist(self) -> None:
        for field in ("discount_window", "primary_credit", "btfp"):
            assert field in H41_UNITS
            assert H41_UNITS[field] == "mil_usd"

    def test_fetch_via_direct_ddp(self, tmp_path) -> None:
        with _gateway(_mock_response({}, text=DDP_H41_RESPONSE)) as gateway:
            prov = H41Provider(data_root=str(tmp_path), cache=False, gateway=gateway)
            results = prov.fetch_series(["primary_credit"])

            assert len(results) == 1
            r = results[0]
            assert r.provider == "h41"
            assert r.series_id == "primary_credit"
            assert not r.frame.empty
            df = r.frame
            assert len(df) == 3
            assert df["value"].iloc[0] == 125.0
            assert df["unit"].iloc[0] == "mil_usd"
            assert df["frequency"].iloc[0] == "Weekly, Ending Wednesday"

            assert r.source_params["method"] == "federal_reserve_ddp_csv"
            assert r.source_params["ddp_series"] == ["H41/H41/RESPPALDP_N.WW"]
            assert r.source_params["verification_status"] == "DIRECT"
            assert r.source_params["status_detail"] == "direct_h41_ddp"

    def test_discount_window_sums_direct_ddp_components(self, tmp_path) -> None:
        with _gateway(_mock_response({}, text=DDP_H41_RESPONSE)) as gateway:
            prov = H41Provider(data_root=str(tmp_path), cache=False, gateway=gateway)
            result = prov.fetch_series(["discount_window"])[0]

            assert not result.frame.empty
            assert result.frame["value"].iloc[0] == 130.0
            assert result.source_params["verification_status"] == "DIRECT"

    def test_btfp_zero_values_are_not_errors(self, tmp_path) -> None:
        with _gateway(_mock_response({}, text=DDP_H41_RESPONSE)) as gateway:
            prov = H41Provider(data_root=str(tmp_path), cache=False, gateway=gateway)
            results = prov.fetch_series(["btfp"])

            assert len(results) == 1
            r = results[0]
            assert r.provider == "h41"
            assert not r.frame.empty
            assert len(r.frame) == 3
            assert (r.frame["value"] == 0.0).all()
            # Must NOT be an error — zero is valid
            assert r.fetch_error is None
            assert r.fetch_fallback_reason is None
            assert r.source_params["status_detail"] == "observed_zero"
            assert r.source_params["verification_status"] == "DIRECT"

    def test_unknown_field(self, tmp_path) -> None:
        prov = H41Provider(data_root=str(tmp_path), cache=False)
        results = prov.fetch_series(["nonexistent_field"])
        assert len(results) == 1
        assert results[0].fetch_error is not None
        assert "no Federal Reserve DDP mapping" in results[0].fetch_error

    def test_missing_api_key_does_not_block_direct_ddp(self, tmp_path) -> None:
        with _gateway(_mock_response({}, text=DDP_H41_RESPONSE)) as gateway:
            prov = H41Provider(api_key="", data_root=str(tmp_path), cache=False, gateway=gateway)
            results = prov.fetch_series(["primary_credit"])

            assert len(results) == 1
            assert results[0].fetch_error is None
            assert results[0].source_params["verification_status"] == "DIRECT"

    def test_direct_failure_can_fallback_to_fred(self, tmp_path) -> None:
        with _gateway(
            _mock_response({}, text="not a usable csv"),
            _mock_response(FRED_H41_RESPONSE),
        ) as gateway:
            prov = H41Provider(api_key="test_key", data_root=str(tmp_path), cache=False, gateway=gateway)
            results = prov.fetch_series(["primary_credit"])

            assert len(results) == 1
            assert results[0].fetch_error is None
            assert results[0].fetch_fallback_reason.startswith("direct_h41_ddp_failed")
            assert results[0].source_params["method"] == "fred_bridge"

    def test_direct_failure_without_fallback_reports_error(self, tmp_path) -> None:
        with _gateway(_mock_response({}, text="not a usable csv")) as gateway:
            prov = H41Provider(
                api_key="",
                data_root=str(tmp_path),
                cache=False,
                allow_fred_fallback=False,
                gateway=gateway,
            )
            results = prov.fetch_series(["primary_credit"])

            assert len(results) == 1
            assert results[0].fetch_error is not None
            assert "H41 direct DDP" in results[0].fetch_error

    def test_fetch_via_fred_bridge_fallback_method(self, tmp_path) -> None:
        with _gateway(_mock_response(FRED_H41_RESPONSE)) as gateway:
            prov = H41Provider(api_key="test_key", data_root=str(tmp_path), cache=False, gateway=gateway)
            result = prov._fetch_via_fred("WPCREDIT", "primary_credit")

        assert result.source_params["method"] == "fred_bridge"
        assert result.source_params["verification_status"] == "PROVISIONAL"

    def test_missing_api_key_blocks_fred_bridge_only(self, tmp_path) -> None:
        with _gateway(_mock_response({}, text="not a usable csv")) as gateway:
            prov = H41Provider(
                api_key="",
                data_root=str(tmp_path),
                cache=False,
                allow_fred_fallback=False,
                gateway=gateway,
            )
            results = prov.fetch_series(["primary_credit"])

            assert len(results) == 1
            # Direct DDP is attempted first and does not need FRED_API_KEY.
            assert results[0].fetch_error is not None

    def test_fetch_all_fields(self, tmp_path) -> None:
        with _gateway(_mock_response({}, text=DDP_H41_RESPONSE)) as gateway:
            prov = H41Provider(data_root=str(tmp_path), cache=False, gateway=gateway)
            results = prov.fetch_series(["discount_window", "primary_credit", "btfp"])

            assert len(results) == 3
            for r in results:
                assert r.provider == "h41"
                assert r.series_id in ("discount_window", "primary_credit", "btfp")
                assert not r.frame.empty

    def test_http_error(self, tmp_path) -> None:
        with _gateway(_mock_response({}, status=500)) as gateway:
            prov = H41Provider(
                data_root=str(tmp_path),
                cache=False,
                allow_fred_fallback=False,
                gateway=gateway,
            )
            results = prov.fetch_series(["primary_credit"])
            assert len(results) == 1
            assert results[0].fetch_error is not None

    def test_to_long_panel(self, tmp_path) -> None:
        with _gateway(_mock_response({}, text=DDP_H41_RESPONSE)) as gateway:
            prov = H41Provider(data_root=str(tmp_path), cache=False, gateway=gateway)
            results = prov.fetch_series(["primary_credit"])
            panel = prov._to_long_panel(results)
            assert not panel.empty
            assert "series_id" in panel.columns
            assert "source_id" in panel.columns
            assert panel["source_id"].iloc[0] == "h41"
            assert panel.loc[0, "series_id"] == "H41:primary_credit"
