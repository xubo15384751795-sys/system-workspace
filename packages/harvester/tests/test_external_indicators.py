from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from harvester.providers.external_indicators import (
    CISS,
    NYFED_PD_TREASURY_NET,
    external_series_to_long_panel,
    fetch_external_indicator,
    write_template_csv,
)

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
    response = MagicMock()
    response.text = "TIME_PERIOD,OBS_VALUE\n2024-01-01,0.7\n"
    response.raise_for_status = MagicMock()
    with patch("requests.get", return_value=response) as get:
        series = fetch_external_indicator(CISS, cache_dir=tmp_path)

    assert series.iloc[-1] == 0.7
    assert (tmp_path / "ciss.csv").exists()
    assert get.called


def test_external_series_to_long_panel(tmp_path) -> None:
    (tmp_path / "ciss.csv").write_text(f"TIME_PERIOD,OBS_VALUE\n{TODAY},0.5\n", encoding="utf-8")
    with patch("harvester.providers.external_indicators._download"):
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
