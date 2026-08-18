from __future__ import annotations

import logging
import os
import time
from typing import Any

import pandas as pd

from harvester.http_gateway import (
    GatewayError,
    GatewayHTTPError,
    OwnedHTTPGateway,
)
from harvester.providers.base import OfficialProvider, ProviderResult

logger = logging.getLogger(__name__)

FRED_BASE = "https://api.stlouisfed.org/fred"
# DFF has a long daily history and its JSON response is larger than the
# generic provider gateway budget.  Keep the limit finite, but give this
# allowlisted endpoint enough room for the largest admitted FRED series.
FRED_MAX_RESPONSE_BYTES = 4_000_000


class FredProvider(OfficialProvider):
    source_id = "fred"

    def __init__(
        self,
        api_key: str = "",
        data_root: str = "",
        cache: bool = True,
        user_agent: str = "StructuralRiskHarvester/0.1.0",
        gateway: OwnedHTTPGateway | None = None,
    ) -> None:
        super().__init__(data_root=data_root, cache=cache, user_agent=user_agent)
        self._api_key = api_key or os.environ.get("FRED_API_KEY", "")
        self._gateway = gateway or OwnedHTTPGateway(
            headers={"User-Agent": user_agent},
            max_response_bytes=FRED_MAX_RESPONSE_BYTES,
        )

    def fetch_series(self, series_ids: list[str]) -> list[ProviderResult]:
        if not self._api_key:
            return [
                self._build_error_result(sid, "missing FRED_API_KEY", "no_api_key")
                for sid in series_ids
            ]

        results: list[ProviderResult] = []
        for sid in series_ids:
            result = self._fetch_one(sid)
            results.append(result)
            if sid != series_ids[-1]:
                time.sleep(0.25)  # rate limit courtesy
        return results

    def _fetch_one(self, series_id: str) -> ProviderResult:
        return self._fetch_one_http(series_id)

    def _fetch_one_http(self, series_id: str) -> ProviderResult:
        url = f"{FRED_BASE}/series/observations"
        params = {
            "series_id": series_id,
            "api_key": self._api_key,
            "file_type": "json",
            "sort_order": "asc",
        }
        try:
            resp = self._gateway.fetch("fred", "series_observations", params)
            if resp.status_code == 400 and "Bad Request" in resp.text:
                return self._build_error_result(
                    series_id, f"FRED returned 400 for {series_id}", "invalid_series"
                )
            resp.raise_for_status()
            data = resp.json()
            raw_bytes = resp.content
        except GatewayHTTPError as exc:
            msg = f"FRED HTTP {exc.status_code} for {series_id}"
            logger.warning(msg)
            return self._build_error_result(series_id, msg, "http_error")
        except GatewayError as exc:
            msg = f"FRED network error for {series_id}: {exc}"
            logger.warning(msg)
            return self._build_error_result(series_id, msg, "network_error")

        if self._cache:
            self._write_raw(series_id, raw_bytes)

        observations = data.get("observations", [])
        if not observations:
            return self._build_error_result(series_id, "no observations returned", "empty")

        rows: list[dict[str, Any]] = []
        for obs in observations:
            date_val = obs.get("date", "")
            val = obs.get("value", "")
            if not date_val or val == "." or val == "":
                continue
            try:
                numeric = float(val)
            except (ValueError, TypeError):
                continue
            rows.append({
                "date": date_val,
                "value": numeric,
                "unit": data.get("units", ""),
                "frequency": data.get("frequency", ""),
            })

        if not rows:
            return self._build_error_result(series_id, "all values unparseable", "empty")

        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        return ProviderResult(
            provider=self.source_id,
            series_id=series_id,
            frame=df,
            source_url=url,
            source_params={"series_id": series_id, "file_type": "json"},
        )
