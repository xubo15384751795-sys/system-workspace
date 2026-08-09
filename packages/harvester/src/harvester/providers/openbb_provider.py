from __future__ import annotations

import os
import signal
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

from harvester.providers.base import OfficialProvider, ProviderResult


@dataclass(frozen=True)
class OpenBBSeriesRoute:
    series_id: str
    obb_path: str
    provider: str
    source_id: str
    source_series_id: str
    value_column: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    unit: str = ""
    frequency: str = ""


DEFAULT_OPENBB_ROUTES: dict[str, OpenBBSeriesRoute] = {
    # FRED routes. These keep source_id=fred so downstream consumers see the
    # admitted evidence identity, not the OpenBB acquisition engine.
    "VIXCLS": OpenBBSeriesRoute(
        series_id="VIXCLS",
        obb_path="economy.fred_series",
        provider="fred",
        source_id="fred",
        source_series_id="VIXCLS",
        value_column="VIXCLS",
        unit="index",
        frequency="daily",
    ),
    "BAMLH0A0HYM2": OpenBBSeriesRoute(
        series_id="BAMLH0A0HYM2",
        obb_path="economy.fred_series",
        provider="fred",
        source_id="fred",
        source_series_id="BAMLH0A0HYM2",
        value_column="BAMLH0A0HYM2",
        unit="percent",
        frequency="daily",
    ),
    "NFCI": OpenBBSeriesRoute(
        series_id="NFCI",
        obb_path="economy.fred_series",
        provider="fred",
        source_id="fred",
        source_series_id="NFCI",
        value_column="NFCI",
        unit="index",
        frequency="weekly",
    ),
    "STLFSI4": OpenBBSeriesRoute(
        series_id="STLFSI4",
        obb_path="economy.fred_series",
        provider="fred",
        source_id="fred",
        source_series_id="STLFSI4",
        value_column="STLFSI4",
        unit="index",
        frequency="weekly",
    ),
    "SOFR": OpenBBSeriesRoute(
        series_id="SOFR",
        obb_path="economy.fred_series",
        provider="fred",
        source_id="fred",
        source_series_id="SOFR",
        value_column="SOFR",
        unit="percent",
        frequency="daily",
    ),
    "IORB": OpenBBSeriesRoute(
        series_id="IORB",
        obb_path="economy.fred_series",
        provider="fred",
        source_id="fred",
        source_series_id="IORB",
        value_column="IORB",
        unit="percent",
        frequency="daily",
    ),
    # M channel — funding / transmission
    "DCPF3M": OpenBBSeriesRoute(
        series_id="DCPF3M",
        obb_path="economy.fred_series",
        provider="fred",
        source_id="fred",
        source_series_id="DCPF3M",
        value_column="DCPF3M",
        unit="percent",
        frequency="daily",
    ),
    "DGS3MO": OpenBBSeriesRoute(
        series_id="DGS3MO",
        obb_path="economy.fred_series",
        provider="fred",
        source_id="fred",
        source_series_id="DGS3MO",
        value_column="DGS3MO",
        unit="percent",
        frequency="daily",
    ),
    "DPRIME": OpenBBSeriesRoute(
        series_id="DPRIME",
        obb_path="economy.fred_series",
        provider="fred",
        source_id="fred",
        source_series_id="DPRIME",
        value_column="DPRIME",
        unit="percent",
        frequency="daily",
    ),
    # D channel — depth / deformation
    "BAMLC0A0CM": OpenBBSeriesRoute(
        series_id="BAMLC0A0CM",
        obb_path="economy.fred_series",
        provider="fred",
        source_id="fred",
        source_series_id="BAMLC0A0CM",
        value_column="BAMLC0A0CM",
        unit="percent",
        frequency="daily",
    ),
    "BAMLC0A4CBBB": OpenBBSeriesRoute(
        series_id="BAMLC0A4CBBB",
        obb_path="economy.fred_series",
        provider="fred",
        source_id="fred",
        source_series_id="BAMLC0A4CBBB",
        value_column="BAMLC0A4CBBB",
        unit="percent",
        frequency="daily",
    ),
    "DBAA": OpenBBSeriesRoute(
        series_id="DBAA",
        obb_path="economy.fred_series",
        provider="fred",
        source_id="fred",
        source_series_id="DBAA",
        value_column="DBAA",
        unit="percent",
        frequency="daily",
    ),
    "DAAA": OpenBBSeriesRoute(
        series_id="DAAA",
        obb_path="economy.fred_series",
        provider="fred",
        source_id="fred",
        source_series_id="DAAA",
        value_column="DAAA",
        unit="percent",
        frequency="daily",
    ),
    "BAA10YM": OpenBBSeriesRoute(
        series_id="BAA10YM",
        obb_path="economy.fred_series",
        provider="fred",
        source_id="fred",
        source_series_id="BAA10YM",
        value_column="BAA10YM",
        unit="percent",
        frequency="monthly",
    ),
    # NFCI sub-indices
    "NFCIRISK": OpenBBSeriesRoute(
        series_id="NFCIRISK",
        obb_path="economy.fred_series",
        provider="fred",
        source_id="fred",
        source_series_id="NFCIRISK",
        value_column="NFCIRISK",
        unit="index",
        frequency="weekly",
    ),
    "NFCICREDIT": OpenBBSeriesRoute(
        series_id="NFCICREDIT",
        obb_path="economy.fred_series",
        provider="fred",
        source_id="fred",
        source_series_id="NFCICREDIT",
        value_column="NFCICREDIT",
        unit="index",
        frequency="weekly",
    ),
    "NFCILEVERAGE": OpenBBSeriesRoute(
        series_id="NFCILEVERAGE",
        obb_path="economy.fred_series",
        provider="fred",
        source_id="fred",
        source_series_id="NFCILEVERAGE",
        value_column="NFCILEVERAGE",
        unit="index",
        frequency="weekly",
    ),
    # MOVE is intentionally an OpenBB route candidate, not yet a production
    # Harvester core series, because free providers can rate-limit or differ
    # in symbol conventions. It is available for staged acquisition once
    # verified for a release.
    "MOVE": OpenBBSeriesRoute(
        series_id="MOVE",
        obb_path="index.price.historical",
        provider="yfinance",
        source_id="yfinance",
        source_series_id="^MOVE",
        value_column="close",
        params={"symbol": "^MOVE"},
        unit="index",
        frequency="daily",
    ),
    "HYG": OpenBBSeriesRoute(
        series_id="HYG",
        obb_path="equity.price.historical",
        provider="tiingo",
        source_id="tiingo",
        source_series_id="HYG",
        value_column="close",
        params={"symbol": "HYG"},
        unit="usd",
        frequency="daily",
    ),
    "HYG_YF": OpenBBSeriesRoute(
        series_id="HYG",
        obb_path="equity.price.historical",
        provider="yfinance",
        source_id="yfinance",
        source_series_id="HYG",
        value_column="close",
        params={"symbol": "HYG"},
        unit="usd",
        frequency="daily",
    ),
    "LQD": OpenBBSeriesRoute(
        series_id="LQD",
        obb_path="equity.price.historical",
        provider="tiingo",
        source_id="tiingo",
        source_series_id="LQD",
        value_column="close",
        params={"symbol": "LQD"},
        unit="usd",
        frequency="daily",
    ),
    "LQD_YF": OpenBBSeriesRoute(
        series_id="LQD",
        obb_path="equity.price.historical",
        provider="yfinance",
        source_id="yfinance",
        source_series_id="LQD",
        value_column="close",
        params={"symbol": "LQD"},
        unit="usd",
        frequency="daily",
    ),
    "TLT": OpenBBSeriesRoute(
        series_id="TLT",
        obb_path="equity.price.historical",
        provider="tiingo",
        source_id="tiingo",
        source_series_id="TLT",
        value_column="close",
        params={"symbol": "TLT"},
        unit="usd",
        frequency="daily",
    ),
    "TLT_YF": OpenBBSeriesRoute(
        series_id="TLT",
        obb_path="equity.price.historical",
        provider="yfinance",
        source_id="yfinance",
        source_series_id="TLT",
        value_column="close",
        params={"symbol": "TLT"},
        unit="usd",
        frequency="daily",
    ),
    # Treasury curve / risk-free rate complex (FRED) — extends D and M
    # channel coverage beyond the originally registered short list.
    "T10Y2Y": OpenBBSeriesRoute(
        series_id="T10Y2Y",
        obb_path="economy.fred_series",
        provider="fred",
        source_id="fred",
        source_series_id="T10Y2Y",
        value_column="T10Y2Y",
        unit="percent",
        frequency="daily",
    ),
    "T10Y3M": OpenBBSeriesRoute(
        series_id="T10Y3M",
        obb_path="economy.fred_series",
        provider="fred",
        source_id="fred",
        source_series_id="T10Y3M",
        value_column="T10Y3M",
        unit="percent",
        frequency="daily",
    ),
    "DFF": OpenBBSeriesRoute(
        series_id="DFF",
        obb_path="economy.fred_series",
        provider="fred",
        source_id="fred",
        source_series_id="DFF",
        value_column="DFF",
        unit="percent",
        frequency="daily",
    ),
    "EFFR": OpenBBSeriesRoute(
        series_id="EFFR",
        obb_path="economy.fred_series",
        provider="fred",
        source_id="fred",
        source_series_id="EFFR",
        value_column="EFFR",
        unit="percent",
        frequency="daily",
    ),
    "DGS10": OpenBBSeriesRoute(
        series_id="DGS10",
        obb_path="economy.fred_series",
        provider="fred",
        source_id="fred",
        source_series_id="DGS10",
        value_column="DGS10",
        unit="percent",
        frequency="daily",
    ),
    "DGS2": OpenBBSeriesRoute(
        series_id="DGS2",
        obb_path="economy.fred_series",
        provider="fred",
        source_id="fred",
        source_series_id="DGS2",
        value_column="DGS2",
        unit="percent",
        frequency="daily",
    ),
    "DGS30": OpenBBSeriesRoute(
        series_id="DGS30",
        obb_path="economy.fred_series",
        provider="fred",
        source_id="fred",
        source_series_id="DGS30",
        value_column="DGS30",
        unit="percent",
        frequency="daily",
    ),
    # Credit-spread granularity beyond BAMLC0A0CM
    "BAMLC0A1CAAA": OpenBBSeriesRoute(
        series_id="BAMLC0A1CAAA",
        obb_path="economy.fred_series",
        provider="fred",
        source_id="fred",
        source_series_id="BAMLC0A1CAAA",
        value_column="BAMLC0A1CAAA",
        unit="percent",
        frequency="daily",
    ),
    "BAMLH0A1HYBB": OpenBBSeriesRoute(
        series_id="BAMLH0A1HYBB",
        obb_path="economy.fred_series",
        provider="fred",
        source_id="fred",
        source_series_id="BAMLH0A1HYBB",
        value_column="BAMLH0A1HYBB",
        unit="percent",
        frequency="daily",
    ),
    # Policy uncertainty + vol regime probes (FRED daily)
    "USEPUINDXD": OpenBBSeriesRoute(
        series_id="USEPUINDXD",
        obb_path="economy.fred_series",
        provider="fred",
        source_id="fred",
        source_series_id="USEPUINDXD",
        value_column="USEPUINDXD",
        unit="index",
        frequency="daily",
    ),
    "GVZCLS": OpenBBSeriesRoute(
        series_id="GVZCLS",
        obb_path="economy.fred_series",
        provider="fred",
        source_id="fred",
        source_series_id="GVZCLS",
        value_column="GVZCLS",
        unit="index",
        frequency="daily",
    ),
    "OVXCLS": OpenBBSeriesRoute(
        series_id="OVXCLS",
        obb_path="economy.fred_series",
        provider="fred",
        source_id="fred",
        source_series_id="OVXCLS",
        value_column="OVXCLS",
        unit="index",
        frequency="daily",
    ),
    # Market reference series via index (yfinance) — companion to MOVE
    "VVIX": OpenBBSeriesRoute(
        series_id="VVIX",
        obb_path="index.price.historical",
        provider="yfinance",
        source_id="yfinance",
        source_series_id="^VVIX",
        value_column="close",
        params={"symbol": "^VVIX"},
        unit="index",
        frequency="daily",
    ),
    "SKEW": OpenBBSeriesRoute(
        series_id="SKEW",
        obb_path="index.price.historical",
        provider="yfinance",
        source_id="yfinance",
        source_series_id="^SKEW",
        value_column="close",
        params={"symbol": "^SKEW"},
        unit="index",
        frequency="daily",
    ),
    # Cross-asset ETF probes (tiingo)
    "JNK": OpenBBSeriesRoute(
        series_id="JNK",
        obb_path="equity.price.historical",
        provider="tiingo",
        source_id="tiingo",
        source_series_id="JNK",
        value_column="close",
        params={"symbol": "JNK"},
        unit="usd",
        frequency="daily",
    ),
    "SHY": OpenBBSeriesRoute(
        series_id="SHY",
        obb_path="equity.price.historical",
        provider="tiingo",
        source_id="tiingo",
        source_series_id="SHY",
        value_column="close",
        params={"symbol": "SHY"},
        unit="usd",
        frequency="daily",
    ),
}


class OpenBBProvider(OfficialProvider):
    """OpenBB-backed Harvester provider.

    OpenBB is used only inside Harvester acquisition. The emitted panel keeps
    provider-native identity columns (for example source_id=fred) so downstream
    consumers do not need to know or import OpenBB.
    """

    source_id = "openbb"

    def __init__(
        self,
        *,
        openbb_provider: str = "",
        route_map: dict[str, OpenBBSeriesRoute] | None = None,
        obb_client: Any | None = None,
        data_root: str | Path = "",
        cache: bool = True,
        user_agent: str = "StructuralRiskHarvester/0.1.0",
        settings_env: str | Path | None = None,
        timeout_sec: float | None = None,
        **_: Any,
    ) -> None:
        super().__init__(data_root=data_root, cache=cache, user_agent=user_agent)
        self.openbb_provider = openbb_provider
        self._route_map = route_map or _routes_for_provider(openbb_provider)
        self._obb_client = obb_client
        configured_timeout = os.environ.get("HARVESTER_OPENBB_TIMEOUT_SEC", "45")
        try:
            self._timeout_sec = float(timeout_sec if timeout_sec is not None else configured_timeout)
        except (TypeError, ValueError):
            self._timeout_sec = 45.0
        _load_env_file(settings_env)

    def fetch_series(self, series_ids: list[str]) -> list[ProviderResult]:
        results: list[ProviderResult] = []
        for series_id in series_ids:
            route = self._route_map.get(series_id)
            if route is None:
                results.append(self._build_error_result(series_id, "no OpenBB route registered", "unknown_route"))
                continue
            results.append(self._fetch_one(route))
        return results

    def _fetch_one(self, route: OpenBBSeriesRoute) -> ProviderResult:
        try:
            obb = self._obb()
            endpoint = _resolve_attr(obb, route.obb_path)
            params = dict(route.params)
            params.setdefault("provider", route.provider)
            if "symbol" not in params:
                params["symbol"] = route.source_series_id
            with _operation_timeout(self._timeout_sec):
                result = endpoint(**params)
            frame = _to_frame(result)
            panel = _normalize_frame(frame, route)
        except TimeoutError:
            return self._build_error_result(
                route.series_id,
                f"OpenBB fetch timed out after {self._timeout_sec:g}s",
                "timeout",
            )
        except Exception as exc:  # OpenBB providers raise several package-specific errors.
            return self._build_error_result(route.series_id, f"OpenBB fetch failed: {exc}", "openbb_error")

        if panel.empty:
            return self._build_error_result(route.series_id, "OpenBB returned no usable rows", "empty")

        if self._cache:
            self._write_raw(route.series_id, panel.to_json(date_format="iso", orient="records"))

        return ProviderResult(
            provider=route.source_id,
            series_id=route.source_series_id,
            frame=panel,
            source_url=f"openbb:{route.obb_path}",
            source_params={
                "source_engine": "openbb",
                "openbb_provider": route.provider,
                "route": route.obb_path,
                "params": _safe_params(route.params),
            },
            data_note="Acquired through OpenBB inside Harvester; downstream identity remains provider-native.",
        )

    def _obb(self) -> Any:
        if self._obb_client is not None:
            return self._obb_client
        try:
            from openbb import obb  # type: ignore
        except Exception as exc:
            raise RuntimeError(
                "OpenBB is not importable. Install the optional OpenBB backend or run with another provider."
            ) from exc
        self._obb_client = obb
        return obb


@contextmanager
def _operation_timeout(seconds: float) -> Iterator[None]:
    """Bound one OpenBB call when running in the Harvester main process.

    OpenBB's endpoint wrappers do not expose a consistent requests timeout.
    The daily Harvester runs in a dedicated subprocess on macOS/Linux, so a
    process-local alarm is a safer boundary than allowing one endpoint to hold
    the entire release indefinitely. Calls made from worker threads simply
    rely on the outer Harvester subprocess timeout.
    """
    if seconds <= 0 or threading.current_thread() is not threading.main_thread() or not hasattr(signal, "SIGALRM"):
        yield
        return

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, 0)

    def _raise_timeout(_signum: int, _frame: Any) -> None:
        raise TimeoutError

    signal.signal(signal.SIGALRM, _raise_timeout)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, *previous_timer)


def _routes_for_provider(openbb_provider: str) -> dict[str, OpenBBSeriesRoute]:
    if not openbb_provider:
        return dict(DEFAULT_OPENBB_ROUTES)
    # Build route map keyed by series_id (not route name) so that
    # fetch_series("HYG") finds the correct route regardless of whether
    # the route key is "HYG" or "HYG_YF".
    result: dict[str, OpenBBSeriesRoute] = {}
    for key, route in DEFAULT_OPENBB_ROUTES.items():
        if route.provider == openbb_provider:
            result[route.series_id] = route
    return result


def _resolve_attr(obj: Any, dotted: str) -> Any:
    current = obj
    for part in dotted.split("."):
        current = getattr(current, part)
    return current


def _to_frame(result: Any) -> pd.DataFrame:
    if isinstance(result, pd.DataFrame):
        return result.copy()
    if hasattr(result, "to_df"):
        return result.to_df().copy()
    if hasattr(result, "results"):
        return pd.DataFrame(result.results)
    return pd.DataFrame(result)


def _normalize_frame(frame: pd.DataFrame, route: OpenBBSeriesRoute) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()

    df = frame.copy()
    if "date" not in df.columns:
        if df.index.name or not isinstance(df.index, pd.RangeIndex):
            df = df.reset_index()
        if "index" in df.columns and "date" not in df.columns:
            df = df.rename(columns={"index": "date"})
    if "date" not in df.columns:
        first = df.columns[0]
        df = df.rename(columns={first: "date"})

    value_column = route.value_column
    if value_column is None or value_column not in df.columns:
        value_column = _first_numeric_column(df, exclude={"date"})
    if value_column is None:
        return pd.DataFrame()

    out = pd.DataFrame({
        "date": pd.to_datetime(df["date"], errors="coerce"),
        "value": pd.to_numeric(df[value_column], errors="coerce"),
        "unit": route.unit,
        "frequency": route.frequency,
        "source_id": route.source_id,
        "source_series_id": route.source_series_id,
        "series_id": f"{route.source_id.upper()}:{route.source_series_id}",
    })
    out = out.dropna(subset=["date", "value"]).sort_values("date").reset_index(drop=True)
    return out


def _first_numeric_column(frame: pd.DataFrame, *, exclude: set[str]) -> str | None:
    for column in frame.columns:
        if str(column) in exclude:
            continue
        values = pd.to_numeric(frame[column], errors="coerce")
        if values.notna().any():
            return str(column)
    return None


def _safe_params(params: dict[str, Any]) -> dict[str, Any]:
    blocked = {"api_key", "token", "secret", "password"}
    return {k: ("<redacted>" if any(b in k.lower() for b in blocked) else v) for k, v in params.items()}


def _load_env_file(settings_env: str | Path | None) -> None:
    if settings_env is None:
        default = Path.cwd() / "OpenBB" / "settings.env"
        settings_env = default if default.exists() else None
    if settings_env is None:
        return
    path = Path(settings_env).expanduser()
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


__all__ = ["DEFAULT_OPENBB_ROUTES", "OpenBBProvider", "OpenBBSeriesRoute"]
