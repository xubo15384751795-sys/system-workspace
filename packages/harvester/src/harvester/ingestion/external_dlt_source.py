"""dlt shadow source for the CFTC TFF Leveraged-Funds E-mini S&P 500 indicator.

Shadow-only pilot: this module is not imported by any provider, registry, or
pipeline entrypoint. It re-implements the exact normalization of
``harvester.providers.external_indicators._parse_cftc_tff_lev_sp`` (micro
E-mini exclusion, report-date/lev-money column detection, net = long - short,
per-date sum aggregation) so its output can be diffed against the legacy
series without touching the default path.

Schema contract mapping: dlt ``evolution_strategy="freeze"`` on the ``date``
and ``value`` columns corresponds to the repo's BLOCK tier — a payload that
would change those columns' type or nullability fails the load instead of
silently migrating the shadow table.

No network I/O happens here. Callers pass an already-fetched Socrata JSON
payload; only ``pipeline.run(...)`` performs I/O against the configured
destination.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Iterator

import dlt
import pandas as pd

SHADOW_TABLE_NAME = "cftc_cot_shadow"

# Repo BLOCK tier == dlt freeze. The table holds exactly the two canonical
# columns below, so kind-level freeze covers both.
_SCHEMA_CONTRACT: dict[str, Any] = {
    "columns": "freeze",
    "data_type": "freeze",
}

_COLUMNS: dict[str, Any] = {
    "date": {"data_type": "date", "nullable": False},
    "value": {"data_type": "double", "nullable": False},
}


def _decode_socrata_rows(payload_json: str | list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mirror _cftc_frame's JSON decoding (dict unwrap + row-array requirement)."""
    if isinstance(payload_json, list):
        decoded: Any = payload_json
    else:
        try:
            decoded = json.loads(payload_json)
        except json.JSONDecodeError as exc:
            raise ValueError("CFTC Socrata response is not valid JSON") from exc
        if isinstance(decoded, dict):
            decoded = decoded.get("data", decoded.get("results", decoded))
    if not isinstance(decoded, list):
        raise ValueError("CFTC Socrata JSON response must contain a row array")
    return decoded


def _iter_normalized_rows(payload_json: str | list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    rows = _decode_socrata_rows(payload_json)
    if not rows:
        return
    keys = {str(key).lower(): key for key in rows[0]}
    market_col = next((keys[name] for name in keys if name == "market_and_exchange_names"), None)
    date_col = next(
        (keys[name] for name in keys if "report_date" in name or name == "date"),
        None,
    )
    long_col = next(
        (keys[name] for name in keys if "lev_money" in name and "long" in name),
        None,
    )
    short_col = next(
        (keys[name] for name in keys if "lev_money" in name and "short" in name),
        None,
    )
    if date_col is None or long_col is None or short_col is None:
        raise ValueError("Unexpected CFTC TFF schema; need report date + lev money long/short")

    # Legacy semantics: drop MICRO E-MINI rows, net = long - short, drop
    # unparseable dates/values, then aggregate duplicate dates by SUM.
    per_date: dict[pd.Timestamp, float] = {}
    for row in rows:
        if market_col is not None:
            market = str(row.get(market_col, "")).upper()
            if market.startswith("MICRO E-MINI"):
                continue
        observed_at = pd.to_datetime(row.get(date_col), errors="coerce")
        value = pd.to_numeric(pd.Series([row.get(long_col)]), errors="coerce").iloc[0]
        value -= pd.to_numeric(pd.Series([row.get(short_col)]), errors="coerce").iloc[0]
        if pd.isna(observed_at) or pd.isna(value):
            continue
        day = observed_at.normalize()
        per_date[day] = per_date.get(day, 0.0) + float(value)

    for day in sorted(per_date):
        yield {"date": day.date(), "value": per_date[day]}


def _legacy_cftc_series(payload_json: str | list[dict[str, Any]]) -> pd.Series:
    """Load the legacy parser without making the dlt path a provider route."""
    from harvester.providers.external_indicators import _parse_cftc_tff_lev_sp

    payload: str | bytes
    if isinstance(payload_json, list):
        payload = json.dumps(payload_json)
    else:
        payload = payload_json
    legacy = _parse_cftc_tff_lev_sp(payload)
    if legacy.empty:
        return pd.Series(dtype="float64", name="CFTC_TFF_LEV_SP")
    # The legacy parser receives report-date strings.  Normalize here so the
    # comparison is about the canonical daily key, not an incidental timestamp
    # representation in a captured response.
    index = pd.to_datetime(legacy.index, errors="coerce").normalize()
    values = pd.to_numeric(legacy, errors="coerce")
    return (
        pd.Series(values.to_numpy(), index=index, name="CFTC_TFF_LEV_SP")
        .dropna()
        .groupby(level=0)
        .sum()
        .sort_index()
    )


def _shadow_cftc_series(payload_json: str | list[dict[str, Any]]) -> pd.Series:
    rows = list(_iter_normalized_rows(payload_json))
    if not rows:
        return pd.Series(dtype="float64", name="CFTC_TFF_LEV_SP")
    return pd.Series(
        [float(row["value"]) for row in rows],
        index=pd.to_datetime([row["date"] for row in rows]),
        name="CFTC_TFF_LEV_SP",
        dtype="float64",
    ).sort_index()


def build_cftc_shadow_parity_report(
    payload_json: str | list[dict[str, Any]],
) -> dict[str, Any]:
    """Compare the dlt shadow normalization with the legacy parser.

    This is deliberately a pure, offline comparison.  It does not run a dlt
    pipeline, fetch a URL, update a cache, or grant the shadow source any
    provider or publication authority.
    """
    legacy = _legacy_cftc_series(payload_json)
    shadow = _shadow_cftc_series(payload_json)
    legacy_values = {
        pd.Timestamp(day).date().isoformat(): float(value)
        for day, value in legacy.items()
    }
    shadow_values = {
        pd.Timestamp(day).date().isoformat(): float(value)
        for day, value in shadow.items()
    }
    legacy_dates = set(legacy_values)
    shadow_dates = set(shadow_values)
    missing_in_shadow = sorted(legacy_dates - shadow_dates)
    extra_in_shadow = sorted(shadow_dates - legacy_dates)
    value_mismatches = [
        {
            "date": day,
            "legacy": legacy_values[day],
            "dlt_shadow": shadow_values[day],
        }
        for day in sorted(legacy_dates & shadow_dates)
        if not math.isclose(
            legacy_values[day],
            shadow_values[day],
            rel_tol=1e-12,
            abs_tol=1e-12,
        )
    ]
    matched = not missing_in_shadow and not extra_in_shadow and not value_mismatches
    return {
        "schema_version": "system.harvester_dlt_shadow_parity.v1",
        "authority": "shadow_only",
        "provider": "cftc",
        "series_id": "CFTC_TFF_LEV_SP",
        "status": "MATCH" if matched else "MISMATCH",
        "execution_parity": "MATCH" if matched else "MISMATCH",
        "legacy_row_count": len(legacy_values),
        "dlt_shadow_row_count": len(shadow_values),
        "missing_in_shadow": missing_in_shadow,
        "extra_in_shadow": extra_in_shadow,
        "value_mismatches": value_mismatches,
        "promotion_allowed": False,
    }


def write_cftc_shadow_parity_report(
    payload_json: str | list[dict[str, Any]],
    output_path: Path,
) -> dict[str, Any]:
    """Atomically write a diagnostic parity record and return its payload."""
    report = build_cftc_shadow_parity_report(payload_json)
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            mode="w",
            encoding="utf-8",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(report, temporary, indent=2, sort_keys=True)
            temporary.write("\n")
        os.replace(temporary_path, output_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return report


@dlt.source(name="cftc_external")
def cftc_cot_source(payload_json: str | list[dict[str, Any]]):
    """Shadow dlt source mirroring the legacy CFTC_TFF_LEV_SP normalization."""

    @dlt.resource(
        name=SHADOW_TABLE_NAME,
        primary_key="date",
        write_disposition="append",
        columns=_COLUMNS,
        schema_contract=_SCHEMA_CONTRACT,
    )
    def cftc_cot_shadow(
        incremental: dlt.sources.incremental[Any] = dlt.sources.incremental("date"),
    ) -> Iterator[dict[str, Any]]:
        last_value = incremental.last_value
        for row in _iter_normalized_rows(payload_json):
            if last_value is not None and row["date"] <= last_value:
                continue
            yield row

    yield cftc_cot_shadow


__all__ = [
    "SHADOW_TABLE_NAME",
    "build_cftc_shadow_parity_report",
    "cftc_cot_source",
    "write_cftc_shadow_parity_report",
]
