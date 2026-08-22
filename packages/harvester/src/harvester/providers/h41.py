from __future__ import annotations

import logging
import json
import os
import time
from io import StringIO
from typing import Any

import pandas as pd

from harvester.http_gateway import GatewayError, GatewayHTTPError, OwnedHTTPGateway
from harvester.providers.base import OfficialProvider, ProviderResult

logger = logging.getLogger(__name__)

FRED_BASE = "https://api.stlouisfed.org/fred"
FED_DDP_BASE = "https://www.federalreserve.gov/datadownload/DownloadTable.aspx"
H41_DDP_TABLE1_PACKAGE = "f52e72511be65e16f71d4f5858951312"
# The public FRED graph fallback is a larger historical CSV. Keep the normal
# H.4.1 gateway bounded and give the graph request its own short-lived client;
# a stuck graph request must not hold the direct Table 1 connection open.
H41_GATEWAY_TIMEOUT_SEC = 30.0
H41_GRAPH_TIMEOUT_SEC = 15.0

# H.4.1 direct path:
#   The Board of Governors publishes H.4.1 ("Factors Affecting Reserve
#   Balances") through the Federal Reserve Data Download Program (DDP).  This
#   provider now fetches the relevant DDP Table 1 series directly and keeps the
#   older FRED bridge only as an explicit fallback for resilience.

H41_FRED_MAP: dict[str, str] = {
    "discount_window": "WORAL",
    "primary_credit": "WPCREDIT",
    "btfp": "H41RESPPALDKNWW",
}

H41_DDP_MAP: dict[str, str | tuple[str, ...]] = {
    "discount_window": (
        "H41/H41/RESPPALD_N.WW",  # total loans / discount-window line
        "H41/H41/RESPPALDP_N.WW",  # legacy component fallback: primary credit
        "H41/H41/RESPPALDQ_N.WW",  # legacy component fallback: secondary credit
        "H41/H41/RESPPALDS_N.WW",  # legacy component fallback: seasonal credit
    ),
    "primary_credit": "H41/H41/RESPPALDP_N.WW",
    # BTFP is historical and no longer appears in the current preformatted
    # Table 1 package. Keep its historical DDP identity for auditability; a
    # missing current-table row falls through to the public FRED graph route
    # rather than being relabeled as total loans.
    "btfp": "H41/H41/RESPPALDK_N.WW",
}

H41_UNITS: dict[str, str] = {
    "discount_window": "mil_usd",
    "primary_credit": "mil_usd",
    "btfp": "mil_usd",
}

# ── H41_SOURCE_NOTE ──────────────────────────────────────────────────
# Each entry below gives the precise H.4.1 table reference for future
# direct-ingestion work.  These are NOT consumed by the bridge path.
# When a direct parser is implemented, verify every entry against the
# most recent H.4.1 release (published every Thursday at 4:30 PM ET).
#
# Field structure per entry:
#   - table:        H.4.1 table number and full title
#   - row_label:    exact row label as printed (may change across vintages)
#   - field_semantic: what this number represents in structural terms
#   - sign:         expected sign (>0 = asset / <0 = liability)
#   - units:        display units in the release (converted to mil_usd)
#   - expiry_behavior:
#       disappears:  row removed from table after facility closes
#       zeros:       row remains but reports 0.00
#       merges:      row consolidated into another line (specify which)
#       unknown:     not yet observed post-expiry; needs monitoring
H41_SOURCE_NOTE: dict[str, dict[str, str]] = {
    "discount_window": {
        "table": "Table 1 — Factors Affecting Reserve Balances of Depository Institutions (Wednesday Level)",
        "row_label": "Discount window (or 'Primary, secondary, and seasonal credit' grouped line)",
        "field_semantic": "Total discount-window lending outstanding. Funding-freedom stress signal.",
        "sign": ">0 (asset: loans to depository institutions)",
        "units": "Millions of U.S. Dollars (converted to mil_usd)",
        "expiry_behavior": "disappears or zeros — facility is permanent; zero means no banks are borrowing, not that the facility is gone",
        "fred_series": "WORAL — Assets: Discount Window Borrowing: Wednesday Level",
        "fred_frequency": "Weekly, Ending Wednesday",
        "fred_units": "Millions of U.S. Dollars",
    },
    "primary_credit": {
        "table": "Table 1 — Factors Affecting Reserve Balances of Depository Institutions (Wednesday Level)",
        "row_label": "Primary credit (sub-line under loans / liquidity facilities)",
        "field_semantic": "Primary-credit usage. Visible trace of emergency funding substitution.",
        "sign": ">0 (asset: loans to depository institutions)",
        "units": "Millions of U.S. Dollars (converted to mil_usd)",
        "expiry_behavior": "disappears or zeros — facility is permanent; zero means normal (no emergency borrowing)",
        "fred_series": "WPCREDIT — Assets: Liquidity and Credit Facilities: Loans: Primary Credit: Wednesday Level",
        "fred_frequency": "Weekly, Ending Wednesday",
        "fred_units": "Millions of U.S. Dollars",
    },
    "btfp": {
        "table": "Table 1 — Factors Affecting Reserve Balances of Depository Institutions (Wednesday Level)",
        "row_label": "Bank Term Funding Program, Net (sub-line under 'Loans' / 'Liquidity and Credit Facilities')",
        "field_semantic": "BTFP outstanding. Emergency funding substitution pressure. Currently observed_zero post-expiry (ceased new lending March 2024; outstanding loans may persist through maturity).",
        "sign": ">0 (asset: loans to depository institutions)",
        "units": "Millions of U.S. Dollars (converted to mil_usd)",
        "expiry_behavior": "historical row may disappear from the current preformatted Table 1 after facility closure; public FRED graph preserves observed zeros after expiry. Zero values MUST be recorded as observed_zero (data quality OK, not an error).",
        "fred_series": "H41RESPPALDKNWW — Assets: Liquidity and Credit Facilities: Loans: Bank Term Funding Program, Net: Wednesday Level",
        "fred_frequency": "Weekly, Ending Wednesday",
        "fred_units": "Millions of U.S. Dollars, Not Seasonally Adjusted",
    },
}


class H41Provider(OfficialProvider):
    source_id = "h41"

    def __init__(
        self,
        api_key: str = "",
        data_root: str = "",
        cache: bool = True,
        user_agent: str = "StructuralRiskHarvester/0.1.0",
        allow_fred_fallback: bool = True,
        gateway: OwnedHTTPGateway | None = None,
    ) -> None:
        super().__init__(data_root=data_root, cache=cache, user_agent=user_agent)
        self._api_key = api_key or os.environ.get("FRED_API_KEY", "")
        self._allow_fred_fallback = allow_fred_fallback
        self._owns_gateway = gateway is None
        self._gateway = gateway or OwnedHTTPGateway(
            headers={"User-Agent": user_agent},
            timeout_sec=H41_GATEWAY_TIMEOUT_SEC,
        )

    def fetch_series(self, series_ids: list[str]) -> list[ProviderResult]:
        results: list[ProviderResult] = []
        for sid in series_ids:
            ddp_series = H41_DDP_MAP.get(sid)
            if ddp_series is None:
                results.append(
                    self._build_error_result(sid, f"no Federal Reserve DDP mapping for H41 field: {sid}", "unknown_field")
                )
                continue
            result = self._fetch_via_ddp(ddp_series, sid)
            if result.fetch_error and self._allow_fred_fallback:
                fred_sid = H41_FRED_MAP.get(sid)
                if fred_sid:
                    fallback = (
                        self._fetch_via_fred(fred_sid, sid)
                        if self._api_key
                        else self._fetch_via_fred_graph(fred_sid, sid)
                    )
                    if not fallback.fetch_error:
                        reasons = [
                            fallback.fetch_fallback_reason,
                            f"direct_h41_ddp_failed: {result.fetch_error}",
                        ]
                        fallback.fetch_fallback_reason = "; ".join(
                            reason for reason in reasons if reason
                        )
                    result = fallback
            results.append(result)
            if sid != series_ids[-1]:
                time.sleep(0.25)
        return results

    def _fetch_via_ddp(self, ddp_series: str | tuple[str, ...], h41_field: str) -> ProviderResult:
        series_codes = (ddp_series,) if isinstance(ddp_series, str) else ddp_series
        url = (
            f"{FED_DDP_BASE}?filetype=csv&label=include&layout=seriescolumn"
            f"&rel=H41&lastobs=5000&from=&to=&type=package"
            f"&series={H41_DDP_TABLE1_PACKAGE}"
        )
        try:
            resp = self._gateway.fetch(
                "h41",
                "ddp_csv",
                {
                    "filetype": "csv",
                    "label": "include",
                    "layout": "seriescolumn",
                    "rel": "H41",
                    "lastobs": 5000,
                    "from": "",
                    "to": "",
                    "type": "package",
                    "series": H41_DDP_TABLE1_PACKAGE,
                },
            )
            resp.raise_for_status()
            raw_bytes = resp.content
            text = raw_bytes.decode("utf-8-sig", errors="replace")
        except GatewayError as exc:
            msg = f"H41 direct DDP network error for {h41_field}: {exc}"
            logger.warning(msg)
            return self._build_error_result(h41_field, msg, "network_error")

        if "series definitions for the request could not be found" in text.lower():
            return self._build_error_result(h41_field, "H41 direct DDP rejected series definitions", "invalid_series")
        if self._cache:
            self._write_raw(f"h41_ddp_{h41_field}", raw_bytes)

        try:
            parsed = _parse_ddp_series_csv(text, series_codes, h41_field)
        except ValueError as exc:
            return self._build_error_result(h41_field, f"H41 direct DDP parse failed: {exc}", "parse_error")

        if parsed.empty:
            return self._build_error_result(h41_field, "H41 direct DDP returned no usable rows", "empty")

        parsed["unit"] = H41_UNITS.get(h41_field, "")
        parsed["frequency"] = "Weekly, Ending Wednesday"
        all_zero = bool((parsed["value"] == 0.0).all())
        status_detail = "observed_zero" if all_zero else "direct_h41_ddp"
        note = H41_SOURCE_NOTE.get(h41_field, {})
        result = ProviderResult(
            provider=self.source_id,
            series_id=h41_field,
            frame=parsed,
            source_url=url,
            source_params={
                "method": "federal_reserve_ddp_csv",
                "verification_status": "DIRECT",
                "status_detail": status_detail,
                "ddp_series": list(series_codes),
                "ddp_package": H41_DDP_TABLE1_PACKAGE,
                "ddp_layout": "preformatted_table1",
                "h41_table": note.get("table", ""),
                "h41_row_label": note.get("row_label", ""),
                "field_semantic": note.get("field_semantic", ""),
                "expiry_behavior": note.get("expiry_behavior", ""),
            },
        )
        if all_zero:
            result.data_note = "observed_zero — facility may be expired/at floor; data quality OK, not an error"
        return result

    def _fetch_via_fred(self, fred_series_id: str, h41_field: str) -> ProviderResult:
        url = f"{FRED_BASE}/series/observations"
        params = {
            "series_id": fred_series_id,
            "api_key": self._api_key,
            "file_type": "json",
            "sort_order": "asc",
        }
        try:
            resp = self._gateway.fetch("fred", "series_observations", params)
            if resp.status_code == 400 and "Bad Request" in resp.text:
                return self._build_error_result(
                    h41_field,
                    f"H41 via FRED: series {fred_series_id} returned 400 (may be discontinued or invalid)",
                    "invalid_series",
                )
            resp.raise_for_status()
            data = resp.json()
            raw_bytes = resp.content
        except GatewayHTTPError as exc:
            status = exc.status_code
            msg = f"H41 via FRED HTTP {status} for {fred_series_id}"
            logger.warning(msg)
            return self._build_error_result(h41_field, msg, "http_error")
        except GatewayError as exc:
            msg = f"H41 via FRED network error for {fred_series_id}: {exc}"
            logger.warning(msg)
            return self._build_error_result(h41_field, msg, "network_error")

        if self._cache:
            self._write_raw(f"h41_{fred_series_id}", raw_bytes)

        observations = data.get("observations", [])
        if not observations:
            return self._build_error_result(
                h41_field,
                f"no observations returned for H41 field via {fred_series_id}",
                "empty",
            )

        source_note_entry = H41_SOURCE_NOTE.get(h41_field, {})
        unit = H41_UNITS.get(h41_field, "")
        rows: list[dict[str, Any]] = []
        all_zero = True

        for obs in observations:
            date_val = obs.get("date", "")
            val = obs.get("value", "")
            if not date_val or val == "." or val == "":
                continue
            try:
                numeric = float(val)
            except (ValueError, TypeError):
                continue
            if numeric != 0.0:
                all_zero = False
            rows.append({
                "date": date_val,
                "value": numeric,
                "unit": unit,
                "frequency": data.get("frequency", "weekly"),
            })

        if not rows:
            return self._build_error_result(
                h41_field,
                f"all values unparseable for H41 field via {fred_series_id}",
                "empty",
            )

        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])

        status_detail: str | None = None
        if all_zero:
            status_detail = "observed_zero"
        else:
            status_detail = "provisional_fred_bridge"

        result = ProviderResult(
            provider=self.source_id,
            series_id=h41_field,
            frame=df,
            source_url=url,
            source_params={
                "fred_series_id": fred_series_id,
                "h41_field": h41_field,
                "method": "fred_bridge",
                "verification_status": "PROVISIONAL",
                "status_detail": status_detail,
                "fred_series_title": source_note_entry.get("fred_series", ""),
                "fred_frequency": source_note_entry.get("fred_frequency", ""),
                "fred_units": source_note_entry.get("fred_units", ""),
                "h41_table": source_note_entry.get("table", ""),
                "h41_row_label": source_note_entry.get("row_label", ""),
                "field_semantic": source_note_entry.get("field_semantic", ""),
                "expiry_behavior": source_note_entry.get("expiry_behavior", ""),
            },
        )

        if all_zero:
            result.data_note = "observed_zero — facility may be expired/at floor; data quality OK, not an error"
            logger.info(
                "H41 %s via %s: all observations are zero (observed_zero — facility may be expired/at floor)",
                h41_field, fred_series_id,
            )

        return result

    def _fetch_from_cached_fred_history(
        self,
        fred_series_id: str,
        h41_field: str,
        *,
        failure_reason: str,
    ) -> ProviderResult | None:
        """Use an already captured FRED history when graph transport is down.

        BTFP is a closed historical facility.  Its cached FRED API response is
        therefore a bounded, semantically equivalent fallback for a transient
        graph-proxy failure; it is explicitly marked cached/provisional and is
        never treated as a fresh provider success.
        """
        raw_bytes = self._read_raw(f"h41_{fred_series_id}")
        if not raw_bytes:
            return None
        try:
            payload = json.loads(raw_bytes.decode("utf-8"))
            observations = payload.get("observations", [])
            rows: list[dict[str, Any]] = []
            for observation in observations:
                date_val = observation.get("observation_date", observation.get("date", ""))
                value = observation.get("value", "")
                if not date_val or value in {"", ".", None}:
                    continue
                try:
                    numeric = float(value)
                except (TypeError, ValueError):
                    continue
                rows.append(
                    {
                        "date": date_val,
                        "value": numeric,
                        "unit": H41_UNITS.get(h41_field, ""),
                        "frequency": payload.get("frequency", "weekly"),
                    }
                )
            if not rows:
                return None
            frame = pd.DataFrame(rows)
            frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
            frame = frame.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
            if frame.empty:
                return None
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, AttributeError):
            logger.warning("Cached H41 FRED history is invalid: %s", fred_series_id)
            return None

        note = H41_SOURCE_NOTE.get(h41_field, {})
        return ProviderResult(
            provider=self.source_id,
            series_id=h41_field,
            frame=frame,
            fetch_fallback_reason=failure_reason,
            source_url=f"{FRED_BASE}/series/observations",
            source_params={
                "fred_series_id": fred_series_id,
                "method": "fred_cached_history",
                "verification_status": "CACHED",
                "status_detail": "cached_fred_history",
                "h41_table": note.get("table", ""),
                "h41_row_label": note.get("row_label", ""),
                "field_semantic": note.get("field_semantic", ""),
                "expiry_behavior": note.get("expiry_behavior", ""),
            },
        )
    def _fetch_via_fred_graph(self, fred_series_id: str, h41_field: str) -> ProviderResult:
        """Use the public FRED graph CSV for discontinued H.4.1 history."""
        url = "https://fred.stlouisfed.org/graph/fredgraph.csv"
        graph_gateway = self._gateway
        if self._owns_gateway:
            # Do not reuse the direct DDP client's proxy connection. Some
            # local proxies leave that connection half-open after a large
            # response, which otherwise creates a false graph timeout.
            graph_gateway = OwnedHTTPGateway(
                headers={"User-Agent": self._user_agent},
                timeout_sec=H41_GRAPH_TIMEOUT_SEC,
            )
        try:
            resp = graph_gateway.fetch("fred", "series_graph", {"id": fred_series_id})
            resp.raise_for_status()
            raw_bytes = resp.content
            frame = pd.read_csv(StringIO(resp.text))
        except GatewayHTTPError as exc:
            msg = f"H41 via public FRED graph HTTP {exc.status_code} for {fred_series_id}"
            logger.warning(msg)
            cached = self._fetch_from_cached_fred_history(
                fred_series_id,
                h41_field,
                failure_reason=f"public_fred_graph_failed: {msg}",
            )
            return cached or self._build_error_result(h41_field, msg, "http_error")
        except (GatewayError, ValueError, pd.errors.ParserError) as exc:
            msg = f"H41 via public FRED graph failed for {fred_series_id}: {exc}"
            logger.warning(msg)
            cached = self._fetch_from_cached_fred_history(
                fred_series_id,
                h41_field,
                failure_reason=f"public_fred_graph_failed: {msg}",
            )
            return cached or self._build_error_result(h41_field, msg, "parse_error")
        finally:
            if graph_gateway is not self._gateway:
                graph_gateway.close()

        date_col = next(
            (col for col in frame.columns if str(col).lower() in {"date", "observation_date"}),
            None,
        )
        value_col = next((col for col in frame.columns if str(col).lower() == fred_series_id.lower()), None)
        if date_col is None or value_col is None:
            return self._build_error_result(
                h41_field,
                f"public FRED graph schema missing Date/{fred_series_id}",
                "parse_error",
            )
        dates = pd.to_datetime(frame[date_col], errors="coerce")
        values = pd.to_numeric(frame[value_col], errors="coerce")
        parsed = pd.DataFrame({"date": dates, "value": values}).dropna().sort_values("date")
        if parsed.empty:
            return self._build_error_result(
                h41_field,
                f"public FRED graph returned no observations for {fred_series_id}",
                "empty",
            )
        parsed["unit"] = H41_UNITS.get(h41_field, "")
        parsed["frequency"] = "Weekly, Ending Wednesday"
        if self._cache:
            self._write_raw(f"h41_{fred_series_id}_graph", raw_bytes)
        note = H41_SOURCE_NOTE.get(h41_field, {})
        return ProviderResult(
            provider=self.source_id,
            series_id=h41_field,
            frame=parsed.reset_index(drop=True),
            source_url=url,
            source_params={
                "fred_series_id": fred_series_id,
                "method": "fred_public_graph",
                "verification_status": "PROVISIONAL",
                "status_detail": "provisional_fred_graph",
                "h41_table": note.get("table", ""),
                "h41_row_label": note.get("row_label", ""),
                "field_semantic": note.get("field_semantic", ""),
                "expiry_behavior": note.get("expiry_behavior", ""),
            },
        )


def _parse_ddp_series_csv(text: str, series_codes: tuple[str, ...], h41_field: str) -> pd.DataFrame:
    if "<table" in text.lower():
        return _parse_ddp_series_table_html(text, series_codes, h41_field)
    df = pd.read_csv(StringIO(text), comment="#")
    if df.empty:
        return pd.DataFrame(columns=["date", "value"])

    date_col = _find_date_column(df)
    if date_col is None:
        raise ValueError("date column not found")

    values = pd.Series(0.0, index=df.index, dtype="float64")
    matched = 0
    codes_to_use = series_codes
    if h41_field == "discount_window":
        total_code = next((code for code in series_codes if code.endswith("RESPPALD_N.WW")), None)
        if total_code is not None and _find_series_column(df, total_code) is not None:
            codes_to_use = (total_code,)
    for code in codes_to_use:
        col = _find_series_column(df, code)
        if col is None:
            continue
        matched += 1
        values = values.add(pd.to_numeric(df[col], errors="coerce").fillna(0.0), fill_value=0.0)
    if matched == 0:
        raise ValueError(f"none of the expected DDP series columns were found for {h41_field}")

    out = pd.DataFrame({
        "date": pd.to_datetime(df[date_col], errors="coerce"),
        "value": values,
    })
    out = out.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    return out


def _parse_ddp_series_table_html(
    text: str,
    series_codes: tuple[str, ...],
    h41_field: str,
) -> pd.DataFrame:
    """Parse the Board's preformatted Table 1 HTML response."""
    try:
        tables = pd.read_html(StringIO(text))
    except (ValueError, ImportError) as exc:
        raise ValueError("H41 DDP Table 1 HTML did not contain a readable table") from exc
    table = next(
        (
            candidate
            for candidate in tables
            if any(str(column).strip().lower() == "series" for column in candidate.columns)
        ),
        None,
    )
    if table is None or table.empty:
        raise ValueError("H41 DDP Table 1 HTML table is empty")
    series_col = next(
        column for column in table.columns if str(column).strip().lower() == "series"
    )
    date_columns = [
        column
        for column in table.columns
        if pd.notna(pd.to_datetime(str(column).strip(), errors="coerce"))
    ]
    if not date_columns:
        raise ValueError("H41 DDP Table 1 HTML has no observation dates")
    labels = table[series_col].astype(str).str.strip()
    dates = pd.to_datetime([str(column) for column in date_columns])
    values = pd.Series(0.0, index=dates)
    matched = 0
    codes_to_use = series_codes
    if h41_field == "discount_window":
        total_code = next((code for code in series_codes if code.endswith("RESPPALD_N.WW")), None)
        if total_code is not None and labels.isin({total_code, total_code.split("/")[-1]}).any():
            codes_to_use = (total_code,)
    for code in codes_to_use:
        tail = code.split("/")[-1]
        mask = labels.isin({code, tail})
        if not mask.any():
            continue
        matched += int(mask.sum())
        rows = table.loc[mask, date_columns].apply(pd.to_numeric, errors="coerce").fillna(0.0)
        values = values.add(rows.sum(axis=0).to_numpy(dtype=float), fill_value=0.0)
    if matched == 0:
        raise ValueError(f"none of the expected DDP series rows were found for {h41_field}")
    return pd.DataFrame({"date": values.index, "value": values.to_numpy()})


def _find_date_column(df: pd.DataFrame) -> str | None:
    candidates = {"date", "time period", "time_period", "observation_date"}
    for col in df.columns:
        normalized = str(col).strip().lower()
        if normalized in candidates or normalized.startswith("time"):
            return str(col)
    return str(df.columns[0]) if len(df.columns) else None


def _find_series_column(df: pd.DataFrame, code: str) -> str | None:
    code_tail = code.split("/")[-1]
    compact = code_tail.replace("_", "").replace(".", "").upper()
    for col in df.columns:
        label = str(col).strip()
        normalized = label.replace("_", "").replace(".", "").upper()
        if label == code or label.endswith(code_tail) or compact in normalized:
            return str(col)
    return None
