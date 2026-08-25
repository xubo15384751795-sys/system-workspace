from __future__ import annotations

from datetime import date
from io import BytesIO
from unittest.mock import patch

import pandas as pd

from harvester.ingestion.dlt_observation import load_capture_manifest, payload_sha256
from harvester.official import build_complete_benchmark_panel
from harvester.providers.external_indicators import (
    CISS,
    COVAR,
    CFTC_TFF_LEV_SP,
    EXTERNAL_INDICATOR_MAX_RESPONSE_BYTES,
    FINRA_MARGIN_DEBT,
    NYFED_PD_TREASURY_NET,
    OFR_FSI,
    SRISK,
    _parse_ciss_csv,
    _parse_cftc_tff_lev_sp,
    _parse_finra_margin_debt,
    external_series_to_long_panel,
    fetch_all_external,
    fetch_external_indicator,
    write_template_csv,
)
import harvester.providers.external_indicators as external_module

# Cache fixtures must be current-dated: a cache older than the freshness
# budget is deliberately re-downloaded, which would make these tests hit the
# network and assert against live publisher data.
TODAY = date.today().isoformat()


def test_fetch_external_indicator_uses_cached_csv(tmp_path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "ciss.csv").write_text(f"TIME_PERIOD,OBS_VALUE\n{TODAY},0.5\n", encoding="utf-8")

    with patch("harvester.providers.external_indicators._download") as download:
        series = fetch_external_indicator(CISS, cache_dir=cache)

    assert series.name == "CISS"
    assert series.iloc[-1] == 0.5
    assert not download.called


def test_external_gateway_has_bounded_large_sdmx_budget(tmp_path, monkeypatch) -> None:
    created = []

    class _Gateway:
        def __init__(self, **kwargs):
            created.append(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def fetch(self, *_args, **_kwargs):
            raise RuntimeError("publisher unavailable")

    monkeypatch.setattr(external_module, "OwnedHTTPGateway", _Gateway)
    # CISS is stale, so the provider must construct its bounded gateway and
    # then fall back to the cache rather than disabling the byte guard.
    cache = tmp_path / "external_indicators"
    cache.mkdir()
    (cache / "ciss.csv").write_text(
        "TIME_PERIOD,OBS_VALUE\n2024-01-01,0.5\n", encoding="utf-8"
    )
    fetch_external_indicator(CISS, cache_dir=cache, refresh=True)
    assert created
    assert created[0]["max_response_bytes"] == EXTERNAL_INDICATOR_MAX_RESPONSE_BYTES


def test_stale_cache_is_refreshed_and_history_is_preserved(tmp_path) -> None:
    """A cache past its freshness budget must be re-fetched, and the download
    must extend the archived history rather than truncate it."""
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "ciss.csv").write_text(
        "TIME_PERIOD,OBS_VALUE\n1980-01-03,0.1\n2024-01-01,0.5\n", encoding="utf-8"
    )

    # Publisher serves only a short rolling window.
    with patch(
        "harvester.providers.external_indicators._download",
        return_value=f"TIME_PERIOD,OBS_VALUE\n{TODAY},0.9\n",
    ) as download:
        series = fetch_external_indicator(CISS, cache_dir=cache)

    assert download.called
    assert series.iloc[-1] == 0.9
    # Pre-existing history survives the refresh.
    assert series.iloc[0] == 0.1
    assert len(series) == 3
    assert "1980-01-03" in (cache / "ciss.csv").read_text(encoding="utf-8")


def test_stale_cache_falls_back_when_publisher_is_unreachable(tmp_path) -> None:
    """OFR_FSI is network-blocked from some hosts; a failed refresh must still
    serve the cache instead of raising."""
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "ciss.csv").write_text("TIME_PERIOD,OBS_VALUE\n2024-01-01,0.5\n", encoding="utf-8")

    with patch(
        "harvester.providers.external_indicators._download",
        side_effect=OSError("publisher unreachable"),
    ):
        series = fetch_external_indicator(CISS, cache_dir=cache)

    assert series.iloc[-1] == 0.5


def test_fetch_external_indicator_downloads_and_caches(tmp_path) -> None:
    with patch(
        "harvester.providers.external_indicators._download",
        return_value="TIME_PERIOD,OBS_VALUE\n2024-01-01,0.7\n",
    ) as download:
        series = fetch_external_indicator(CISS, cache_dir=tmp_path)

    assert series.iloc[-1] == 0.7
    assert (tmp_path / "ciss.csv").exists()
    assert download.called

    manifest = load_capture_manifest(
        tmp_path / "external_indicators.capture.json",
        expected_provider="external_indicators",
    )
    assert manifest["capture_kind"] == "daily_provider_capture"
    assert manifest["payload_digests"]["CISS"] == payload_sha256(tmp_path / "ciss.csv")


def test_unparseable_refresh_does_not_overwrite_valid_cache(tmp_path) -> None:
    cache = tmp_path / "ciss.csv"
    original = f"TIME_PERIOD,OBS_VALUE\n{TODAY},0.5\n"
    cache.write_text(original, encoding="utf-8")

    with patch(
        "harvester.providers.external_indicators._download",
        return_value="not,a,CISS,response\nthis,is,not,parseable\n",
    ):
        series = fetch_external_indicator(CISS, cache_dir=tmp_path, refresh=True)

    assert series.iloc[-1] == 0.5
    assert cache.read_text(encoding="utf-8") == original


def test_cftc_refresh_preserves_publisher_schema_for_its_parser(tmp_path) -> None:
    text = (
        "report_date_as_yyyy_mm_dd,market_and_exchange_names,"
        "lev_money_positions_long,lev_money_positions_short\n"
        f"{TODAY},E-MINI S&P 500,100,40\n"
    )

    with patch(
        "harvester.providers.external_indicators._download",
        return_value=text,
    ):
        series = fetch_external_indicator(
            CFTC_TFF_LEV_SP,
            cache_dir=tmp_path,
            refresh=True,
        )

    cache_text = (tmp_path / "cftc_tff_lev_sp.csv").read_text(encoding="utf-8")
    assert series.iloc[-1] == 60
    assert _parse_cftc_tff_lev_sp(cache_text).iloc[-1] == 60
    assert "lev_money_positions_long" in cache_text

    manifest = load_capture_manifest(
        tmp_path / "cftc_tff_lev_sp.capture.json",
        expected_provider="cftc",
    )
    assert manifest["payload_sha256"] == payload_sha256(
        tmp_path / "cftc_tff_lev_sp.csv"
    )


def test_cftc_socrata_json_is_parsed_and_cached_as_validated_csv(tmp_path) -> None:
    payload = (
        "[{\"report_date_as_yyyy_mm_dd\":\"2026-08-14\","
        "\"market_and_exchange_names\":\"E-MINI S&P 500\","
        "\"lev_money_positions_long\":\"125\","
        "\"lev_money_positions_short\":\"40\"}]"
    )
    with patch(
        "harvester.providers.external_indicators._download",
        return_value=payload,
    ):
        series = fetch_external_indicator(CFTC_TFF_LEV_SP, cache_dir=tmp_path, refresh=True)

    assert series.iloc[-1] == 85
    cached = (tmp_path / "cftc_tff_lev_sp.csv").read_text(encoding="utf-8")
    assert cached.startswith("report_date_as_yyyy_mm_dd")
    assert _parse_cftc_tff_lev_sp(cached).iloc[-1] == 85


def test_cftc_parser_excludes_micro_e_mini_match(tmp_path) -> None:
    payload = (
        "[{\"report_date_as_yyyy_mm_dd\":\"2026-08-14\","
        "\"market_and_exchange_names\":\"E-MINI S&P 500 - CME\","
        "\"lev_money_positions_long\":\"125\",\"lev_money_positions_short\":\"40\"},"
        "{\"report_date_as_yyyy_mm_dd\":\"2026-08-14\","
        "\"market_and_exchange_names\":\"MICRO E-MINI S&P 500 INDEX - CME\","
        "\"lev_money_positions_long\":\"999\",\"lev_money_positions_short\":\"1\"}]"
    )

    assert _parse_cftc_tff_lev_sp(payload).iloc[-1] == 85


def test_invalid_cftc_json_does_not_overwrite_valid_cache(tmp_path) -> None:
    cache = tmp_path / "cftc_tff_lev_sp.csv"
    original = f"report_date_as_yyyy_mm_dd,market_and_exchange_names,lev_money_positions_long,lev_money_positions_short\n{TODAY},E-MINI S&P 500,100,40\n"
    cache.write_text(original, encoding="utf-8")

    with patch(
        "harvester.providers.external_indicators._download",
        return_value="{not valid json",
    ):
        series = fetch_external_indicator(CFTC_TFF_LEV_SP, cache_dir=tmp_path, refresh=True)

    assert series.iloc[-1] == 60
    assert cache.read_text(encoding="utf-8") == original


def test_finra_official_xlsx_is_validated_then_normalized(tmp_path) -> None:
    workbook = BytesIO()
    pd.DataFrame(
        {
            "Year-Month": ["2026-07"],
            "Debit Balances in Customers' Securities Margin Accounts": [1417225],
        }
    ).to_excel(workbook, index=False)

    with patch(
        "harvester.providers.external_indicators._download",
        return_value=workbook.getvalue(),
    ):
        series = fetch_external_indicator(FINRA_MARGIN_DEBT, cache_dir=tmp_path, refresh=True)

    assert _parse_finra_margin_debt(workbook.getvalue()).iloc[-1] == 1417225
    assert series.iloc[-1] == 1417225
    assert (tmp_path / "finra_margin_debt.csv").read_text(encoding="utf-8").startswith("Date,value")


def test_manual_sources_are_not_reported_as_transport_unavailable(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(external_module, "KNOWN_INDICATORS", (SRISK, COVAR))
    results = fetch_all_external(cache_dir=tmp_path, refresh=True)

    assert "SRISK" not in results
    assert "COVAR" not in results
    assert "__errors__" not in results


def test_fetch_all_external_writes_one_capture_manifest_for_fresh_series(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(external_module, "KNOWN_INDICATORS", (CISS,))
    with patch(
        "harvester.providers.external_indicators._download",
        return_value="TIME_PERIOD,OBS_VALUE\n2024-01-01,0.7\n",
    ):
        results = fetch_all_external(cache_dir=tmp_path, refresh=True)

    assert results["CISS"].iloc[-1] == 0.7
    manifest = load_capture_manifest(
        tmp_path / "external_indicators.capture.json",
        expected_provider="external_indicators",
    )
    assert manifest["payload_digests"]["CISS"] == payload_sha256(tmp_path / "ciss.csv")


def test_direct_provider_calls_merge_same_day_capture_context(tmp_path) -> None:
    with patch(
        "harvester.providers.external_indicators._download",
        side_effect=[
            "TIME_PERIOD,OBS_VALUE\n2024-01-01,0.7\n",
            "Date,OFR FSI\n2024-01-01,-1.5\n",
        ],
    ):
        fetch_external_indicator(CISS, cache_dir=tmp_path, refresh=True)
        fetch_external_indicator(OFR_FSI, cache_dir=tmp_path, refresh=True)

    manifest = load_capture_manifest(
        tmp_path / "external_indicators.capture.json",
        expected_provider="external_indicators",
    )
    assert set(manifest["payload_digests"]) == {"CISS", "OFR_FSI"}
    assert manifest["payload_digests"]["CISS"] == payload_sha256(tmp_path / "ciss.csv")
    assert manifest["payload_digests"]["OFR_FSI"] == payload_sha256(
        tmp_path / "ofr_fsi.csv"
    )


def test_external_endpoint_identity_uses_real_publisher_authority(tmp_path) -> None:
    calls: list[tuple[str, str]] = []

    class Gateway:
        def fetch(self, provider: str, endpoint_id: str, *_args, **_kwargs):
            calls.append((provider, endpoint_id))

            class Response:
                text = "TIME_PERIOD,OBS_VALUE\n2026-08-19,0.7\n"

                def raise_for_status(self):
                    return None

            return Response()

    series = fetch_external_indicator(CISS, cache_dir=tmp_path, gateway=Gateway())

    assert series.iloc[-1] == 0.7
    assert calls == [("ecb", "CISS")]
    assert all(provider != "external_public" for provider, _ in calls)


def test_external_series_to_long_panel(tmp_path) -> None:
    (tmp_path / "ciss.csv").write_text(f"TIME_PERIOD,OBS_VALUE\n{TODAY},0.5\n", encoding="utf-8")
    with patch("harvester.providers.external_indicators._download"):
        series = fetch_external_indicator(CISS, cache_dir=tmp_path)

    panel = external_series_to_long_panel({"CISS": series}, vintage_date="2026-05-05")

    assert list(panel["series_id"].unique()) == ["CISS"]
    assert list(panel["source_id"].unique()) == ["ecb"]
    assert panel["value"].iloc[0] == 0.5


def test_ciss_external_panel_is_retained_by_complete_benchmark_panel() -> None:
    series = pd.Series(
        [0.11, 0.12],
        index=pd.to_datetime(["2026-08-14", "2026-08-15"]),
        name="CISS",
    )
    external = external_series_to_long_panel({"CISS": series}, vintage_date="2026-08-18")
    empty_acquired = pd.DataFrame(
        columns=[
            "date",
            "series_id",
            "source_id",
            "source_series_id",
            "value",
            "unit",
            "frequency",
            "vintage_date",
            "quality_flag",
        ]
    )

    combined = build_complete_benchmark_panel(
        empty_acquired,
        external_indicators=external,
    )

    assert int((combined["series_id"] == "CISS").sum()) == 2


def test_write_template_csv(tmp_path) -> None:
    path = write_template_csv("CISS", cache_dir=tmp_path)

    assert path.exists()
    assert "TIME_PERIOD" in path.read_text(encoding="utf-8")


def test_ofr_fsi_publisher_url_is_csv_export() -> None:
    """HTML landing page is not parseable; download must hit fsi.csv."""
    assert OFR_FSI.publisher_url.endswith("/financial-stress-index/data/fsi.csv")


def test_ofr_fsi_cache_keeps_date_ofr_schema(tmp_path) -> None:
    with patch(
        "harvester.providers.external_indicators._download",
        return_value=f"Date,OFR FSI\n{TODAY},-1.5\n",
    ):
        series = fetch_external_indicator(OFR_FSI, cache_dir=tmp_path, refresh=True)

    assert series.iloc[-1] == -1.5
    cached = (tmp_path / "ofr_fsi.csv").read_text(encoding="utf-8")
    assert cached.splitlines()[0] == "date,OFR_FSI"


def test_nyfed_json_cache_is_normalized_to_csv(tmp_path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    raw = (
        '{"pd":{"timeseries":['
        '{"asofdate":"2013-04-03","keyid":"PDPOSGST-TOT","value":"108014"},'
        f'{{"asofdate":"{TODAY}","keyid":"PDPOSGST-TOT","value":"137924"}}'
        "]}}"
    )
    path = cache / "nyfed_pd_treasury_net.csv"
    path.write_text(raw, encoding="utf-8")

    with patch("harvester.providers.external_indicators._download"):
        series = fetch_external_indicator(NYFED_PD_TREASURY_NET, cache_dir=cache)
    healed = path.read_text(encoding="utf-8")
    assert len(series) == 2
    assert healed.lstrip().startswith("Date")
    assert "108014" in healed
    assert not healed.lstrip().startswith("{")


def test_ciss_sdmx_cache_is_normalized_to_slim_csv(tmp_path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    raw = (
        "KEY,FREQ,REF_AREA,TIME_PERIOD,OBS_VALUE\n"
        "CISS.D,D,U2,2020-01-02,0.11\n"
        f"CISS.D,D,U2,{TODAY},0.12\n"
    )
    path = cache / "ciss.csv"
    path.write_text(raw, encoding="utf-8")

    with patch("harvester.providers.external_indicators._download"):
        series = fetch_external_indicator(CISS, cache_dir=cache)
    healed = path.read_text(encoding="utf-8")
    assert len(series) == 2
    assert healed.lstrip().startswith("TIME_PERIOD")
    assert "KEY,FREQ" not in healed.splitlines()[0]


def test_ciss_sdmx_generic_xml_is_parsed() -> None:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <message:GenericData xmlns:message="urn:sdmx:org.sdmx.infomodel v2_1"
                         xmlns:generic="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/data/generic">
      <message:DataSet>
        <generic:Series>
          <generic:SeriesKey>
            <generic:Value id="FREQ" value="D"/>
            <generic:Value id="REF_AREA" value="U2"/>
          </generic:SeriesKey>
          <generic:Obs>
            <generic:ObsDimension id="TIME_PERIOD" value="2026-08-14"/>
            <generic:ObsValue value="0.12"/>
          </generic:Obs>
          <generic:Obs>
            <generic:ObsDimension id="TIME_PERIOD" value="2026-08-15"/>
            <generic:ObsValue value="0.13"/>
          </generic:Obs>
        </generic:Series>
      </message:DataSet>
    </message:GenericData>
    """

    series = _parse_ciss_csv(xml)

    assert series.name == "CISS"
    assert list(series.index.strftime("%Y-%m-%d")) == ["2026-08-14", "2026-08-15"]
    assert list(series) == [0.12, 0.13]


def test_ciss_sdmx_generic_xml_rejects_entity_declarations() -> None:
    xml = "<!DOCTYPE foo [<!ENTITY xxe SYSTEM 'file:///etc/passwd'>]><GenericData/>"

    with patch("harvester.providers.external_indicators.ET.fromstring") as parse:
        try:
            _parse_ciss_csv(xml)
        except ValueError as exc:
            assert "entity" in str(exc).lower()
        else:  # pragma: no cover - defensive assertion for a negative test
            raise AssertionError("entity declaration should be rejected")
        parse.assert_not_called()
