from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import requests

from harvester.providers.base import OfficialProvider, ProviderResult

logger = logging.getLogger(__name__)

TREASURY_BASE = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"


class TreasuryProvider(OfficialProvider):
    source_id = "treasury"

    def __init__(
        self,
        api_key: str = "",
        data_root: str = "",
        cache: bool = True,
        user_agent: str = "StructuralRiskHarvester/0.1.0",
    ) -> None:
        super().__init__(data_root=data_root, cache=cache, user_agent=user_agent)
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": user_agent})
        self._session.trust_env = False  # 不使用环境变量中的代理

    def fetch_series(self, series_ids: list[str]) -> list[ProviderResult]:
        results: list[ProviderResult] = []
        for sid in series_ids:
            dataset, field = self._parse_series_id(sid)
            if not dataset or not field:
                results.append(
                    self._build_error_result(sid, f"invalid series_id format: {sid} (expected dataset:field)", "bad_format")
                )
                continue
            result = self._fetch_dataset_field(dataset, field, sid)
            results.append(result)
        return results

    def _parse_series_id(self, series_id: str) -> tuple[str, str]:
        if ":" in series_id:
            parts = series_id.split(":", 1)
            return parts[0], parts[1]
        return "", ""

    def _fetch_dataset_field(self, dataset: str, field: str, series_id: str) -> ProviderResult:
        endpoint_map = {
            "debt_to_penny": "/v2/accounting/od/debt_to_penny",
            "daily_treasury_statement": "/v1/accounting/dts/operating_cash_balance",
        }
        endpoint = endpoint_map.get(dataset)
        if not endpoint:
            return self._build_error_result(
                series_id, f"unknown dataset: {dataset}", "unknown_dataset"
            )

        date_field_map = {
            "debt_to_penny": "record_date",
            "daily_treasury_statement": "record_date",
        }
        date_field = date_field_map.get(dataset, "record_date")

        url = f"{TREASURY_BASE}{endpoint}"
        params = {
            "fields": f"{date_field},{field}",
            "sort": date_field,
            "page[size]": 10000,
        }

        try:
            resp = self._session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            raw_bytes = resp.content
        except requests.exceptions.HTTPError as exc:
            msg = f"Treasury HTTP {exc.response.status_code if exc.response else '?'} for {series_id}"
            logger.warning(msg)
            return self._build_error_result(series_id, msg, "http_error")
        except requests.exceptions.RequestException as exc:
            msg = f"Treasury network error for {series_id}: {exc}"
            logger.warning(msg)
            return self._build_error_result(series_id, msg, "network_error")

        if self._cache:
            key = series_id.replace(":", "_")
            self._write_raw(key, raw_bytes)

        observations = data.get("data", [])
        if not observations:
            return self._build_error_result(series_id, "no data returned", "empty")

        rows: list[dict[str, Any]] = []
        for obs in observations:
            date_val = obs.get(date_field, "")
            val = obs.get(field)
            if not date_val or val is None:
                continue
            try:
                numeric = float(str(val).replace(",", ""))
            except (ValueError, TypeError):
                continue
            rows.append({
                "date": str(date_val)[:10],
                "value": numeric,
                "unit": "usd",
                "frequency": "daily",
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
            source_params=params,
        )
