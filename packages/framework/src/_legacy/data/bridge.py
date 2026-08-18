"""
LEGACY ACQUISITION SHIM.
This bridge still adapts legacy provider-shaped data into structural evidence
during migration. New Deformation code must use src/data_access/.
retire_after: 2026-10-15
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from src._legacy.data.data_sources import DEFAULT_PROXY_SERIES_MAP
from src.core.interfaces import DataSource
from src.data.contracts import (
    StructuralPresetResult,
    build_structural_fetch_plan,
)
from src.data.quality.manifest import DataEvidenceManifest, SeriesEvidenceRecord

logger = logging.getLogger(__name__)


class DataHubBridge(DataSource):
    """
    Single-track adapter: drives the main pipeline fetch through DataHub's
    structural preset path, eliminating the dual DataSourceFactory track.

    The pipeline calls fetch(series_ids, start, end) exactly as before and
    gets back the same M_PROXY/D_PROXY/K_PROXY/X_PROXY DataFrame.  Internally
    every byte of data travels through DataHub's admission-checked, preset-
    driven path.

    After each fetch, `last_evidence_manifest` holds per-series provenance:
    which series were real, which fell back, which channels have degraded data.
    """

    def __init__(
        self,
        hub: Any,  # DataHub — typed as Any to avoid circular import at module level
        proxy_series_map: dict[str, list[Any]] | None = None,
        fallback_seed: int = 42,
    ) -> None:
        self._hub = hub
        self._proxy_series_map = proxy_series_map or DEFAULT_PROXY_SERIES_MAP
        self._fallback_seed = fallback_seed
        self._last_manifest: DataEvidenceManifest | None = None

    # ------------------------------------------------------------------
    # DataSource interface
    # ------------------------------------------------------------------

    def fetch(self, series_ids: list[str], start: str, end: str) -> pd.DataFrame:
        plan = build_structural_fetch_plan(series_ids=series_ids)
        if not plan.presets:
            logger.warning("DataHubBridge: no structural presets resolved for %s", series_ids)
            return pd.DataFrame()

        result = self._hub.fetch_structural_presets(
            preset_names=list(plan.preset_names),
            start=start,
            end=end,
        )

        # Index components by (output_series_id, request_key)
        component_frames: dict[str, dict[str, pd.Series]] = {}  # proxy_id → {req_key → series}
        series_records: list[SeriesEvidenceRecord] = []

        for item in result.items:
            if not isinstance(item, StructuralPresetResult):
                continue
            proxy_id = item.preset.output_series_id
            component_frames.setdefault(proxy_id, {})

            for series_result in item.items:
                req_key = series_result.request_key
                frame = series_result.frame

                # Extract a single Series from the result frame
                raw = self._extract_series(frame, req_key)
                component_frames[proxy_id][req_key] = raw

                # Determine data quality
                is_mock = series_result.metadata.get("mode") == "mock"
                is_empty = raw.dropna().empty

                if is_mock:
                    fallback_reason: str | None = "mock"
                    has_real = False
                elif is_empty:
                    fallback_reason = "empty"
                    has_real = False
                else:
                    fallback_reason = None
                    has_real = True

                series_records.append(
                    SeriesEvidenceRecord(
                        series_id=req_key,
                        provider=series_result.provider,
                        channel=item.preset.channel,
                        measurement_block=item.preset.measurement_block,
                        evidence_role=item.preset.evidence_role,
                        preset_name=item.preset.name,
                        row_count=int(raw.notna().sum()),
                        has_real_data=has_real,
                        fallback_reason=fallback_reason,
                    )
                )

        # Record errors as failed series
        for error in result.errors:
            req_key = error.request.get("request_key", str(error.request))
            series_records.append(
                SeriesEvidenceRecord(
                    series_id=req_key,
                    provider=error.provider,
                    channel=None,
                    measurement_block=None,
                    evidence_role=None,
                    preset_name=None,
                    row_count=0,
                    has_real_data=False,
                    fallback_reason="error",
                )
            )

        # Build evidence manifest before aggregation
        run_date = end
        self._last_manifest = DataEvidenceManifest.build(run_date=run_date, series_records=series_records)

        if self._last_manifest.any_fallback:
            logger.warning(
                "DataHubBridge[%s]: research_quality=%s  fallback series=%s  channels=%s",
                end,
                self._last_manifest.research_quality,
                [r.series_id for r in self._last_manifest.fallback_series()],
                self._last_manifest.channels_with_fallback(),
            )

        # Aggregate component series into proxy values
        out = pd.DataFrame()
        for sid in series_ids:
            components = self._proxy_series_map.get(sid)
            if not components:
                continue
            component_dict = component_frames.get(sid, {})
            aggregated = self._aggregate_proxy(components, component_dict)
            if aggregated is not None and not aggregated.empty:
                if out.empty:
                    out = pd.DataFrame(index=aggregated.index)
                out[sid] = aggregated.reindex(out.index)
            else:
                if not out.empty:
                    out[sid] = np.nan

        if out.empty:
            return pd.DataFrame()

        return out.sort_index()

    def available_series(self) -> list[str]:
        return list(self._proxy_series_map.keys())

    @property
    def last_evidence_manifest(self) -> DataEvidenceManifest | None:
        return self._last_manifest

    # ------------------------------------------------------------------
    # Internal aggregation (mirrors ProxyAggregationDataSource logic)
    # ------------------------------------------------------------------

    def _extract_series(self, frame: pd.DataFrame, req_key: str) -> pd.Series:
        if frame is None or frame.empty:
            return pd.Series(dtype=float)
        if req_key in frame.columns:
            return pd.to_numeric(frame[req_key], errors="coerce")
        # Try the first numeric column
        for col in frame.columns:
            s = pd.to_numeric(frame[col], errors="coerce")
            if s.notna().any():
                return s.rename(req_key)
        return pd.Series(dtype=float)

    def _aggregate_proxy(
        self,
        components: list[Any],
        component_dict: dict[str, pd.Series],
    ) -> pd.Series | None:
        normalized: list[pd.Series] = []
        for component in components:
            parsed = _parse_component(component)
            if parsed is None:
                continue
            source_id, weight, invert = parsed
            raw = component_dict.get(source_id)
            if raw is None or raw.dropna().empty:
                continue
            s = pd.to_numeric(raw, errors="coerce").replace([np.inf, -np.inf], np.nan)
            if invert:
                s = -s
            s = s * weight
            s = _zscore(s)
            normalized.append(s)

        if not normalized:
            return None

        frame = pd.concat(normalized, axis=1)
        return frame.mean(axis=1, skipna=True)


# ------------------------------------------------------------------
# Pure functions (no state, easy to test)
# ------------------------------------------------------------------

def _parse_component(component: Any) -> tuple[str, float, bool] | None:
    """Parse a component spec like '-FRED:T10Y2Y' or '2.0*FRED:DFF'."""
    if isinstance(component, dict):
        sid = str(component.get("id", "")).strip()
        if not sid:
            return None
        return sid, float(component.get("weight", 1.0)), bool(component.get("invert", False))

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
        lhs, rhs = lhs.strip(), rhs.strip()
        try:
            weight = float(lhs)
            token = rhs
        except ValueError:
            try:
                weight = float(rhs)
            except ValueError:
                logger.debug("Unweighted legacy component token: %s", token)
            token = lhs

    return (token, weight, invert) if token else None


def _zscore(s: pd.Series) -> pd.Series:
    finite = s.replace([np.inf, -np.inf], np.nan).dropna()
    if finite.empty:
        return s * np.nan
    mean = float(finite.mean())
    std = float(finite.std(ddof=0))
    if not np.isfinite(std) or std == 0:
        return s - mean
    return (s - mean) / std
"""
LEGACY ACQUISITION SHIM.
This bridge still adapts legacy provider-shaped data into structural evidence
during migration. New Deformation code must use src/data_access/.
retire_after: 2026-10-15
"""
