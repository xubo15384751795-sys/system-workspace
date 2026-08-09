from __future__ import annotations

from dataclasses import dataclass
import time

import pandas as pd

from harvester.providers import build_provider
from harvester.providers.openbb_provider import OpenBBProvider


@dataclass
class FakeOBBResult:
    frame: pd.DataFrame

    def to_df(self) -> pd.DataFrame:
        return self.frame


class FakeFredSeries:
    def __call__(self, **kwargs):
        symbol = kwargs["symbol"]
        return FakeOBBResult(
            pd.DataFrame(
                {symbol: [18.5, 19.0]},
                index=pd.to_datetime(["2026-04-20", "2026-04-21"]),
            )
        )


class FakeHistorical:
    def __call__(self, **kwargs):
        assert kwargs["symbol"] == "^MOVE"
        return FakeOBBResult(
            pd.DataFrame(
                {
                    "date": ["2026-04-20", "2026-04-21"],
                    "open": [120.0, 121.0],
                    "close": [123.0, 124.0],
                }
            )
        )


class FakeEquityHistorical:
    def __call__(self, **kwargs):
        assert kwargs["symbol"] == "HYG"
        assert kwargs["provider"] == "tiingo"
        return FakeOBBResult(
            pd.DataFrame(
                {
                    "date": ["2026-04-20", "2026-04-21"],
                    "open": [78.0, 79.0],
                    "close": [78.5, 79.5],
                    "volume": [100, 200],
                }
            )
        )


class FakeOBB:
    class economy:
        fred_series = FakeFredSeries()

    class index:
        class price:
            historical = FakeHistorical()

    class equity:
        class price:
            historical = FakeEquityHistorical()


class SlowFredSeries:
    def __call__(self, **kwargs):
        time.sleep(0.15)
        return FakeOBBResult(pd.DataFrame({kwargs["symbol"]: [18.5]}))


class SlowOBB:
    class economy:
        fred_series = SlowFredSeries()


def test_openbb_fred_provider_normalizes_to_provider_native_identity(tmp_path) -> None:
    provider = OpenBBProvider(openbb_provider="fred", obb_client=FakeOBB(), data_root=tmp_path, cache=False)

    result = provider.fetch_series(["VIXCLS"])[0]

    assert result.fetch_error is None
    assert result.provider == "fred"
    assert result.series_id == "VIXCLS"
    assert result.source_url == "openbb:economy.fred_series"
    assert result.source_params["source_engine"] == "openbb"
    assert list(result.frame.columns) == [
        "date",
        "value",
        "unit",
        "frequency",
        "source_id",
        "source_series_id",
        "series_id",
    ]
    assert result.frame["source_id"].unique().tolist() == ["fred"]
    assert result.frame["source_series_id"].unique().tolist() == ["VIXCLS"]
    assert result.frame["series_id"].unique().tolist() == ["FRED:VIXCLS"]
    assert result.frame["value"].tolist() == [18.5, 19.0]


def test_openbb_endpoint_timeout_is_reported_as_provider_error(tmp_path) -> None:
    provider = OpenBBProvider(
        openbb_provider="fred",
        obb_client=SlowOBB(),
        data_root=tmp_path,
        cache=False,
        timeout_sec=0.02,
    )

    result = provider.fetch_series(["VIXCLS"])[0]

    assert result.frame.empty
    assert result.fetch_fallback_reason == "timeout"
    assert "timed out" in (result.fetch_error or "")


def test_openbb_yfinance_move_route_uses_close_value(tmp_path) -> None:
    provider = OpenBBProvider(openbb_provider="yfinance", obb_client=FakeOBB(), data_root=tmp_path, cache=False)

    result = provider.fetch_series(["MOVE"])[0]

    assert result.fetch_error is None
    assert result.provider == "yfinance"
    assert result.series_id == "^MOVE"
    assert result.frame["source_id"].unique().tolist() == ["yfinance"]
    assert result.frame["source_series_id"].unique().tolist() == ["^MOVE"]
    assert result.frame["value"].tolist() == [123.0, 124.0]


def test_openbb_tiingo_etf_route_uses_close_value(tmp_path) -> None:
    provider = OpenBBProvider(openbb_provider="tiingo", obb_client=FakeOBB(), data_root=tmp_path, cache=False)

    result = provider.fetch_series(["HYG"])[0]

    assert result.fetch_error is None
    assert result.provider == "tiingo"
    assert result.series_id == "HYG"
    assert result.frame["source_id"].unique().tolist() == ["tiingo"]
    assert result.frame["series_id"].unique().tolist() == ["TIINGO:HYG"]
    assert result.frame["value"].tolist() == [78.5, 79.5]


def test_openbb_unknown_route_returns_provider_result_error(tmp_path) -> None:
    provider = OpenBBProvider(openbb_provider="fred", obb_client=FakeOBB(), data_root=tmp_path, cache=False)

    result = provider.fetch_series(["NO_SUCH_ROUTE"])[0]

    assert result.fetch_error is not None
    assert result.fetch_fallback_reason == "unknown_route"
    assert result.frame.empty


def test_build_provider_supports_openbb_prefixes(tmp_path) -> None:
    provider = build_provider("openbb_fred", data_root=tmp_path, cache=False)

    assert isinstance(provider, OpenBBProvider)
    assert provider.openbb_provider == "fred"
