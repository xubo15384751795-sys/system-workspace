from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from harvester.http_gateway import GatewayError, GatewayHTTPError, OwnedHTTPGateway
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
        gateway: OwnedHTTPGateway | None = None,
    ) -> None:
        super().__init__(data_root=data_root, cache=cache, user_agent=user_agent)
        self._gateway = gateway or OwnedHTTPGateway(headers={"User-Agent": user_agent})

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
        endpoint_id = dataset if dataset in {"debt_to_penny", "daily_treasury_statement"} else None
        if endpoint_id is None:
            return self._build_error_result(
                series_id, f"unknown dataset: {dataset}", "unknown_dataset"
            )
        url = (
            f"{TREASURY_BASE}/v2/accounting/od/debt_to_penny"
            if endpoint_id == "debt_to_penny"
            else f"{TREASURY_BASE}/v1/accounting/dts/operating_cash_balance"
        )

        date_field_map = {
            "debt_to_penny": "record_date",
            "daily_treasury_statement": "record_date",
        }
        date_field = date_field_map.get(dataset, "record_date")

        params = {
            "fields": f"{date_field},{field}",
            "sort": date_field,
            "page[size]": 10000,
        }

        try:
            resp = self._gateway.fetch("treasury", endpoint_id, params)
            resp.raise_for_status()
            data = resp.json()
            raw_bytes = resp.content
        except GatewayHTTPError as exc:
            msg = f"Treasury HTTP {exc.status_code} for {series_id}"
            logger.warning(msg)
            return self._build_error_result(series_id, msg, "http_error")
        except GatewayError as exc:
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
