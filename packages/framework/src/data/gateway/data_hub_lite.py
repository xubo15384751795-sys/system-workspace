"""
DataHub Lite — structural routing and Harvester-release serving layer.

This module replaces the acquisition half of DataHub.  It does NOT import
requests, httpx, urllib, openbb, or any legacy provider adapter.  It does
NOT read API keys.  All data arrives through an injected adapter that
conforms to the HarvesterAdapter load_bundle() / load_dataset() contract.

When no adapter is provided, fetch_series raises NotImplementedError.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence

import pandas as pd

from src.data.contracts import (
    DataRequestError,
    FetchResult,
    SeriesRequest,
    SeriesResult,
    StructuralPreset,
    build_structural_fetch_plan,
    default_structural_presets,
)
from src.data.gateway.evidence_router import (
    EvidenceRouter,
    ProviderCapability,
    default_provider_capabilities,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REQUIRED_BENCHMARK_COLUMNS: tuple[str, ...] = (
    "date",
    "series_id",
    "source_id",
    "source_series_id",
    "value",
    "unit",
    "frequency",
    "vintage_date",
    "quality_flag",
)


class BenchmarkPanelSchemaError(ValueError):
    """Raised when the Harvester bundle benchmark_panel is missing required columns."""


# ---------------------------------------------------------------------------
# Match strategy constants + risk levels
# ---------------------------------------------------------------------------

MATCH_EXACT_SOURCE_AND_SERIES = "exact_source_and_series"
MATCH_EXPLICIT_PRESET = "explicit_preset"
MATCH_PROVIDER_ALIAS = "provider_alias"
MATCH_SERIES_ID_ONLY = "series_id_only"
MATCH_SOURCE_SERIES_ID_ONLY = "source_series_id_only"
MATCH_FUZZY_SUBSTRING = "fuzzy_substring"
MATCH_NOT_FOUND = "not_found"

# Strategies that indicate a non-exact identity resolution.
_FUZZY_STRATEGIES = frozenset({
    MATCH_FUZZY_SUBSTRING,
    MATCH_SERIES_ID_ONLY,
    MATCH_NOT_FOUND,
})

_MATCH_RISK_LEVELS: dict[str, str] = {
    MATCH_EXACT_SOURCE_AND_SERIES: "low",
    MATCH_EXPLICIT_PRESET: "low_medium",
    MATCH_PROVIDER_ALIAS: "medium_low",
    MATCH_SERIES_ID_ONLY: "medium",
    MATCH_SOURCE_SERIES_ID_ONLY: "medium",
    MATCH_FUZZY_SUBSTRING: "high",
    MATCH_NOT_FOUND: "high",
}

# Known provider aliases: requested provider → canonical source_id in panel
_PROVIDER_ALIASES: dict[str, str] = {
    "fred": "fred_chicago_fed",  # fred may resolve to fred_chicago_fed in panel
}


# ---------------------------------------------------------------------------
# Panel lookup result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _PanelMatch:
    """Result of a benchmark_panel lookup, including match audit metadata."""

    frame: pd.DataFrame
    match_strategy: str
    matched_source_id: str
    matched_source_series_id: str
    match_audit: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return self.frame.empty

    @property
    def is_fuzzy(self) -> bool:
        return self.match_strategy in _FUZZY_STRATEGIES

    @property
    def risk_level(self) -> str:
        return _MATCH_RISK_LEVELS.get(self.match_strategy, "unknown")


# ---------------------------------------------------------------------------
# Release bundle protocol
# ---------------------------------------------------------------------------


class ReleaseBundleLike(Protocol):
    """Structural contract for a Harvester release bundle.

    At minimum the bundle must carry a release_id and a benchmark_panel
    DataFrame.  catalog and manifests are optional but encouraged.
    """

    release_id: str
    benchmark_panel: pd.DataFrame

    @property
    def catalog(self) -> Mapping[str, Any] | None: ...
    @property
    def manifests(self) -> Mapping[str, Any] | None: ...


# ---------------------------------------------------------------------------
# Adapter protocol — anything that quacks like HarvesterAdapter
# ---------------------------------------------------------------------------


class HarvesterAdapterLike(Protocol):
    """Structural contract for the data adapter injected into DataHubLite.

    Must provide load_bundle() returning an object whose benchmark_panel is a
    DataFrame with at least the columns listed in _REQUIRED_BENCHMARK_COLUMNS.
    """

    def load_bundle(self) -> Any: ...

    def load_dataset(self, name: str) -> pd.DataFrame: ...

    def list_datasets(self) -> list[str]: ...

    @property
    def current_release_id(self) -> str | None:
        """The adapter's notion of the current release identifier.

        When implemented, DataHubLite uses this for automatic cache
        invalidation.  When absent (returns None), DataHubLite logs a
        warning and skips automatic invalidation.
        """
        return None


# ---------------------------------------------------------------------------
# Schema guard — standalone validation + metadata generation
# ---------------------------------------------------------------------------


def _validate_benchmark_panel_schema(
    panel: pd.DataFrame,
    release_label: str = "",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Validate required columns, normalize types, and return schema metadata.

    Returns (normalized_panel, schema_metadata).

    Normalization:
      - date         → pd.Timestamp
      - vintage_date → pd.Timestamp (or NaT-preserving)
      - value        → numeric (coerce failures → NaN)
      - series_id    → string
      - source_id    → string.lower()
      - source_series_id → string
      - quality_flag → string / nullable string

    Does NOT mutate the input panel.
    """
    missing = sorted(set(_REQUIRED_BENCHMARK_COLUMNS) - set(panel.columns))
    if missing:
        raise BenchmarkPanelSchemaError(
            f"BenchmarkPanelSchemaError: missing required columns: {missing}"
            f"  release_id: {release_label or 'unknown'}"
        )

    panel = panel.copy()
    panel["date"] = pd.to_datetime(panel["date"], errors="coerce")
    panel["vintage_date"] = pd.to_datetime(panel["vintage_date"], errors="coerce")
    panel["value"] = pd.to_numeric(panel["value"], errors="coerce")
    panel["series_id"] = panel["series_id"].astype(str)
    panel["source_id"] = panel["source_id"].astype(str).str.lower()
    panel["source_series_id"] = panel["source_series_id"].astype(str)
    panel["quality_flag"] = panel["quality_flag"].astype(str)

    # Schema metadata
    date_min = panel["date"].min()
    date_max = panel["date"].max()
    metadata: dict[str, Any] = {
        "panel": "benchmark_panel",
        "row_count": int(len(panel)),
        "columns": [str(c) for c in panel.columns],
        "date_min": date_min.strftime("%Y-%m-%d") if pd.notna(date_min) else None,
        "date_max": date_max.strftime("%Y-%m-%d") if pd.notna(date_max) else None,
        "series_count": int(panel["series_id"].nunique()),
        "source_ids": sorted(panel["source_id"].unique().tolist()),
        "release_id": release_label or None,
    }

    return panel, metadata


# ---------------------------------------------------------------------------
# DataHubLite
# ---------------------------------------------------------------------------


@dataclass
class DataHubLite:
    """Structural routing layer backed by an optional Harvester-release adapter.

    When *adapter* is None every fetch_* method raises NotImplementedError.
    The class is safe to import and instantiate in any context — it carries
    no network dependencies.
    """

    adapter: HarvesterAdapterLike | None = None
    presets: tuple[StructuralPreset, ...] = field(default_factory=default_structural_presets)
    capabilities: tuple[ProviderCapability, ...] = field(default_factory=default_provider_capabilities)

    def __post_init__(self) -> None:
        self._router = EvidenceRouter(presets=self.presets, capabilities=self.capabilities)
        self._presets_by_name = {preset.name: preset for preset in self.presets}
        self._bundle: Any = None  # cached bundle from adapter
        self._panel: pd.DataFrame | None = None  # validated + normalized benchmark_panel
        self._schema_metadata: dict[str, Any] | None = None  # from schema guard
        self._loaded_release_id: str | None = None  # for cache invalidation

    # ------------------------------------------------------------------
    # diagnostics
    # ------------------------------------------------------------------

    @property
    def release_id(self) -> str | None:
        """The bundle_id from the loaded Harvester release, or None."""
        if self._bundle is None:
            return None
        return getattr(self._bundle, "bundle_id", None)

    @property
    def bundle(self) -> Any:
        """The cached Harvester bundle, or None if not yet loaded.

        Raises NotImplementedError when no adapter is configured.
        """
        return self._ensure_bundle()

    @property
    def panel(self) -> pd.DataFrame | None:
        """The validated and normalized benchmark_panel, or None."""
        self._ensure_bundle()
        return self._panel

    @property
    def schema_metadata(self) -> dict[str, Any] | None:
        """Schema metadata from the most recent benchmark_panel validation."""
        self._ensure_bundle()
        return self._schema_metadata

    # ------------------------------------------------------------------
    # schema guard + normalization (delegates to standalone function)
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_and_normalize_panel(raw: pd.DataFrame, release_label: str = "") -> pd.DataFrame:
        """Validate required columns and normalize types.  Legacy entry point.

        Returns a copy of *raw* with:
          - date       → datetime
          - vintage_date → datetime (or NaT-preserving)
          - value      → numeric (coerce failures → NaN)
          - source_id  → lowercase string
          - series_id, source_series_id, quality_flag → string
        """
        panel, _ = _validate_benchmark_panel_schema(raw, release_label=release_label)
        return panel

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _ensure_bundle(self) -> Any:
        """Load (or reload) the bundle from the adapter, respecting cache invalidation.

        Cache invalidation triggers when the adapter exposes current_release_id
        and it differs from the previously loaded release.
        """
        if self.adapter is None:
            raise NotImplementedError(
                "DataHubLite has no adapter — cannot load data. "
                "Inject a HarvesterAdapter-like object or use a live backend."
            )

        current_id: str | None = None
        adapter_has_release_tracking = False
        if hasattr(self.adapter, "current_release_id"):
            try:
                current_id = self.adapter.current_release_id
                adapter_has_release_tracking = True
            except Exception:
                current_id = None

        # Invalidate cache if release changed
        if (
            self._bundle is not None
            and current_id is not None
            and self._loaded_release_id is not None
            and current_id != self._loaded_release_id
        ):
            self._bundle = None
            self._panel = None
            self._schema_metadata = None

        if self._bundle is None:
            if not adapter_has_release_tracking:
                import warnings
                warnings.warn(
                    "adapter_does_not_expose_current_release_id: "
                    "DataHubLite cannot auto-invalidate cache on release change."
                )

            self._bundle = self.adapter.load_bundle()
            raw = getattr(self._bundle, "benchmark_panel", pd.DataFrame())
            release_label = getattr(self._bundle, "bundle_id", "unknown")
            if raw.empty and raw.columns.empty:
                self._panel = raw
                self._schema_metadata = {
                    "panel": "benchmark_panel",
                    "row_count": 0,
                    "columns": [],
                    "date_min": None,
                    "date_max": None,
                    "series_count": 0,
                    "source_ids": [],
                    "release_id": release_label or None,
                }
            else:
                self._panel, self._schema_metadata = _validate_benchmark_panel_schema(
                    raw, release_label=release_label,
                )
            self._loaded_release_id = current_id

        return self._bundle

    @staticmethod
    def _lookup_in_panel(
        panel: pd.DataFrame,
        source_id: str,
        source_series_id: str,
        start: str,
        end: str,
    ) -> _PanelMatch:
        """Return rows from *panel* matching source + series within [start, end].

        Matching strategies (in priority order):

        1. ``exact_source_and_series`` — (source_id, source_series_id) both match.
        2. ``provider_alias`` — source_id is a known alias for the panel source_id
           (e.g. "fred" → "fred_chicago_fed").
        3. ``source_series_id_only`` — source_series_id alone, single source_id.
        4. ``series_id_only`` — series_id column matches, any source.
        5. ``fuzzy_substring`` — source_id is a substring of panel source_id.
        6. ``not_found`` — no match possible.
        """
        sid_lower = source_id.lower()

        # ------------------------------------------------------------------
        # Pass 0 — check if the series exists at all
        # ------------------------------------------------------------------
        candidates = panel[panel["source_series_id"] == source_series_id]
        if candidates.empty:
            # Try series_id column as last resort
            candidates = panel[panel["series_id"] == source_series_id]
            if candidates.empty:
                return _PanelMatch(
                    frame=panel.iloc[0:0].copy(),
                    match_strategy=MATCH_NOT_FOUND,
                    matched_source_id=source_id,
                    matched_source_series_id=source_series_id,
                    match_audit={
                        "requested_source_id": source_id,
                        "requested_source_series_id": source_series_id,
                        "matched": False,
                        "match_strategy": MATCH_NOT_FOUND,
                        "risk_level": _MATCH_RISK_LEVELS[MATCH_NOT_FOUND],
                    },
                )
            # Found via series_id — apply series_id_only strategy
            matched = candidates
            strategy = MATCH_SERIES_ID_ONLY
            warnings: list[str] = []
        else:
            # ------------------------------------------------------------------
            # Pass 1 — exact (source_id, source_series_id)
            # ------------------------------------------------------------------
            exact = candidates[candidates["source_id"].str.lower() == sid_lower]
            warnings: list[str] = []
            if not exact.empty:
                matched = exact
                strategy = MATCH_EXACT_SOURCE_AND_SERIES
            else:
                # ------------------------------------------------------------------
                # Pass 2 — provider alias
                # ------------------------------------------------------------------
                canonical = _PROVIDER_ALIASES.get(sid_lower)
                aliased = (
                    candidates[candidates["source_id"].str.lower() == canonical]
                    if canonical is not None
                    else candidates.iloc[0:0]
                )
                if not aliased.empty:
                    matched = aliased
                    strategy = MATCH_PROVIDER_ALIAS
                    warnings.append("provider_alias_match")
                else:
                    unique_sids = candidates["source_id"].str.lower().unique()
                    if len(unique_sids) == 1:
                        # ------------------------------------------------------------------
                        # Pass 3 — source_series_id only (single source_id → unambiguous)
                        # ------------------------------------------------------------------
                        matched = candidates
                        strategy = MATCH_SOURCE_SERIES_ID_ONLY
                    else:
                        # ------------------------------------------------------------------
                        # Pass 4 — fuzzy substring match
                        # ------------------------------------------------------------------
                        sub = candidates[
                            candidates["source_id"].str.lower().str.contains(sid_lower, na=False)
                        ]
                        if not sub.empty:
                            matched = sub
                            strategy = MATCH_FUZZY_SUBSTRING
                            warnings.append("identity_match_fuzzy")
                        else:
                            matched = candidates
                            strategy = MATCH_SERIES_ID_ONLY

        matched = matched.copy()
        actual_source_id = str(matched["source_id"].iloc[0])
        matched = matched.set_index("date").sort_index()
        sliced = matched.loc[start:end]  # type: ignore[no-any-return]

        return _PanelMatch(
            frame=sliced,
            match_strategy=strategy,
            matched_source_id=actual_source_id,
            matched_source_series_id=source_series_id,
            warnings=warnings,
            match_audit={
                "requested_source_id": source_id,
                "requested_source_series_id": source_series_id,
                "matched": True,
                "matched_source_id": actual_source_id,
                "matched_source_series_id": source_series_id,
                "match_strategy": strategy,
                "risk_level": _MATCH_RISK_LEVELS.get(strategy, "unknown"),
                "warnings": warnings,
            },
        )

    def _coerce_series_request(self, raw: SeriesRequest | Mapping[str, Any]) -> tuple[SeriesRequest, str]:
        """Normalise a raw request, returning (request, enrichment_source).

        *enrichment_source* is one of:
          - ``"structural_semantics"`` — request already had channel/block/role
          - ``"explicit_preset"`` — preset_name was provided
          - ``"preset_index"`` — request_key matched exactly one preset
          - ``"identity_fallback"`` — no preset match; resolved by provider+series identity
        """
        request = SeriesRequest.from_input(raw)

        if request.has_structural_semantics():
            return request, "structural_semantics"

        if request.preset_name:
            preset = self._presets_by_name.get(str(request.preset_name))
            if preset is None:
                raise ValueError(f"unknown structural preset '{request.preset_name}'")
            return _enrich_from_preset(request, preset), "explicit_preset"

        rk = request.request_key()
        candidates = [
            p for p in self.presets
            for r in p.requests
            if r.request_key() == rk
        ]
        seen: set[str] = set()
        unique: list[StructuralPreset] = []
        for p in candidates:
            if p.name not in seen:
                seen.add(p.name)
                unique.append(p)
        if len(unique) == 1:
            return _enrich_from_preset(request, unique[0]), "preset_index"

        if _request_has_identity(request):
            return request, "identity_fallback"

        raise ValueError(
            "series request lacks series identity; provide provider + series_id, "
            "field, key, resource, or dataset."
        )

    def _available_series_ids(self) -> list[str]:
        """Return the list of series identifiers available in the current panel."""
        if self._panel is None:
            return []
        return sorted(self._panel["source_series_id"].unique().tolist())

    # ------------------------------------------------------------------
    # public API (compatible with DataHub surface)
    # ------------------------------------------------------------------

    def fetch_series(
        self,
        series_requests: Sequence[SeriesRequest | Mapping[str, Any]],
        start: str,
        end: str,
    ) -> FetchResult:
        """Read series data from the injected Harvester-release adapter.

        Raises NotImplementedError when no adapter is configured.
        """
        self._ensure_bundle()
        panel = self._panel
        if panel is None or panel.empty:
            return FetchResult(
                kind="series",
                items=[],
                errors=[
                    DataRequestError(
                        "series", "", {},
                        "Harvester bundle has empty benchmark_panel",
                    )
                ],
                metadata={
                    "start": start,
                    "end": end,
                    "release_id": self.release_id,
                    "data_backend": "harvester",
                    "serving_layer": "datahub_lite",
                    "request_count": len(series_requests),
                    "success_count": 0,
                    "error_count": len(series_requests),
                    "match_audit": [],
                    "schema_guard": self._schema_metadata or {},
                    "quality_warnings": ["empty_benchmark_panel"],
                },
            )

        items: list[SeriesResult] = []
        errors: list[DataRequestError] = []
        audit: list[dict[str, Any]] = []
        fuzzy_count = 0
        available = self._available_series_ids()

        for raw in series_requests:
            try:
                request, enrichment_source = self._coerce_series_request(raw)
            except Exception as exc:
                probe = SeriesRequest.from_input(raw)
                errors.append(
                    DataRequestError(
                        "series", probe.provider,
                        {
                            "request_key": probe.request_key(),
                            "requested_provider": probe.provider,
                            "requested_series_id": probe.series_id or probe.request_key(),
                            "release_id": self.release_id,
                            "available_series": available,
                            "error_type": "request_coercion_failed",
                            "hint": str(exc),
                        },
                        str(exc),
                    )
                )
                continue

            source_id = request.provider.lower().replace("-", "_")
            source_series_id = _resolve_source_series_id(request)

            match = self._lookup_in_panel(panel, source_id, source_series_id, start, end)
            request_key = request.request_key()

            if match.empty:
                errors.append(
                    DataRequestError(
                        "series", request.provider,
                        {
                            "request_key": request_key,
                            "requested_provider": request.provider,
                            "requested_series_id": source_series_id,
                            "source_id": source_id,
                            "source_series_id": source_series_id,
                            "release_id": self.release_id,
                            "available_series": available,
                            "error_type": "series_not_found",
                            "hint": f"Series {source_series_id!r} is missing from current Harvester release.",
                        },
                        f"no data in Harvester release for {source_id}:{source_series_id}",
                    )
                )
                audit.append({
                    "request_key": request_key,
                    "requested_provider": request.provider,
                    "requested_series_id": source_series_id,
                    "matched": False,
                    "match_strategy": MATCH_NOT_FOUND,
                    "risk_level": _MATCH_RISK_LEVELS[MATCH_NOT_FOUND],
                    "warnings": [],
                })
                continue

            # Determine the effective match strategy, accounting for preset enrichment.
            if enrichment_source == "explicit_preset":
                effective_strategy = MATCH_EXPLICIT_PRESET
                effective_warnings = list(match.warnings)
            elif enrichment_source == "preset_index":
                effective_strategy = match.match_strategy
                effective_warnings = list(match.warnings)
            else:
                effective_strategy = match.match_strategy
                effective_warnings = list(match.warnings)

            if match.is_fuzzy or enrichment_source == "identity_fallback":
                fuzzy_count += 1
                if "identity_match_fuzzy" not in effective_warnings:
                    effective_warnings.append("identity_match_fuzzy")

            # Build item-level quality flags
            quality_flags: list[str] = []
            if effective_warnings:
                quality_flags.extend(effective_warnings)

            items.append(
                SeriesResult(
                    provider=request.provider,
                    request_key=request_key,
                    frame=match.frame.reset_index(),
                    frequency=request.metadata.get("frequency"),
                    unit=request.metadata.get("unit"),
                    metadata={
                        "requested_provider": request.provider,
                        "requested_series_id": source_series_id,
                        "matched_source_id": match.matched_source_id,
                        "matched_source_series_id": match.matched_source_series_id,
                        "source_id": match.matched_source_id,  # backward compat
                        "source_series_id": match.matched_source_series_id,  # backward compat
                        "series_id": source_series_id,
                        "unit": request.metadata.get("unit"),
                        "frequency": request.metadata.get("frequency"),
                        "quality_flag": quality_flags,
                        "channel": request.channel,
                        "measurement_block": request.measurement_block,
                        "evidence_role": request.evidence_role,
                        "preset_name": request.preset_name,
                        "enrichment_source": enrichment_source,
                        "match_strategy": effective_strategy,
                        "risk_level": _MATCH_RISK_LEVELS.get(effective_strategy, "unknown"),
                        **(
                            {"identity_match_fuzzy": True}
                            if match.is_fuzzy or enrichment_source == "identity_fallback"
                            else {}
                        ),
                    },
                )
            )

            audit.append(match.match_audit | {
                "request_key": request_key,
                "requested_provider": request.provider,
                "requested_series_id": source_series_id,
                "enrichment_source": enrichment_source,
                "preset_name": request.preset_name,
                "match_strategy": effective_strategy,
                "risk_level": _MATCH_RISK_LEVELS.get(effective_strategy, "unknown"),
                "warnings": effective_warnings,
            })

        return FetchResult(
            kind="series",
            items=items,
            errors=errors,
            metadata={
                "start": start,
                "end": end,
                "release_id": self.release_id,
                "data_backend": "harvester",
                "serving_layer": "datahub_lite",
                "request_count": len(series_requests),
                "success_count": len(items),
                "error_count": len(errors),
                "match_audit": audit,
                "schema_guard": self._schema_metadata or {},
                "quality_warnings": [
                    w for entry in audit
                    for w in entry.get("warnings", [])
                ],
                "match_audit_summary": {
                    "total_requests": len(series_requests),
                    "matched": len(items),
                    "errors": len(errors),
                    "fuzzy_matches": fuzzy_count,
                },
            },
        )

    def fetch_structural_presets(
        self,
        preset_names: Sequence[str],
        start: str,
        end: str,
    ) -> FetchResult:
        """Fetch all series for the named structural presets.

        Compatible with the legacy DataHub.fetch_structural_presets() signature.
        Internally, all data comes from the Harvester release.
        """
        all_requests: list[dict[str, Any]] = []
        for name in preset_names:
            preset = self._presets_by_name.get(str(name))
            if preset is None:
                continue
            for req in preset.requests:
                all_requests.append({
                    "provider": req.provider,
                    "series_id": req.series_id,
                    "field": req.field,
                    "dataset": req.dataset,
                    "cik": req.cik,
                    "resource": req.resource,
                    "key": req.key,
                    "preset_name": name,
                    "channel": preset.channel,
                    "measurement_block": preset.measurement_block,
                    "evidence_role": preset.evidence_role,
                    "jurisdiction_or_scope": preset.jurisdiction_or_scope,
                })

        if not all_requests:
            return FetchResult(
                kind="series",
                items=[],
                errors=[],
                metadata={
                    "release_id": self.release_id,
                    "data_backend": "harvester",
                    "serving_layer": "datahub_lite",
                    "request_count": 0,
                    "success_count": 0,
                    "error_count": 0,
                },
            )

        return self.fetch_series(all_requests, start=start, end=end)

    def build_structural_plan(
        self,
        series_ids: Sequence[str],
    ) -> dict[str, Any]:
        """Build a structural fetch plan from a list of series ids.

        Compatible with the legacy DataHub.build_structural_plan() signature.
        """
        plan = build_structural_fetch_plan(series_ids, self.presets)
        return plan.to_dict()

    def available_structural_presets(self) -> list[dict[str, Any]]:
        return [preset.to_dict() for preset in self.presets]

    def provider_capabilities(self) -> list[dict[str, Any]]:
        """Return release-coverage capabilities (not live acquisition capabilities).

        The capability_type field signals that these describe what the current
        release contains, not what providers are reachable via live HTTP.
        """
        caps = self._router.capability_catalog()
        # Stamp each entry with release-serving semantics
        for entry in caps:
            entry["capability_type"] = "release_serving"
            entry["not_acquisition"] = True
            entry["release_id"] = self.release_id
        return caps

    def route_evidence(self, request: Mapping[str, Any]) -> dict[str, Any]:
        return self._router.route(request).to_dict()

    def available_providers(self) -> dict[str, list[str]]:
        """Return providers and their series from the current release.

        Compatible with the legacy DataHub.available_providers() signature.
        """
        if self._panel is None:
            return {}
        providers: dict[str, list[str]] = {}
        for sid in self._panel["source_id"].unique():
            key = str(sid)
            series = sorted(self._panel[self._panel["source_id"] == sid]["source_series_id"].unique().tolist())
            providers[key] = series
        return providers


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _resolve_source_series_id(request: SeriesRequest) -> str:
    """Best-effort extraction of the native series identifier from a request."""
    if request.series_id:
        return request.series_id
    if request.field:
        return request.field
    if request.key:
        return request.key
    if request.resource:
        return request.resource
    if request.dataset:
        return request.dataset
    return request.request_key()


def _enrich_from_preset(request: SeriesRequest, preset: StructuralPreset) -> SeriesRequest:
    """Stamp preset structural semantics onto a bare series request."""
    default_req = preset.requests[0] if preset.requests else None
    return SeriesRequest(
        provider=request.provider or (default_req.provider if default_req else request.provider),
        series_id=request.series_id,
        dataset=request.dataset,
        field=request.field,
        cik=request.cik,
        resource=request.resource,
        key=request.key,
        preset_name=preset.name,
        channel=preset.channel,
        measurement_block=preset.measurement_block,
        evidence_role=preset.evidence_role,
        jurisdiction_or_scope=preset.jurisdiction_or_scope,
        metadata=dict(request.metadata),
    )


def _request_has_identity(request: SeriesRequest) -> bool:
    """True when *request* carries at least one series-level identifier."""
    return bool(
        request.provider
        and (
            request.series_id
            or request.field
            or request.key
            or request.resource
            or request.dataset
        )
    )


__all__ = [
    "BenchmarkPanelSchemaError",
    "DataHubLite",
    "HarvesterAdapterLike",
    "ReleaseBundleLike",
    "MATCH_EXACT_SOURCE_AND_SERIES",
    "MATCH_EXPLICIT_PRESET",
    "MATCH_PROVIDER_ALIAS",
    "MATCH_SERIES_ID_ONLY",
    "MATCH_SOURCE_SERIES_ID_ONLY",
    "MATCH_FUZZY_SUBSTRING",
    "MATCH_NOT_FOUND",
    "_validate_benchmark_panel_schema",
    "_MATCH_RISK_LEVELS",
]
