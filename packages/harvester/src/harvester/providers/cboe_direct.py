from __future__ import annotations

from dataclasses import dataclass
from io import StringIO
from typing import Any

import pandas as pd
import requests

from harvester.providers.base import OfficialProvider, ProviderResult


@dataclass(frozen=True)
class CboeDirectRoute:
    series_id: str
    symbol: str
    csv_value_column: str
    unit: str = "index"
    frequency: str = "daily"
    intraday: bool = False


DEFAULT_CBOE_ROUTES: dict[str, CboeDirectRoute] = {
    "VIXCLS": CboeDirectRoute("VIXCLS", "VIX", "CLOSE", intraday=True),
    "VIX": CboeDirectRoute("VIX", "VIX", "CLOSE"),
    "VVIX": CboeDirectRoute("VVIX", "VVIX", "VVIX"),
    "SKEW": CboeDirectRoute("SKEW", "SKEW", "SKEW"),
    "MOVE": CboeDirectRoute("MOVE", "VXTLT", "VXTLT"),
    "TYVIX": CboeDirectRoute("TYVIX", "TYVIX", "CLOSE"),
    "VXTLT": CboeDirectRoute("VXTLT", "VXTLT", "VXTLT"),
    "VIX3M": CboeDirectRoute("VIX3M", "VIX3M", "CLOSE"),
    "VIX9D": CboeDirectRoute("VIX9D", "VIX9D", "CLOSE"),
    "VIX6M": CboeDirectRoute("VIX6M", "VIX6M", "CLOSE"),
    "SPX": CboeDirectRoute("SPX", "SPX", "CLOSE"),
}


class CboeDirectProvider(OfficialProvider):
    """Direct public CBOE acquisition for volatility index series.

    CSV endpoints provide same-day EOD history. The delayed quote JSON endpoint
    provides intraday observations for supported symbols without an API key.
    """

    source_id = "cboe"

    def __init__(
        self,
        *,
        route_map: dict[str, CboeDirectRoute] | None = None,
        data_root: str = "",
        cache: bool = True,
        user_agent: str = "StructuralRiskHarvester/0.1.0",
        **_: Any,
    ) -> None:
        super().__init__(data_root=data_root, cache=cache, user_agent=user_agent)
        self._route_map = route_map or DEFAULT_CBOE_ROUTES
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": user_agent})

    def fetch_series(self, series_ids: list[str]) -> list[ProviderResult]:
        return [self._fetch_one(series_id) for series_id in series_ids]

    def _fetch_one(self, series_id: str) -> ProviderResult:
        route = self._route_map.get(series_id)
        if route is None:
            return self._build_error_result(series_id, "no CBOE direct route registered", "unknown_route")

        try:
            if route.intraday:
                return self._fetch_intraday(route)
            return self._fetch_eod(route)
        except requests.exceptions.RequestException as exc:
            return self._build_error_result(series_id, f"CBOE network error: {exc}", "network_error")
        except Exception as exc:
            return self._build_error_result(series_id, f"CBOE parse error: {exc}", "parse_error")

    def _fetch_eod(self, route: CboeDirectRoute) -> ProviderResult:
        url = _csv_url(route.symbol)
        resp = self._session.get(url, timeout=30)
        resp.raise_for_status()
        if self._cache:
            self._write_raw(route.series_id, resp.text)
        panel = _csv_to_panel(resp.text, route)
        if panel.empty:
            return self._build_error_result(route.series_id, "CBOE CSV returned no usable rows", "empty")
        return ProviderResult(
            provider=self.source_id,
            series_id=route.series_id,
            frame=panel,
            source_url=url,
            source_params={"endpoint_family": "daily_prices_csv", "symbol": route.symbol},
            data_note="Direct CBOE EOD CSV; no API key.",
        )

    def _fetch_intraday(self, route: CboeDirectRoute) -> ProviderResult:
        url = _intraday_url(route.symbol)
        resp = self._session.get(url, timeout=30)
        resp.raise_for_status()
        if self._cache:
            self._write_raw(f"{route.series_id}_intraday", resp.text)
        panel = _json_to_panel(resp.json(), route)
        if panel.empty:
            return self._fetch_eod(route)
        return ProviderResult(
            provider=self.source_id,
            series_id=route.series_id,
            frame=panel,
            source_url=url,
            source_params={"endpoint_family": "delayed_quotes_json", "symbol": f"_{route.symbol}"},
            data_note="Direct CBOE delayed quote JSON; approximately 15-minute delayed during market hours.",
        )


def _csv_url(symbol: str) -> str:
    return f"https://cdn.cboe.com/api/global/us_indices/daily_prices/{symbol}_History.csv"


def _intraday_url(symbol: str) -> str:
    return f"https://cdn.cboe.com/api/global/delayed_quotes/quotes/_{symbol}.json"


def _csv_to_panel(text: str, route: CboeDirectRoute) -> pd.DataFrame:
    frame = pd.read_csv(StringIO(text))
    date_col = _first_matching(frame, ("DATE", "Date", "date"))
    value_col = _first_matching(frame, (route.csv_value_column, route.symbol, route.symbol.upper(), "CLOSE", "Close"))
    if date_col is None or value_col is None:
        return pd.DataFrame()
    return _panel(
        dates=pd.to_datetime(frame[date_col], errors="coerce"),
        values=pd.to_numeric(frame[value_col], errors="coerce"),
        route=route,
    )


def _json_to_panel(payload: dict[str, Any], route: CboeDirectRoute) -> pd.DataFrame:
    data = payload.get("data", {})
    if not isinstance(data, dict):
        return pd.DataFrame()
    stamp = data.get("last_trade_time") or payload.get("timestamp")
    value = data.get("last") or data.get("current_price") or data.get("close")
    return _panel(
        dates=pd.to_datetime(pd.Series([stamp]), errors="coerce"),
        values=pd.to_numeric(pd.Series([value]), errors="coerce"),
        route=route,
    )


def _panel(dates: pd.Series, values: pd.Series, route: CboeDirectRoute) -> pd.DataFrame:
    out = pd.DataFrame(
        {
            "date": dates,
            "value": values,
            "unit": route.unit,
            "frequency": "intraday_delayed" if route.intraday and len(values) == 1 else route.frequency,
            "source_id": "cboe",
            "source_series_id": route.symbol,
            "series_id": f"CBOE:{route.series_id}",
        }
    )
    return out.dropna(subset=["date", "value"]).sort_values("date").reset_index(drop=True)


def _first_matching(frame: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    columns = {str(c).lower(): str(c) for c in frame.columns}
    for candidate in candidates:
        match = columns.get(str(candidate).lower())
        if match is not None:
            return match
    return None


__all__ = ["CboeDirectProvider", "CboeDirectRoute", "DEFAULT_CBOE_ROUTES"]
