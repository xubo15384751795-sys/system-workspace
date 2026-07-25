"""
LEGACY ACQUISITION SHIM.
retire_after: 2026-10-15
This module contains legacy public-provider acquisition logic retained for
backward compatibility.
New Deformation code must not import this module for provider acquisition.
New external data acquisition belongs in Structural Risk Harvester.
Deformation's official data boundary is src/data_access/, which consumes
Harvester-published admitted evidence releases.
Allowed temporary use:
- legacy replay
- old dashboard rendering
- compatibility tests
- migration support
Forbidden new use:
- new provider clients
- new API-key access
- new HTTP acquisition
- new raw provider cache logic
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from io import StringIO
import json
from pathlib import Path
import threading
import time
from typing import Any
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

from src.core.interfaces import DataSource
from src.data.paths import resolve_fred_cache_dir


DEFAULT_PROXY_SERIES_MAP: dict[str, list[str]] = {
    "M_PROXY": [
        "-FRED:T10Y2Y",
        "FRED:DFF",
    ],
    "D_PROXY": [
        "-FRED:BAMLH0A0HYM2",
        "-FRED:VIXCLS",
        "-H41:discount_window",
    ],
    "K_PROXY": [
        "FRED:VIXCLS",
        "TFD:debt_to_penny:tot_pub_debt_out_amt",
        "TFD:daily_treasury_statement:open_today_bal",
    ],
    "X_PROXY": [
        "H41:primary_credit",
        "H41:btfp",
        "SEC:0000072971",
    ],
}


def _now_perf() -> float:
    return time.perf_counter()


def _elapsed_ms(started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1000.0, 3)


def _safe_fetch_metadata(source: Any) -> dict[str, Any] | None:
    payload = getattr(source, "last_fetch_metadata", None)
    return dict(payload) if isinstance(payload, dict) else None


def _provider_from_series_id(series_id: str) -> str:
    if not isinstance(series_id, str) or ":" not in series_id:
        return "proxy"
    return str(series_id.split(":", 1)[0]).lower()


def _set_last_fetch_metadata(source: Any, payload: dict[str, Any]) -> None:
    source.last_fetch_metadata = payload


def _normalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    frame = frame.copy()
    frame.index = pd.to_datetime(frame.index, errors="coerce")
    frame = frame[~frame.index.isna()]
    return frame.sort_index()


def _empty_result() -> pd.DataFrame:
    return pd.DataFrame()


def _coerce_series(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def _extract_prefixed_series_ids(series_ids: list[str], prefix: str, allow_unprefixed: bool = False) -> dict[str, str]:
    normalized_prefix = f"{prefix.upper()}:"
    out: dict[str, str] = {}
    for sid in series_ids:
        if not isinstance(sid, str):
            continue
        if sid.upper().startswith(normalized_prefix):
            out[sid] = sid[len(normalized_prefix) :]
        elif allow_unprefixed and ":" not in sid:
            out[sid] = sid
    return out


@dataclass
class MockDataSource(DataSource):
    seed: int = 42

    def fetch(self, series_ids: list[str], start: str, end: str) -> pd.DataFrame:
        started_at = _now_perf()
        dates = pd.date_range(start=start, end=end, freq="W-MON")
        if len(dates) == 0:
            dates = pd.DatetimeIndex([pd.to_datetime(end)])
        rng = np.random.default_rng(self.seed)
        data = rng.standard_normal((len(dates), len(series_ids)))
        frame = pd.DataFrame(data=data, index=dates, columns=series_ids)
        _set_last_fetch_metadata(
            self,
            {
                "provider": "mock",
                "source_type": type(self).__name__,
                "request_count": len(series_ids),
                "request_keys": list(series_ids),
                "providers_touched": sorted({_provider_from_series_id(series_id) for series_id in series_ids}),
                "row_count": int(len(frame)),
                "column_count": int(len(frame.columns)),
                "success_count": len(series_ids),
                "failure_count": 0,
                "fallback_used": False,
                "latency_ms": _elapsed_ms(started_at),
                "lineage_mode": "mock",
            },
        )
        return frame

    def available_series(self) -> list[str]:
        return ["M_PROXY", "D_PROXY", "K_PROXY", "X_PROXY"]


class HTTPClient:
    def __init__(
        self,
        timeout_sec: int = 20,
        retries: int = 0,
        backoff_sec: float = 0.0,
        default_headers: dict[str, str] | None = None,
    ) -> None:
        self.timeout_sec = timeout_sec
        self.retries = max(0, int(retries))
        self.backoff_sec = max(0.0, float(backoff_sec))
        self.default_headers = default_headers or {}

    def get_json(self, url: str, headers: dict[str, str] | None = None) -> dict[str, Any] | list[Any]:
        return json.loads(self.get_text(url=url, headers=headers))

    def get_text(self, url: str, headers: dict[str, str] | None = None) -> str:
        all_headers = dict(self.default_headers)
        if headers:
            all_headers.update(headers)
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            req = Request(url=url, headers=all_headers, method="GET")
            try:
                with urlopen(req, timeout=self.timeout_sec) as resp:  # nosec B310
                    return resp.read().decode("utf-8")
            except Exception as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
                sleep_for = self.backoff_sec * (2**attempt)
                if sleep_for > 0:
                    time.sleep(sleep_for)
        if last_error is not None:
            raise last_error
        raise RuntimeError("HTTP request failed without an explicit error")


class FREDDataSource(DataSource):
    def __init__(
        self,
        api_key: str | None = None,
        fallback_seed: int = 42,
        http: HTTPClient | None = None,
        base_url: str = "https://api.stlouisfed.org/fred/series/observations",
        graph_url: str = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}",
        cache_dir: str | Path | None = None,
        max_workers: int = 6,
    ) -> None:
        self.api_key = api_key
        self._fallback = MockDataSource(seed=fallback_seed)
        self._http = http or HTTPClient()
        self._base_url = base_url
        self._graph_url = graph_url
        self._cache_dir = Path(cache_dir) if cache_dir is not None else resolve_fred_cache_dir()
        self._max_workers = max(1, int(max_workers))

    def fetch(self, series_ids: list[str], start: str, end: str) -> pd.DataFrame:
        started_at = _now_perf()
        requested = _extract_prefixed_series_ids(series_ids, prefix="FRED", allow_unprefixed=True)
        if not requested:
            _set_last_fetch_metadata(
                self,
                {
                    "provider": "fred",
                    "source_type": type(self).__name__,
                    "request_count": 0,
                    "request_keys": [],
                    "providers_touched": [],
                    "row_count": 0,
                    "column_count": 0,
                    "success_count": 0,
                    "failure_count": 0,
                    "fallback_used": False,
                    "latency_ms": _elapsed_ms(started_at),
                    "endpoint_family": "fred",
                },
            )
            return _empty_result()

        if not self.api_key:
            frame = self._fetch_graph_csv(requested=requested, start=start, end=end)
            _set_last_fetch_metadata(
                self,
                {
                    "provider": "fred",
                    "source_type": type(self).__name__,
                    "request_count": len(requested),
                    "request_keys": list(requested.keys()),
                    "providers_touched": ["fred"],
                    "row_count": int(len(frame)),
                    "column_count": int(len(frame.columns)),
                    "success_count": int(sum(1 for sid in requested if sid in frame.columns and frame[sid].notna().any())),
                    "failure_count": int(sum(1 for sid in requested if sid not in frame.columns or not frame[sid].notna().any())),
                    "fallback_used": False,
                    "latency_ms": _elapsed_ms(started_at),
                    "endpoint_family": "graph_csv",
                },
            )
            return frame

        frames_by_id: dict[str, pd.Series] = {}
        with ThreadPoolExecutor(max_workers=min(self._max_workers, len(requested))) as pool:
            futures = {
                pool.submit(self._fetch_observations_api_series, original_id, fred_series_id, start, end): original_id
                for original_id, fred_series_id in requested.items()
            }
            for future in as_completed(futures):
                original_id = futures[future]
                try:
                    series = future.result()
                except Exception:
                    continue
                if series is not None and not series.empty:
                    frames_by_id[original_id] = series

        if not frames_by_id:
            frame = self._fetch_graph_csv(requested=requested, start=start, end=end)
            _set_last_fetch_metadata(
                self,
                {
                    "provider": "fred",
                    "source_type": type(self).__name__,
                    "request_count": len(requested),
                    "request_keys": list(requested.keys()),
                    "providers_touched": ["fred"],
                    "row_count": int(len(frame)),
                    "column_count": int(len(frame.columns)),
                    "success_count": int(sum(1 for sid in requested if sid in frame.columns and frame[sid].notna().any())),
                    "failure_count": int(sum(1 for sid in requested if sid not in frame.columns or not frame[sid].notna().any())),
                    "fallback_used": True,
                    "latency_ms": _elapsed_ms(started_at),
                    "endpoint_family": "fred_api_to_graph_csv",
                },
            )
            return frame

        merged = pd.concat(frames_by_id.values(), axis=1)
        merged = _normalize_columns(merged)
        for sid in requested:
            if sid not in merged.columns:
                merged[sid] = np.nan
        frame = merged[list(requested.keys())]
        _set_last_fetch_metadata(
            self,
            {
                "provider": "fred",
                "source_type": type(self).__name__,
                "request_count": len(requested),
                "request_keys": list(requested.keys()),
                "providers_touched": ["fred"],
                "row_count": int(len(frame)),
                "column_count": int(len(frame.columns)),
                "success_count": len(frames_by_id),
                "failure_count": len(requested) - len(frames_by_id),
                "fallback_used": False,
                "latency_ms": _elapsed_ms(started_at),
                "endpoint_family": "fred_api",
            },
        )
        return frame

    def _fetch_observations_api_series(
        self,
        original_id: str,
        fred_series_id: str,
        start: str,
        end: str,
    ) -> pd.Series | None:
        query = urlencode(
            {
                "series_id": fred_series_id,
                "api_key": self.api_key,
                "file_type": "json",
                "observation_start": start,
                "observation_end": end,
            }
        )
        payload = self._http.get_json(f"{self._base_url}?{query}")
        observations = payload.get("observations", []) if isinstance(payload, dict) else []
        if not observations:
            return None

        rows: list[tuple[pd.Timestamp, float]] = []
        for obs in observations:
            raw_date = str(obs.get("date", ""))
            raw_value = str(obs.get("value", "."))
            if raw_value in {".", "nan", "NaN", "None", ""}:
                continue
            try:
                rows.append((pd.to_datetime(raw_date), float(raw_value)))
            except Exception:
                continue
        if not rows:
            return None
        return pd.Series(data=[v for _, v in rows], index=[d for d, _ in rows], name=original_id)

    def _fetch_graph_csv(
        self,
        requested: dict[str, str],
        start: str,
        end: str,
    ) -> pd.DataFrame:
        frames_by_id: dict[str, pd.Series] = {}
        with ThreadPoolExecutor(max_workers=min(self._max_workers, len(requested))) as pool:
            futures = {
                pool.submit(self._fetch_graph_csv_series, original_id, fred_series_id, start, end): original_id
                for original_id, fred_series_id in requested.items()
            }
            for future in as_completed(futures):
                original_id = futures[future]
                try:
                    series = future.result()
                except Exception:
                    continue
                if series is not None and not series.empty:
                    frames_by_id[original_id] = series

        if not frames_by_id:
            return self._fallback.fetch(series_ids=list(requested.keys()), start=start, end=end)

        merged = pd.concat(frames_by_id.values(), axis=1)
        merged = _normalize_columns(merged)
        for sid in requested:
            if sid not in merged.columns:
                merged[sid] = np.nan
        return merged[list(requested.keys())]

    def _fetch_graph_csv_series(
        self,
        original_id: str,
        fred_series_id: str,
        start: str,
        end: str,
    ) -> pd.Series | None:
        csv_text = self._read_graph_csv(fred_series_id)
        frame = pd.read_csv(StringIO(csv_text))
        if "observation_date" not in frame.columns or fred_series_id not in frame.columns:
            return None
        dates = pd.to_datetime(frame["observation_date"], errors="coerce")
        values = pd.to_numeric(frame[fred_series_id], errors="coerce")
        series = pd.Series(values.to_numpy(), index=dates, name=original_id).dropna()
        series = series[(series.index >= pd.to_datetime(start)) & (series.index <= pd.to_datetime(end))]
        return series if not series.empty else None

    def _read_graph_csv(self, fred_series_id: str) -> str:
        cache_path = self._cache_dir / f"{fred_series_id}.csv"
        if cache_path.exists():
            return cache_path.read_text(encoding="utf-8")
        csv_text = self._http.get_text(self._graph_url.format(series_id=quote(fred_series_id, safe="")))
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(csv_text, encoding="utf-8")
        return csv_text

    def available_series(self) -> list[str]:
        return [
            "FRED:BAMLH0A0HYM2",
            "FRED:VIXCLS",
            "FRED:DFF",
            "FRED:T10Y2Y",
            "M_PROXY",
            "D_PROXY",
            "K_PROXY",
            "X_PROXY",
        ]


class FederalReserveH41DataSource(DataSource):
    """H.4.1 weekly data adapter with CSV endpoint contract.

    series_ids format: H41:<column_name>
    """

    def __init__(
        self,
        csv_url: str,
        date_column: str = "date",
        fallback_seed: int = 42,
        http: HTTPClient | None = None,
    ) -> None:
        self.csv_url = csv_url
        self.date_column = date_column
        self._http = http or HTTPClient()
        self._fallback = MockDataSource(seed=fallback_seed)

    def fetch(self, series_ids: list[str], start: str, end: str) -> pd.DataFrame:
        started_at = _now_perf()
        requested = _extract_prefixed_series_ids(series_ids, prefix="H41")
        if not requested:
            _set_last_fetch_metadata(
                self,
                {
                    "provider": "fed_h41",
                    "source_type": type(self).__name__,
                    "request_count": 0,
                    "request_keys": [],
                    "providers_touched": [],
                    "row_count": 0,
                    "column_count": 0,
                    "success_count": 0,
                    "failure_count": 0,
                    "fallback_used": False,
                    "latency_ms": _elapsed_ms(started_at),
                },
            )
            return _empty_result()

        if not self.csv_url:
            frame = self._fallback.fetch(list(requested.keys()), start, end)
            _set_last_fetch_metadata(
                self,
                {
                    "provider": "fed_h41",
                    "source_type": type(self).__name__,
                    "request_count": len(requested),
                    "request_keys": list(requested.keys()),
                    "providers_touched": ["fed_h41"],
                    "row_count": int(len(frame)),
                    "column_count": int(len(frame.columns)),
                    "success_count": len(requested),
                    "failure_count": 0,
                    "fallback_used": True,
                    "latency_ms": _elapsed_ms(started_at),
                },
            )
            return frame

        try:
            csv_text = self._http.get_text(self.csv_url)
            frame = pd.read_csv(StringIO(csv_text))
            if self.date_column not in frame.columns:
                return self._fallback.fetch(list(requested.keys()), start, end)

            frame[self.date_column] = pd.to_datetime(frame[self.date_column], errors="coerce")
            frame = frame.dropna(subset=[self.date_column]).set_index(self.date_column).sort_index()
            frame = frame[(frame.index >= pd.to_datetime(start)) & (frame.index <= pd.to_datetime(end))]

            out = pd.DataFrame(index=frame.index)
            for sid, col in requested.items():
                out[sid] = pd.to_numeric(frame.get(col), errors="coerce")

            if out.empty:
                frame = self._fallback.fetch(list(requested.keys()), start, end)
                _set_last_fetch_metadata(
                    self,
                    {
                        "provider": "fed_h41",
                        "source_type": type(self).__name__,
                        "request_count": len(requested),
                        "request_keys": list(requested.keys()),
                        "providers_touched": ["fed_h41"],
                        "row_count": int(len(frame)),
                        "column_count": int(len(frame.columns)),
                        "success_count": len(requested),
                        "failure_count": 0,
                        "fallback_used": True,
                        "latency_ms": _elapsed_ms(started_at),
                    },
                )
                return frame
            frame = _normalize_columns(out)
            _set_last_fetch_metadata(
                self,
                {
                    "provider": "fed_h41",
                    "source_type": type(self).__name__,
                    "request_count": len(requested),
                    "request_keys": list(requested.keys()),
                    "providers_touched": ["fed_h41"],
                    "row_count": int(len(frame)),
                    "column_count": int(len(frame.columns)),
                    "success_count": int(sum(1 for sid in requested if frame[sid].notna().any())),
                    "failure_count": int(sum(1 for sid in requested if not frame[sid].notna().any())),
                    "fallback_used": False,
                    "latency_ms": _elapsed_ms(started_at),
                },
            )
            return frame
        except Exception:
            frame = self._fallback.fetch(list(requested.keys()), start, end)
            _set_last_fetch_metadata(
                self,
                {
                    "provider": "fed_h41",
                    "source_type": type(self).__name__,
                    "request_count": len(requested),
                    "request_keys": list(requested.keys()),
                    "providers_touched": ["fed_h41"],
                    "row_count": int(len(frame)),
                    "column_count": int(len(frame.columns)),
                    "success_count": len(requested),
                    "failure_count": 0,
                    "fallback_used": True,
                    "latency_ms": _elapsed_ms(started_at),
                },
            )
            return frame

    def available_series(self) -> list[str]:
        return [
            "H41:primary_credit",
            "H41:btfp",
            "H41:discount_window",
        ]


class SECEDGARDataSource(DataSource):
    """SEC submissions adapter.

    series_ids format: SEC:<CIK>
    Output value: daily filing count (low-frequency structural pulse).
    """

    def __init__(
        self,
        user_agent: str,
        fallback_seed: int = 42,
        http: HTTPClient | None = None,
        base_url: str = "https://data.sec.gov/submissions",
    ) -> None:
        self.user_agent = user_agent
        self._http = http or HTTPClient(default_headers={"User-Agent": user_agent})
        self._base_url = base_url.rstrip("/")
        self._fallback = MockDataSource(seed=fallback_seed)

    def fetch(self, series_ids: list[str], start: str, end: str) -> pd.DataFrame:
        started_at = _now_perf()
        requested = _extract_prefixed_series_ids(series_ids, prefix="SEC")
        if not requested:
            _set_last_fetch_metadata(
                self,
                {
                    "provider": "sec",
                    "source_type": type(self).__name__,
                    "request_count": 0,
                    "request_keys": [],
                    "providers_touched": [],
                    "row_count": 0,
                    "column_count": 0,
                    "success_count": 0,
                    "failure_count": 0,
                    "fallback_used": False,
                    "latency_ms": _elapsed_ms(started_at),
                },
            )
            return _empty_result()

        if not self.user_agent:
            frame = self._fallback.fetch(list(requested.keys()), start, end)
            _set_last_fetch_metadata(
                self,
                {
                    "provider": "sec",
                    "source_type": type(self).__name__,
                    "request_count": len(requested),
                    "request_keys": list(requested.keys()),
                    "providers_touched": ["sec"],
                    "row_count": int(len(frame)),
                    "column_count": int(len(frame.columns)),
                    "success_count": len(requested),
                    "failure_count": 0,
                    "fallback_used": True,
                    "latency_ms": _elapsed_ms(started_at),
                },
            )
            return frame

        idx = pd.date_range(start=start, end=end, freq="D")
        out = pd.DataFrame(index=idx)
        for sid, cik_code in requested.items():
            cik = cik_code.zfill(10)
            try:
                payload = self._http.get_json(f"{self._base_url}/CIK{cik}.json")
                recent = payload.get("filings", {}).get("recent", {}) if isinstance(payload, dict) else {}
                dates = recent.get("filingDate", []) if isinstance(recent, dict) else []
                s = pd.Series(1.0, index=pd.to_datetime(dates, errors="coerce")).dropna()
                s = s.groupby(level=0).sum().reindex(idx).fillna(0.0)
                out[sid] = s
            except Exception:
                out[sid] = np.nan

        if out.isna().all().all():
            frame = self._fallback.fetch(list(requested.keys()), start, end)
            _set_last_fetch_metadata(
                self,
                {
                    "provider": "sec",
                    "source_type": type(self).__name__,
                    "request_count": len(requested),
                    "request_keys": list(requested.keys()),
                    "providers_touched": ["sec"],
                    "row_count": int(len(frame)),
                    "column_count": int(len(frame.columns)),
                    "success_count": len(requested),
                    "failure_count": 0,
                    "fallback_used": True,
                    "latency_ms": _elapsed_ms(started_at),
                },
            )
            return frame
        frame = _normalize_columns(out)
        _set_last_fetch_metadata(
            self,
            {
                "provider": "sec",
                "source_type": type(self).__name__,
                "request_count": len(requested),
                "request_keys": list(requested.keys()),
                "providers_touched": ["sec"],
                "row_count": int(len(frame)),
                "column_count": int(len(frame.columns)),
                "success_count": int(sum(1 for sid in requested if frame[sid].notna().any())),
                "failure_count": int(sum(1 for sid in requested if not frame[sid].notna().any())),
                "fallback_used": False,
                "latency_ms": _elapsed_ms(started_at),
            },
        )
        return frame

    def available_series(self) -> list[str]:
        return ["SEC:0000072971", "SEC:0000019617", "SEC:0000035527"]


class TreasuryFiscalDataSource(DataSource):
    """U.S. Treasury Fiscal Data API adapter.

    series_ids format: TFD:<dataset>:<field>
    Example: TFD:daily_treasury_statement:open_today_bal
    """

    def __init__(
        self,
        fallback_seed: int = 42,
        http: HTTPClient | None = None,
        base_url: str = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service",
    ) -> None:
        self._http = http or HTTPClient()
        self._base_url = base_url.rstrip("/")
        self._fallback = MockDataSource(seed=fallback_seed)

    def fetch(self, series_ids: list[str], start: str, end: str) -> pd.DataFrame:
        started_at = _now_perf()
        requested = _extract_prefixed_series_ids(series_ids, prefix="TFD")
        if not requested:
            _set_last_fetch_metadata(
                self,
                {
                    "provider": "treasury",
                    "source_type": type(self).__name__,
                    "request_count": 0,
                    "request_keys": [],
                    "providers_touched": [],
                    "row_count": 0,
                    "column_count": 0,
                    "success_count": 0,
                    "failure_count": 0,
                    "fallback_used": False,
                    "latency_ms": _elapsed_ms(started_at),
                },
            )
            return _empty_result()

        rows_by_sid: dict[str, pd.Series] = {}
        for sid, dataset_field in requested.items():
            try:
                if ":" not in dataset_field:
                    continue
                dataset, field = dataset_field.split(":", 1)
                url = (
                    f"{self._base_url}/v1/accounting/{dataset}"
                    f"?filter=record_date:gte:{start},record_date:lte:{end}"
                    f"&fields=record_date,{field}&format=json&page[size]=10000"
                )
                payload = self._http.get_json(url)
                data = payload.get("data", []) if isinstance(payload, dict) else []
                if not data:
                    continue
                dates = pd.to_datetime([x.get("record_date") for x in data], errors="coerce")
                vals = pd.to_numeric([x.get(field) for x in data], errors="coerce")
                s = pd.Series(vals, index=dates).dropna()
                rows_by_sid[sid] = s
            except Exception:
                continue

        if not rows_by_sid:
            frame = self._fallback.fetch(list(requested.keys()), start, end)
            _set_last_fetch_metadata(
                self,
                {
                    "provider": "treasury",
                    "source_type": type(self).__name__,
                    "request_count": len(requested),
                    "request_keys": list(requested.keys()),
                    "providers_touched": ["treasury"],
                    "row_count": int(len(frame)),
                    "column_count": int(len(frame.columns)),
                    "success_count": len(requested),
                    "failure_count": 0,
                    "fallback_used": True,
                    "latency_ms": _elapsed_ms(started_at),
                },
            )
            return frame

        merged = pd.concat(rows_by_sid.values(), axis=1)
        merged.columns = list(rows_by_sid.keys())
        merged = _normalize_columns(merged)
        for sid in requested:
            if sid not in merged.columns:
                merged[sid] = np.nan
        frame = merged[list(requested.keys())]
        _set_last_fetch_metadata(
            self,
            {
                "provider": "treasury",
                "source_type": type(self).__name__,
                "request_count": len(requested),
                "request_keys": list(requested.keys()),
                "providers_touched": ["treasury"],
                "row_count": int(len(frame)),
                "column_count": int(len(frame.columns)),
                "success_count": len(rows_by_sid),
                "failure_count": len(requested) - len(rows_by_sid),
                "fallback_used": False,
                "latency_ms": _elapsed_ms(started_at),
            },
        )
        return frame

    def available_series(self) -> list[str]:
        return [
            "TFD:daily_treasury_statement:open_today_bal",
            "TFD:debt_to_penny:tot_pub_debt_out_amt",
        ]


class AlphaVantageDataSource(DataSource):
    def __init__(
        self,
        api_key: str | None = None,
        fallback_seed: int = 42,
        http: HTTPClient | None = None,
        base_url: str = "https://www.alphavantage.co/query",
    ) -> None:
        self.api_key = api_key
        self._fallback = MockDataSource(seed=fallback_seed)
        self._http = http or HTTPClient()
        self._base_url = base_url

    def fetch(self, series_ids: list[str], start: str, end: str) -> pd.DataFrame:
        requested = _extract_prefixed_series_ids(series_ids, prefix="AV")
        if not requested:
            return _empty_result()
        if not self.api_key:
            return self._fallback.fetch(list(requested.keys()), start, end)

        frames: list[pd.Series] = []
        for sid, query in requested.items():
            parts = query.split(":")
            symbol = parts[0]
            field = parts[1].lower() if len(parts) > 1 else "close"
            field_map = {
                "open": "1. open",
                "high": "2. high",
                "low": "3. low",
                "close": "4. close",
                "volume": "6. volume",
            }
            value_key = field_map.get(field, "4. close")
            params = urlencode(
                {
                    "function": "TIME_SERIES_DAILY_ADJUSTED",
                    "symbol": symbol,
                    "outputsize": "full",
                    "apikey": self.api_key,
                }
            )
            try:
                payload = self._http.get_json(f"{self._base_url}?{params}")
                data = payload.get("Time Series (Daily)", {}) if isinstance(payload, dict) else {}
                if not isinstance(data, dict) or not data:
                    continue
                rows = []
                for raw_date, metrics in data.items():
                    if not isinstance(metrics, dict):
                        continue
                    rows.append((pd.to_datetime(raw_date), pd.to_numeric(metrics.get(value_key), errors="coerce")))
                s = pd.Series(data=[x[1] for x in rows], index=[x[0] for x in rows], name=sid).dropna()
                s = s[(s.index >= pd.to_datetime(start)) & (s.index <= pd.to_datetime(end))]
                if not s.empty:
                    frames.append(s)
            except Exception:
                continue

        if not frames:
            return self._fallback.fetch(list(requested.keys()), start, end)

        merged = _normalize_columns(pd.concat(frames, axis=1))
        for sid in requested:
            if sid not in merged.columns:
                merged[sid] = np.nan
        return merged[list(requested.keys())]

    def available_series(self) -> list[str]:
        return ["AV:SPY", "AV:QQQ", "AV:VIX"]


class PolygonDataSource(DataSource):
    def __init__(
        self,
        api_key: str | None = None,
        fallback_seed: int = 42,
        http: HTTPClient | None = None,
        base_url: str = "https://api.polygon.io",
    ) -> None:
        self.api_key = api_key
        self._fallback = MockDataSource(seed=fallback_seed)
        self._http = http or HTTPClient()
        self._base_url = base_url.rstrip("/")

    def fetch(self, series_ids: list[str], start: str, end: str) -> pd.DataFrame:
        requested = _extract_prefixed_series_ids(series_ids, prefix="POLY")
        if not requested:
            return _empty_result()
        if not self.api_key:
            return self._fallback.fetch(list(requested.keys()), start, end)

        frames: list[pd.Series] = []
        for sid, query in requested.items():
            parts = query.split(":")
            ticker = parts[0]
            field = parts[1].lower() if len(parts) > 1 else "close"
            field_map = {
                "open": "o",
                "high": "h",
                "low": "l",
                "close": "c",
                "volume": "v",
            }
            key = field_map.get(field, "c")
            encoded_ticker = quote(ticker, safe="")
            url = (
                f"{self._base_url}/v2/aggs/ticker/{encoded_ticker}/range/1/day/{start}/{end}"
                f"?adjusted=true&sort=asc&limit=50000&apiKey={self.api_key}"
            )
            try:
                payload = self._http.get_json(url)
                results = payload.get("results", []) if isinstance(payload, dict) else []
                if not isinstance(results, list) or not results:
                    continue
                dates = pd.to_datetime([x.get("t") for x in results], unit="ms", errors="coerce")
                vals = pd.to_numeric([x.get(key) for x in results], errors="coerce")
                s = pd.Series(vals, index=dates, name=sid).dropna()
                if not s.empty:
                    frames.append(s)
            except Exception:
                continue

        if not frames:
            return self._fallback.fetch(list(requested.keys()), start, end)

        merged = _normalize_columns(pd.concat(frames, axis=1))
        for sid in requested:
            if sid not in merged.columns:
                merged[sid] = np.nan
        return merged[list(requested.keys())]

    def available_series(self) -> list[str]:
        return ["POLY:SPY", "POLY:VIX", "POLY:OPTION:SPY"]


class NasdaqDataLinkDataSource(DataSource):
    def __init__(
        self,
        api_key: str | None = None,
        fallback_seed: int = 42,
        http: HTTPClient | None = None,
        base_url: str = "https://data.nasdaq.com/api/v3/datasets",
    ) -> None:
        self.api_key = api_key
        self._fallback = MockDataSource(seed=fallback_seed)
        self._http = http or HTTPClient()
        self._base_url = base_url.rstrip("/")

    def fetch(self, series_ids: list[str], start: str, end: str) -> pd.DataFrame:
        requested = _extract_prefixed_series_ids(series_ids, prefix="NDL")
        if not requested:
            return _empty_result()
        if not self.api_key:
            return self._fallback.fetch(list(requested.keys()), start, end)

        frames: list[pd.Series] = []
        for sid, dataset_spec in requested.items():
            dataset_code, column_hint = self._parse_dataset_spec(dataset_spec)
            url = (
                f"{self._base_url}/{dataset_code}.json"
                f"?start_date={start}&end_date={end}&api_key={self.api_key}"
            )
            try:
                payload = self._http.get_json(url)
                dataset_data = payload.get("dataset", {}) if isinstance(payload, dict) else {}
                columns = dataset_data.get("column_names", []) if isinstance(dataset_data, dict) else []
                data = dataset_data.get("data", []) if isinstance(dataset_data, dict) else []
                if not isinstance(columns, list) or not isinstance(data, list) or not columns or not data:
                    continue

                col_idx = self._resolve_column_index(columns, column_hint)
                if col_idx is None:
                    continue

                dates = []
                vals = []
                for row in data:
                    if not isinstance(row, list) or len(row) <= col_idx:
                        continue
                    dates.append(pd.to_datetime(row[0], errors="coerce"))
                    vals.append(pd.to_numeric(row[col_idx], errors="coerce"))
                s = pd.Series(vals, index=dates, name=sid).dropna()
                if not s.empty:
                    frames.append(s)
            except Exception:
                continue

        if not frames:
            return self._fallback.fetch(list(requested.keys()), start, end)

        merged = _normalize_columns(pd.concat(frames, axis=1))
        for sid in requested:
            if sid not in merged.columns:
                merged[sid] = np.nan
        return merged[list(requested.keys())]

    def available_series(self) -> list[str]:
        return ["NDL:FRED/TEDRATE", "NDL:USTREASURY/YIELD"]

    def _parse_dataset_spec(self, dataset_spec: str) -> tuple[str, str | None]:
        parts = dataset_spec.rsplit(":", 1)
        if len(parts) == 2 and "/" in parts[0]:
            return parts[0], parts[1]
        return dataset_spec, None

    def _resolve_column_index(self, columns: list[str], column_hint: str | None) -> int | None:
        if len(columns) < 2:
            return None
        if column_hint is None:
            return 1
        if column_hint.isdigit():
            idx = int(column_hint)
            if 0 <= idx < len(columns):
                return idx
            return None
        for idx, name in enumerate(columns):
            if str(name).lower() == column_hint.lower():
                return idx
        return 1


class CompositeDataSource(DataSource):
    def __init__(self, sources: list[DataSource], fallback_seed: int = 42, max_workers: int | None = None) -> None:
        self.sources = sources
        self._fallback = MockDataSource(seed=fallback_seed)
        self._max_workers = max(1, int(max_workers or len(sources) or 1))

    def fetch(self, series_ids: list[str], start: str, end: str) -> pd.DataFrame:
        started_at = _now_perf()
        if not self.sources:
            frame = self._fallback.fetch(series_ids, start, end)
            _set_last_fetch_metadata(
                self,
                {
                    "provider": "composite",
                    "source_type": type(self).__name__,
                    "request_count": len(series_ids),
                    "request_keys": list(series_ids),
                    "providers_touched": [],
                    "provider_runs": [],
                    "row_count": int(len(frame)),
                    "column_count": int(len(frame.columns)),
                    "success_count": 0,
                    "failure_count": len(series_ids),
                    "fallback_used": True,
                    "latency_ms": _elapsed_ms(started_at),
                },
            )
            return frame

        combined: pd.DataFrame | None = None
        with ThreadPoolExecutor(max_workers=min(self._max_workers, len(self.sources))) as pool:
            futures = {pool.submit(source.fetch, series_ids, start, end): source for source in self.sources}
            frames: list[pd.DataFrame] = []
            for future in as_completed(futures):
                try:
                    frame = future.result()
                except Exception:
                    continue
                if frame is not None and not frame.empty:
                    frames.append(_normalize_columns(frame))

        for frame in frames:
            if frame is None or frame.empty:
                continue
            if combined is None:
                combined = frame.copy()
            else:
                combined = combined.combine_first(frame)

        if combined is None or combined.empty:
            frame = self._fallback.fetch(series_ids, start, end)
            provider_runs = [meta for source in self.sources if (meta := _safe_fetch_metadata(source))]
            _set_last_fetch_metadata(
                self,
                {
                    "provider": "composite",
                    "source_type": type(self).__name__,
                    "request_count": len(series_ids),
                    "request_keys": list(series_ids),
                    "providers_touched": sorted({provider for meta in provider_runs for provider in meta.get("providers_touched", [])}),
                    "provider_runs": provider_runs,
                    "row_count": int(len(frame)),
                    "column_count": int(len(frame.columns)),
                    "success_count": int(sum(meta.get("success_count", 0) for meta in provider_runs)),
                    "failure_count": int(sum(meta.get("failure_count", 0) for meta in provider_runs)),
                    "fallback_used": True,
                    "latency_ms": _elapsed_ms(started_at),
                },
            )
            return frame

        for sid in series_ids:
            if sid not in combined.columns:
                combined[sid] = np.nan
        frame = combined.sort_index()[series_ids]
        provider_runs = [meta for source in self.sources if (meta := _safe_fetch_metadata(source))]
        _set_last_fetch_metadata(
            self,
            {
                "provider": "composite",
                "source_type": type(self).__name__,
                "request_count": len(series_ids),
                "request_keys": list(series_ids),
                "providers_touched": sorted({provider for meta in provider_runs for provider in meta.get("providers_touched", [])}),
                "provider_runs": provider_runs,
                "row_count": int(len(frame)),
                "column_count": int(len(frame.columns)),
                "success_count": int(sum(meta.get("success_count", 0) for meta in provider_runs)),
                "failure_count": int(sum(meta.get("failure_count", 0) for meta in provider_runs)),
                "fallback_used": any(bool(meta.get("fallback_used")) for meta in provider_runs),
                "latency_ms": _elapsed_ms(started_at),
            },
        )
        return frame

    def available_series(self) -> list[str]:
        names: set[str] = set()
        for source in self.sources:
            try:
                names.update(source.available_series())
            except Exception:
                continue
        return sorted(names)


class ProxyAggregationDataSource(DataSource):
    """Expand configured component series and aggregate them into proxy channels."""

    def __init__(
        self,
        source: DataSource,
        proxy_series_map: dict[str, list[Any]] | None = None,
        fallback_seed: int = 42,
        incremental_cache: bool = True,
    ) -> None:
        self.source = source
        self.proxy_series_map = proxy_series_map or DEFAULT_PROXY_SERIES_MAP
        self._fallback = MockDataSource(seed=fallback_seed)
        self.incremental_cache = bool(incremental_cache)
        self._raw_cache: dict[tuple[str, ...], pd.DataFrame] = {}
        self._cache_lock = threading.Lock()

    def fetch(self, series_ids: list[str], start: str, end: str) -> pd.DataFrame:
        started_at = _now_perf()
        expanded_ids = self._expand_series_ids(series_ids)
        raw = self._fetch_expanded_incremental(expanded_ids, start, end)
        if raw is None or raw.empty:
            frame = self._fallback.fetch(series_ids, start, end)
            raw_meta = _safe_fetch_metadata(self.source) or {}
            _set_last_fetch_metadata(
                self,
                {
                    "provider": "proxy_aggregation",
                    "source_type": type(self).__name__,
                    "lineage_mode": "data_source_bridge",
                    "requested_series_ids": list(series_ids),
                    "expanded_series_ids": list(expanded_ids),
                    "providers_touched": sorted({provider for provider in raw_meta.get("providers_touched", [])}),
                    "provider_runs": list(raw_meta.get("provider_runs", [])),
                    "request_count": len(expanded_ids),
                    "row_count": int(len(frame)),
                    "column_count": int(len(frame.columns)),
                    "success_count": int(sum(1 for sid in series_ids if sid in frame.columns and frame[sid].notna().any())),
                    "failure_count": int(sum(1 for sid in series_ids if sid not in frame.columns or not frame[sid].notna().any())),
                    "fallback_used": True,
                    "latency_ms": _elapsed_ms(started_at),
                },
            )
            return frame

        raw = _normalize_columns(raw)
        out = pd.DataFrame(index=raw.index)

        for sid in series_ids:
            components = self.proxy_series_map.get(sid)
            if components:
                aggregated = self._aggregate_proxy(components, raw)
                out[sid] = aggregated if aggregated is not None else np.nan
            elif sid in raw.columns:
                out[sid] = _coerce_series(raw[sid])
            else:
                out[sid] = np.nan

        if out.isna().all().all():
            frame = self._fallback.fetch(series_ids, start, end)
            raw_meta = _safe_fetch_metadata(self.source) or {}
            _set_last_fetch_metadata(
                self,
                {
                    "provider": "proxy_aggregation",
                    "source_type": type(self).__name__,
                    "lineage_mode": "data_source_bridge",
                    "requested_series_ids": list(series_ids),
                    "expanded_series_ids": list(expanded_ids),
                    "providers_touched": sorted({provider for provider in raw_meta.get("providers_touched", [])}),
                    "provider_runs": list(raw_meta.get("provider_runs", [])),
                    "request_count": len(expanded_ids),
                    "row_count": int(len(frame)),
                    "column_count": int(len(frame.columns)),
                    "success_count": int(sum(1 for sid in series_ids if sid in frame.columns and frame[sid].notna().any())),
                    "failure_count": int(sum(1 for sid in series_ids if sid not in frame.columns or not frame[sid].notna().any())),
                    "fallback_used": True,
                    "latency_ms": _elapsed_ms(started_at),
                },
            )
            return frame
        frame = out.sort_index()[series_ids]
        raw_meta = _safe_fetch_metadata(self.source) or {}
        _set_last_fetch_metadata(
            self,
            {
                "provider": "proxy_aggregation",
                "source_type": type(self).__name__,
                "lineage_mode": "data_source_bridge",
                "requested_series_ids": list(series_ids),
                "expanded_series_ids": list(expanded_ids),
                "providers_touched": sorted({provider for provider in raw_meta.get("providers_touched", [])}),
                "provider_runs": list(raw_meta.get("provider_runs", [])),
                "request_count": len(expanded_ids),
                "row_count": int(len(frame)),
                "column_count": int(len(frame.columns)),
                "success_count": int(sum(1 for sid in series_ids if sid in frame.columns and frame[sid].notna().any())),
                "failure_count": int(sum(1 for sid in series_ids if sid not in frame.columns or not frame[sid].notna().any())),
                "fallback_used": bool(raw_meta.get("fallback_used", False)),
                "latency_ms": _elapsed_ms(started_at),
                "component_request_count": len(expanded_ids),
            },
        )
        return frame

    def _fetch_expanded_incremental(self, expanded_ids: list[str], start: str, end: str) -> pd.DataFrame:
        if not self.incremental_cache:
            return self.source.fetch(expanded_ids, start, end)

        key = tuple(expanded_ids)
        start_ts = pd.to_datetime(start)
        end_ts = pd.to_datetime(end)
        with self._cache_lock:
            cached = self._raw_cache.get(key)

        if cached is None or cached.empty:
            raw = _normalize_columns(self.source.fetch(expanded_ids, start, end))
            with self._cache_lock:
                self._raw_cache[key] = raw
            return raw.loc[start_ts:end_ts]

        cached = _normalize_columns(cached)
        pieces = [cached]
        min_cached = cached.index.min()
        max_cached = cached.index.max()

        if start_ts < min_cached:
            pre_end = (min_cached - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
            pre = self.source.fetch(expanded_ids, start, pre_end)
            if pre is not None and not pre.empty:
                pieces.append(_normalize_columns(pre))

        if end_ts > max_cached:
            post_start = (max_cached + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
            post = self.source.fetch(expanded_ids, post_start, end)
            if post is not None and not post.empty:
                pieces.append(_normalize_columns(post))

        combined = _normalize_columns(pd.concat(pieces, axis=0))
        combined = combined[~combined.index.duplicated(keep="last")]
        for sid in expanded_ids:
            if sid not in combined.columns:
                combined[sid] = np.nan
        combined = combined.sort_index()[expanded_ids]
        with self._cache_lock:
            self._raw_cache[key] = combined
        return combined.loc[start_ts:end_ts]

    def available_series(self) -> list[str]:
        names = set(self.source.available_series())
        names.update(self.proxy_series_map.keys())
        return sorted(names)

    def _expand_series_ids(self, series_ids: list[str]) -> list[str]:
        expanded: list[str] = []
        for sid in series_ids:
            mapped = self.proxy_series_map.get(sid)
            if not mapped:
                expanded.append(sid)
                continue
            for component in mapped:
                parsed = self._parse_component(component)
                if parsed is None:
                    continue
                expanded.append(parsed[0])
        # preserve order while deduplicating
        return list(dict.fromkeys(expanded))

    def _aggregate_proxy(self, components: list[Any], raw: pd.DataFrame) -> pd.Series | None:
        normalized_components: list[pd.Series] = []
        for component in components:
            parsed = self._parse_component(component)
            if parsed is None:
                continue
            source_id, weight, invert = parsed
            if source_id not in raw.columns:
                continue
            s = _coerce_series(raw[source_id])
            if invert:
                s = -s
            s = s * weight
            s = self._zscore(s)
            normalized_components.append(s)

        if not normalized_components:
            return None

        component_frame = pd.concat(normalized_components, axis=1)
        return component_frame.mean(axis=1, skipna=True)

    def _parse_component(self, component: Any) -> tuple[str, float, bool] | None:
        if isinstance(component, dict):
            component_id = str(component.get("id", "")).strip()
            if not component_id:
                return None
            weight = float(component.get("weight", 1.0))
            invert = bool(component.get("invert", False))
            return component_id, weight, invert

        if not isinstance(component, str):
            return None

        token = component.strip()
        if not token:
            return None

        invert = False
        if token.startswith("-"):
            invert = True
            token = token[1:].strip()
        elif token.startswith("+"):
            token = token[1:].strip()

        weight = 1.0
        if "*" in token:
            lhs, rhs = token.split("*", 1)
            lhs = lhs.strip()
            rhs = rhs.strip()
            try:
                weight = float(lhs)
                token = rhs
            except ValueError:
                token = lhs
                try:
                    weight = float(rhs)
                except ValueError:
                    weight = 1.0

        if not token:
            return None
        return token, weight, invert

    def _zscore(self, s: pd.Series, window: int = 260) -> pd.Series:
        """Rolling z-score with winsorization to avoid look-ahead bias.

        Uses an expanding window (up to `window` observations) so that each
        point is normalized only against its own past. Full-history mean/std
        would be fine for standalone scaling but creates look-ahead bias in
        any historical backtest because future observations shift the mean.
        """
        clean = s.replace([np.inf, -np.inf], np.nan)
        roll_mean = clean.rolling(window=window, min_periods=4).mean()
        roll_std = clean.rolling(window=window, min_periods=4).std(ddof=0)
        # Winsorize before z-scoring: clip raw values at ±3 rolling-std
        lo = roll_mean - 3.0 * roll_std
        hi = roll_mean + 3.0 * roll_std
        clipped = clean.clip(lower=lo, upper=hi)
        result = (clipped - roll_mean) / roll_std.replace(0, float("nan"))
        return result


class DataSourceFactory:
    """Backward-compatible factory for the canonical DataHubBridge path."""

    @staticmethod
    def build(config: dict[str, Any], use_mock: bool, fallback_seed: int = 42) -> DataSource:
        ds_cfg = config.get("data_sources", {})
        proxy_series_map = ds_cfg.get("proxy_series_map", DEFAULT_PROXY_SERIES_MAP) if isinstance(ds_cfg, dict) else DEFAULT_PROXY_SERIES_MAP
        from src.data.gateway import DataHubBridge, create_data_hub

        return DataHubBridge(
            hub=create_data_hub(config=config, use_mock=use_mock),
            proxy_series_map=proxy_series_map if isinstance(proxy_series_map, dict) else DEFAULT_PROXY_SERIES_MAP,
            fallback_seed=fallback_seed,
        )
