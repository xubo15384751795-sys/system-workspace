from __future__ import annotations

from unittest.mock import MagicMock, patch

from harvester.providers.external_indicators import (
    CISS,
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
