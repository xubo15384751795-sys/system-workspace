from __future__ import annotations

import logging
import os
import time
from typing import Any

import pandas as pd
import requests

from harvester.providers.base import OfficialProvider, ProviderResult

logger = logging.getLogger(__name__)

FRED_BASE = "https://api.stlouisfed.org/fred"


class FredProvider(OfficialProvider):
    source_id = "fred"

    def __init__(
        self,
        api_key: str = "",
        data_root: str = "",
        cache: bool = True,
        user_agent: str = "StructuralRiskHarvester/0.1.0",
    ) -> None:
        super().__init__(data_root=data_root, cache=cache, user_agent=user_agent)
        self._api_key = api_key or os.environ.get("FRED_API_KEY", "")
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": user_agent})
        self._session.trust_env = False  # 不使用环境变量中的代理

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
        # Prefer official fredapi client when installed; fall back to raw HTTP.
        sdk_result = self._fetch_one_fredapi(series_id)
        if sdk_result is not None:
            return sdk_result
        return self._fetch_one_http(series_id)

    def _fetch_one_fredapi(self, series_id: str) -> ProviderResult | None:
        try:
            from fredapi import Fred
        except ImportError:
            return None
        try:
            fred = Fred(api_key=self._api_key)
            series = fred.get_series(series_id)
        except Exception as exc:  # noqa: BLE001 — provider boundary
            logger.warning("fredapi failed for %s (%s); falling back to HTTP", series_id, exc)
            return None
        if series is None or len(series) == 0:
            return self._build_error_result(series_id, "no observations returned", "empty")
        rows: list[dict[str, Any]] = []
        for ts, val in series.items():
            if val is None or (isinstance(val, float) and pd.isna(val)):
                continue
            try:
                numeric = float(val)
            except (ValueError, TypeError):
                continue
            date_val = ts.date().isoformat() if hasattr(ts, "date") else str(ts)[:10]
            rows.append({
                "date": date_val,
                "value": numeric,
                "unit": "",
                "frequency": "",
            })
        if not rows:
            return self._build_error_result(series_id, "all values unparseable", "empty")
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        if self._cache:
            self._write_raw(series_id, df.to_csv(index=False).encode("utf-8"))
        return ProviderResult(
            provider=self.source_id,
            series_id=series_id,
            frame=df,
            source_url=f"{FRED_BASE}/series/observations",
            source_params={"series_id": series_id, "client": "fredapi"},
        )

    def _fetch_one_http(self, series_id: str) -> ProviderResult:
        url = f"{FRED_BASE}/series/observations"
        params = {
            "series_id": series_id,
            "api_key": self._api_key,
            "file_type": "json",
            "sort_order": "asc",
        }
        try:
            resp = self._session.get(url, params=params, timeout=30)
            if resp.status_code == 400 and "Bad Request" in resp.text:
                return self._build_error_result(
                    series_id, f"FRED returned 400 for {series_id}", "invalid_series"
                )
            resp.raise_for_status()
            data = resp.json()
            raw_bytes = resp.content
        except requests.exceptions.HTTPError as exc:
            msg = f"FRED HTTP {exc.response.status_code if exc.response else '?'} for {series_id}"
            logger.warning(msg)
            return self._build_error_result(series_id, msg, "http_error")
        except requests.exceptions.RequestException as exc:
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
