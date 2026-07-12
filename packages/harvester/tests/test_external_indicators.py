from __future__ import annotations

from unittest.mock import MagicMock, patch

from harvester.providers.external_indicators import (
    CISS,
    NYFED_PD_TREASURY_NET,
    external_series_to_long_panel,
    fetch_external_indicator,
    write_template_csv,
)


def test_fetch_external_indicator_uses_cached_csv(tmp_path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "ciss.csv").write_text("TIME_PERIOD,OBS_VALUE\n2024-01-01,0.5\n", encoding="utf-8")

    series = fetch_external_indicator(CISS, cache_dir=cache)

    assert series.name == "CISS"
    assert series.iloc[-1] == 0.5


def test_fetch_external_indicator_downloads_and_caches(tmp_path) -> None:
    response = MagicMock()
    response.text = "TIME_PERIOD,OBS_VALUE\n2024-01-01,0.7\n"
    response.raise_for_status = MagicMock()
    with patch("requests.get", return_value=response) as get:
        series = fetch_external_indicator(CISS, cache_dir=tmp_path)

    assert series.iloc[-1] == 0.7
    assert (tmp_path / "ciss.csv").exists()
    assert get.called


def test_external_series_to_long_panel(tmp_path) -> None:
    (tmp_path / "ciss.csv").write_text("TIME_PERIOD,OBS_VALUE\n2024-01-01,0.5\n", encoding="utf-8")
    series = fetch_external_indicator(CISS, cache_dir=tmp_path)

    panel = external_series_to_long_panel({"CISS": series}, vintage_date="2026-05-05")

    assert list(panel["series_id"].unique()) == ["CISS"]
    assert list(panel["source_id"].unique()) == ["external_public"]
    assert panel["value"].iloc[0] == 0.5


def test_write_template_csv(tmp_path) -> None:
    path = write_template_csv("CISS", cache_dir=tmp_path)

    assert path.exists()
    assert "TIME_PERIOD" in path.read_text(encoding="utf-8")


def test_nyfed_json_cache_is_normalized_to_csv(tmp_path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    raw = (
        '{"pd":{"timeseries":['
        '{"asofdate":"2013-04-03","keyid":"PDPOSGST-TOT","value":"108014"},'
        '{"asofdate":"2013-04-10","keyid":"PDPOSGST-TOT","value":"137924"}'
        "]}}"
    )
    path = cache / "nyfed_pd_treasury_net.csv"
    path.write_text(raw, encoding="utf-8")

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
        "CISS.D,D,U2,2020-01-03,0.12\n"
    )
    path = cache / "ciss.csv"
    path.write_text(raw, encoding="utf-8")

    series = fetch_external_indicator(CISS, cache_dir=cache)
    healed = path.read_text(encoding="utf-8")
    assert len(series) == 2
    assert healed.lstrip().startswith("TIME_PERIOD")
    assert "KEY,FREQ" not in healed.splitlines()[0]
