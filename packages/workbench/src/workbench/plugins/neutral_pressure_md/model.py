"""Pure M/D model implementation behind the generic model protocol.

The calculation is intentionally the existing causal-z-score/component-mean
algorithm.  It receives data through ``ModelContext`` and returns an opaque
private payload; it does not know about Dagster, judgment, secrets, or output
publication.
"""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from workbench.model_protocol import (
    ModelContext,
    ModelManifest,
    MeasurementModel,
    MeasurementRequest,
    ModelResult,
    PROTOCOL_VERSION,
)

from .manifest import manifest_for

GAUGES: dict[str, dict[str, Any]] = {
    "M": {
        "product_name": "funding_mismatch_pressure",
        "display_name": "Funding mismatch pressure",
        "series": (
            "DERIVED:CP_TBILL_SPREAD",
            "DERIVED:SOFR_IORB_SPREAD",
            "FRED:NFCICREDIT",
        ),
    },
    "D": {
        "product_name": "market_constraint_pressure",
        "display_name": "Market constraint pressure",
        "series": (
            "FRED:NFCIRISK",
            "CBOE:MOVE",
            "DERIVED:SPX_ROLL_SPREAD",
        ),
    },
}


def _series(panel: pd.DataFrame, series_id: str) -> pd.Series:
    rows = panel.loc[panel["series_id"] == series_id, ["date", "value"]].copy()
    if rows.empty:
        return pd.Series(dtype=float, name=series_id)
    rows["date"] = pd.to_datetime(rows["date"], utc=True).dt.tz_convert(None)
    rows["value"] = pd.to_numeric(rows["value"], errors="coerce")
    return (
        rows.dropna(subset=["date"])
        .sort_values("date")
        .drop_duplicates("date", keep="last")
        .set_index("date")["value"]
        .rename(series_id)
    )


def _causal_zscore(series: pd.Series, window: int = 756, min_periods: int = 126) -> pd.Series:
    mean = series.rolling(window, min_periods=min_periods).mean()
    std = series.rolling(window, min_periods=min_periods).std().replace(0.0, np.nan)
    return ((series - mean) / std).clip(-4.0, 4.0)


def build_pressure_history(panel: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Compute the frozen M/D history without any runtime or path access."""
    required = {"date", "series_id", "value"}
    missing = required - set(panel.columns)
    if missing:
        raise ValueError(f"neutral pressure panel missing columns: {sorted(missing)}")
    panel_dates = pd.to_datetime(panel["date"], utc=True, errors="coerce").dt.tz_convert(None).dropna()
    if panel_dates.empty:
        raise ValueError("neutral pressure panel has no usable dates")
    shared_calendar = pd.date_range(
        panel_dates.min().normalize(),
        panel_dates.max().normalize(),
        freq="B",
    )
    components: dict[str, pd.Series] = {}
    metadata: dict[str, Any] = {}
    for key, spec in GAUGES.items():
        gauge_components: list[pd.Series] = []
        component_meta: list[dict[str, Any]] = []
        for series_id in spec["series"]:
            raw = _series(panel, series_id)
            zscore = _causal_zscore(raw)
            components[f"{key}:{series_id}"] = zscore
            usable = zscore.dropna()
            component_meta.append(
                {
                    "series_id": series_id,
                    "raw_rows": int(raw.notna().sum()),
                    "usable_rows": int(usable.shape[0]),
                    "last_observation": str(usable.index[-1].date()) if not usable.empty else None,
                    "status": "usable" if not usable.empty else "missing_or_short_history",
                }
            )
            if not usable.empty:
                gauge_components.append(zscore)
        if gauge_components:
            aligned = (
                pd.concat(gauge_components, axis=1)
                .sort_index()
                .reindex(shared_calendar)
                .ffill(limit=5)
            )
            gauge = aligned.mean(axis=1, skipna=True)
            minimum = 2 if len(gauge_components) >= 2 else 1
            gauge = gauge.where(aligned.notna().sum(axis=1) >= minimum)
        else:
            gauge = pd.Series(dtype=float)
        components[key] = gauge.rename(key)
        metadata[key] = {
            "product_name": spec["product_name"],
            "display_name": spec["display_name"],
            "components": component_meta,
            "required_usable_components": 2,
        }
    history = pd.concat({"M": components["M"], "D": components["D"]}, axis=1).sort_index()
    history.index.name = "date"
    return history, metadata


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 4) if np.isfinite(number) else None


def _state(m_value: float | None, d_value: float | None) -> str:
    values = [value for value in (m_value, d_value) if value is not None]
    if len(values) < 2:
        return "PRESSURE_READOUT_UNAVAILABLE"
    average = sum(values) / len(values)
    if average >= 1.0:
        return "BROAD_PRESSURE_HIGH"
    if average >= 0.35:
        return "PRESSURE_BUILDING"
    if average <= -0.35:
        return "PRESSURE_EASING"
    return "PRESSURE_BALANCED"


def _panel_digest(panel: pd.DataFrame) -> str:
    ordered = panel.reindex(sorted(panel.columns), axis=1).copy()
    hashed = pd.util.hash_pandas_object(ordered, index=True).values.tobytes()
    return hashlib.sha256(hashed).hexdigest()


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


class NeutralPressureMdModel(MeasurementModel):
    """First production-path implementation of the generic model protocol."""

    manifest: ModelManifest = manifest_for(Path(__file__))

    def evaluate(self, request: MeasurementRequest, context: ModelContext) -> ModelResult:
        panel = context.data_access.read_table(request.input_ref)
        if not isinstance(panel, pd.DataFrame):
            raise TypeError("neutral_pressure_md data_access must return a pandas DataFrame")
        history, metadata = build_pressure_history(panel)
        usable = history.dropna(how="all")
        if usable.empty:
            raise ValueError("neutral pressure gauges have no usable observations")

        last = usable.iloc[-1]
        m_value = _finite(last.get("M"))
        d_value = _finite(last.get("D"))
        velocity = history.diff(20).iloc[-1] if len(history) > 20 else pd.Series(dtype=float)
        velocity_20d = {"score_0": _finite(velocity.get("M")), "score_1": _finite(velocity.get("D"))}
        n_deteriorating = sum(
            1 for value in velocity_20d.values() if value is not None and value > 0.2
        )
        state = _state(m_value, d_value)
        as_of = usable.index[-1].to_pydatetime().replace(tzinfo=UTC).isoformat()
        both_live = m_value is not None and d_value is not None
        quality = "FULL_WITH_WARNINGS" if both_live else "PARTIAL"
        release_id = str(context.metadata.get("release_id") or "unknown")
        run_id = str(
            request.parameters.get("run_id")
            or context.metadata.get("run_id")
            or f"neutral_pressure_{as_of[:10]}"
        )
        scores: dict[str, float | None] = {"score_0": m_value, "score_1": d_value}
        diagnostics = {
            "quality_status": quality,
            "coverage_ratio": f"{int(m_value is not None) + int(d_value is not None)}/2",
            "algorithm": "causal_zscore_and_component_mean",
            "carry_forward_policy": "component_ffill_limit_5_on_shared_business_day_calendar",
            "n_deteriorating": n_deteriorating,
            "channels_available": int(m_value is not None) + int(d_value is not None),
        }
        payload = {
            "gauge_values": {"M": m_value, "D": d_value},
            "velocity_20d": velocity_20d,
            "component_metadata": metadata,
            "release_id": release_id,
            "run_id": run_id,
            "state": state,
            "quality_status": quality,
            "common_sample_available": bool(not history.dropna(subset=["M", "D"]).empty),
            "n_deteriorating": n_deteriorating,
        }
        return ModelResult(
            protocol_version=PROTOCOL_VERSION,
            model_id=self.manifest.model_id,
            model_version=self.manifest.model_version,
            as_of=_iso(request.as_of) or as_of,
            available_at=datetime.now(UTC).isoformat(),
            status="available" if both_live else "degraded",
            confidence=0.7 if both_live else 0.35,
            state=state,
            scores=scores,
            diagnostics=diagnostics,
            model_payload=payload,
            provenance={
                "producer": self.manifest.model_id,
                "run_id": run_id,
                "source_release_id": release_id,
                "input_ref": request.input_ref,
                "claim_ceiling": "bounded_neutral_measurement",
            },
            input_digest=str(context.metadata.get("input_digest") or _panel_digest(panel)),
            implementation_digest=self.manifest.implementation_digest,
            authority="DIAGNOSTIC_ONLY",
            claim_ceiling="bounded_neutral_measurement",
            diagnostic_only=True,
            runtime_artifacts={"pressure_history": history},
        )


__all__ = ["GAUGES", "NeutralPressureMdModel", "build_pressure_history"]
