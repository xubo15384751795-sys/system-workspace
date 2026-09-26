"""Compatibility facade for the Harvester package public API.

Production acquisition, routing, canonicalization, and release composition
live in their owning modules.  This module keeps the legacy import surface
stable while injecting its compatibility seams into those owners.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from harvester.acquisition import (
    fetch_official_series as _fetch_official_series,
    fetch_official_series_from_registry as _fetch_registry_series,
)
from harvester.canonical import (
    canonical_official_observations as _canonical_official_observations,  # noqa: F401 - compatibility re-export
    panel_identity_set,  # noqa: F401 - compatibility re-export
)
from harvester.provider_catalog import (
    DEFAULT_OFFICIAL_PROVIDERS,
    OFFICIAL_PROVIDER_OUTCOME_STATUSES,  # noqa: F401 - compatibility re-export
    OFFICIAL_SERIES_MAP,
)
from harvester.provider_routing import (
    _failed_attempt_failure_classes,  # noqa: F401 - compatibility re-export
    _external_indicator_timeout_seconds,  # noqa: F401 - compatibility re-export
    _is_external_managed_series,
    _merge_external_provider_outcome,  # noqa: F401 - compatibility re-export
    _provider_outcome,
    order_provider_priority,
    prefer_openbb,  # noqa: F401 - compatibility re-export
)
from harvester.normalization import (
    build_complete_benchmark_panel,  # noqa: F401 - compatibility re-export
    build_proxy_candidate_panel,  # noqa: F401 - compatibility re-export
    normalize_release_panel,  # noqa: F401 - compatibility re-export
)
from harvester.release import (
    _carry_forward_missing_series,  # noqa: F401 - compatibility re-export
    default_columns,
    make_manifest,  # noqa: F401 - compatibility re-export
    make_provenance,  # noqa: F401 - compatibility re-export
    save_processed_panel,  # noqa: F401 - compatibility re-export
    stage_release,  # noqa: F401 - compatibility re-export
    stage_complete_release as _stage_complete_release,
)
from harvester.providers import build_provider
from system_runtime.context import RuntimeContext
from system_runtime.secrets import SecretProvider


def data_root() -> Path:
    """Return the canonical workspace data root.

    The Harvester package is independently buildable, but a System checkout
    must never infer its data authority from the package's source location.
    The old ``parents[2] / data`` fallback pointed at
    ``packages/harvester/data`` and could make a real refresh acquire into a
    package-local shadow tree while publishing a release under canonical
    ``Data/harvester/exports``.
    """
    return RuntimeContext.current_context().data_root


def harvester_raw_root() -> Path:
    """Return the governed Harvester raw-data root.

    ``WorkspacePaths.data`` is the workspace-wide ``Data`` directory, while
    the Harvester raw/cache contract (and freshness registry) lives under
    ``Data/harvester/raw``.  Keeping this explicit prevents external
    indicators from being acquired into an unmonitored ``Data/raw`` shadow
    tree during the workspace migration.
    """
    return RuntimeContext.current_context().data_root / "harvester" / "raw"


def workspace_root() -> Path:
    """Return the explicitly resolved System workspace root."""
    return RuntimeContext.current_context().workspace


def _default_columns() -> list[dict[str, Any]]:
    """Compatibility alias for the canonical release column contract."""
    return default_columns()


def fetch_official_series(
    *,
    as_of_date: str = "",
    data_root: str = "",
    providers: list[str] | None = None,
    cache: bool = True,
    api_keys: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Compatibility facade for the canonical acquisition entrypoint."""
    return _fetch_official_series(
        as_of_date=as_of_date,
        data_root=data_root,
        providers=providers,
        cache=cache,
        api_keys=api_keys,
        provider_factory=build_provider,
        series_catalog=OFFICIAL_SERIES_MAP,
        default_providers=DEFAULT_OFFICIAL_PROVIDERS,
    )

# ======================================================================
# Registry-based acquisition (Phase C)
# ======================================================================


def fetch_official_series_from_registry(
    *,
    as_of_date: str = "",
    data_root: str = "",
    providers: list[str] | None = None,
    cache: bool = True,
    api_keys: dict[str, str] | None = None,
    deadline_monotonic: float | None = None,
) -> pd.DataFrame:
    """Compatibility facade for registry-driven acquisition."""
    return _fetch_registry_series(
        as_of_date=as_of_date,
        data_root=data_root,
        providers=providers,
        cache=cache,
        api_keys=api_keys,
        deadline_monotonic=deadline_monotonic,
        provider_factory=build_provider,
        outcome_factory=_provider_outcome,
        route_orderer=order_provider_priority,
        external_classifier=_is_external_managed_series,
        default_providers=DEFAULT_OFFICIAL_PROVIDERS,
    )






def stage_complete_release(
    *,
    release_id: str,
    as_of_date: str,
    vintage_date: str,
    exports_root: str = "",
    providers: list[str] | None = None,
    cache: bool = True,
    api_keys: dict[str, str] | None = None,
    include_external: bool = True,
    notes: str = "",
    data_contract_mode: str | None = None,
    secret_provider: SecretProvider | None = None,
) -> dict[str, Any]:
    """Compatibility facade for complete release composition."""
    return _stage_complete_release(
        release_id=release_id,
        as_of_date=as_of_date,
        vintage_date=vintage_date,
        exports_root=exports_root,
        providers=providers,
        cache=cache,
        api_keys=api_keys,
        include_external=include_external,
        notes=notes,
        data_contract_mode=data_contract_mode,
        secret_provider=secret_provider,
        acquisition_fn=fetch_official_series_from_registry,
    )
