"""Release metadata and persistence contracts for Harvester outputs."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
import logging
from pathlib import Path
import threading
import time
from typing import Any, cast
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from harvester.canonical import canonical_official_observations, panel_identity_set
from harvester.core.acquisition_timing import (
    replace_local_steps,
    source_record,
    track_local_step,
    utc_now,
)
from harvester.core.exporter import resolve_release_dir, validate_release_id
from harvester.core.manifest import build_manifest
from harvester.core.observation import (
    observation_coverage_from_frame,
    read_observation_coverage,
)
from harvester.provider_catalog import OFFICIAL_SERIES_MAP
from harvester.provenance import make_provenance
from system_runtime.context import RuntimeContext
from system_runtime.secrets import SecretProvider

logger = logging.getLogger(__name__)


def save_processed_panel(panel: pd.DataFrame, data_root: str = "") -> Path:
    """Persist the compatibility processed-panel artifact."""
    root = Path(data_root) if data_root else RuntimeContext.current_context().data_root
    processed_dir = root / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    path = processed_dir / "official_panel.parquet"
    panel.to_parquet(path, index=False)
    return path


def make_manifest(
    *,
    dataset_id: str,
    release_id: str,
    as_of_date: str,
    vintage_date: str,
    data_path: Path,
    provider: str,
    source_url: str,
    source_params: dict[str, Any] | None = None,
    columns: list[dict[str, Any]] | None = None,
    provenance_path: str = "",
    quality_report_path: str | None = None,
    row_count: int = 0,
    observation_start: str | None = None,
    observation_end: str | None = None,
    provider_outcome: dict[str, Any] | None = None,
    notes: str = "",
) -> dict[str, Any]:
    """Build the standard release manifest from an emitted data file."""
    file_bytes = data_path.read_bytes()
    sha = hashlib.sha256(file_bytes).hexdigest()
    size = len(file_bytes)
    columns = columns or default_columns()
    prov_path = provenance_path or f"provenance/{dataset_id}.provenance.json"
    actual_coverage = read_observation_coverage(
        data_path,
        file_format="parquet",
        time_column="date",
    )
    if actual_coverage is not None:
        actual_start = actual_coverage["start"]
        actual_end = actual_coverage["end"]
        if observation_start is not None and observation_start != actual_start:
            raise ValueError(
                f"manifest observation_start mismatch for {dataset_id}: "
                f"declared={observation_start}, actual={actual_start}"
            )
        if observation_end is not None and observation_end != actual_end:
            raise ValueError(
                f"manifest observation_end mismatch for {dataset_id}: "
                f"declared={observation_end}, actual={actual_end}"
            )
        observation_start = actual_start
        observation_end = actual_end
    return cast(
        dict[str, Any],
        build_manifest(
            dataset_id=dataset_id,
            release_id=release_id,
            as_of_date=as_of_date,
            vintage_date=vintage_date,
            source={
                "provider": provider,
                "kind": "public_api",
                "url_or_reference": source_url,
                "retrieved_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            },
            data_file={
                "path": f"data/{data_path.name}",
                "format": "parquet",
                "sha256": sha,
                "byte_size": size,
                "row_count": row_count,
            },
            columns=columns,
            time_coverage={
                "start": observation_start or as_of_date,
                "end": observation_end or as_of_date,
                "frequency": "irregular",
                "time_column": "date",
            },
            provenance_path=prov_path,
            quality_report_path=quality_report_path,
            provider_outcome=provider_outcome,
            notes=notes,
        ),
    )




def default_columns() -> list[dict[str, Any]]:
    return [
        {"name": "date", "dtype": "date", "nullable": False,
         "description": "Observation date.", "semantic_role": "time_index"},
        {"name": "series_id", "dtype": "string", "nullable": False,
         "description": "Full series identifier (e.g. FRED:T10Y2Y).", "semantic_role": "identifier"},
        {"name": "source_id", "dtype": "string", "nullable": False,
         "description": "Source provider (fred, treasury, sec, h41).", "semantic_role": "category"},
        {"name": "source_series_id", "dtype": "string", "nullable": False,
         "description": "Raw series identifier from source.", "semantic_role": "identifier"},
        {"name": "value", "dtype": "float64", "nullable": True,
         "description": "Observed value.", "semantic_role": "measure"},
        {"name": "unit", "dtype": "string", "nullable": True,
         "description": "Unit of measurement.", "semantic_role": "metadata"},
        {"name": "frequency", "dtype": "string", "nullable": True,
         "description": "Sampling frequency.", "semantic_role": "metadata"},
        {"name": "vintage_date", "dtype": "date", "nullable": True,
         "description": "Date the data was observed/retrieved.", "semantic_role": "metadata"},
        {"name": "quality_flag", "dtype": "string", "nullable": False,
         "description": "Quality label such as observed, fallback, error, derived, synthetic_proxy, or missing.", "semantic_role": "metadata"},
    ]


def _release_panel_candidates(exports_root: Path, *, exclude_release_id: str = "") -> list[Path]:
    """Ordered candidate benchmark panels (newest first), optionally skipping one release."""
    seen: set[Path] = set()
    ordered: list[Path] = []
    latest = exports_root / "latest"
    if latest.exists():
        try:
            resolved = latest.resolve()
            if not exclude_release_id or resolved.name != exclude_release_id:
                ordered.append(resolved / "data" / "benchmark_panel.parquet")
        except OSError:
            logger.warning("Unable to resolve latest Harvester release pointer: %s", latest, exc_info=True)
    for path in sorted(exports_root.glob("*/data/benchmark_panel.parquet"), reverse=True):
        if exclude_release_id and path.parent.parent.name == exclude_release_id:
            continue
        if path not in seen:
            ordered.append(path)
            seen.add(path)
    return ordered


def _carry_forward_missing_series(
    panel: pd.DataFrame,
    *,
    exports_root: Path,
    exclude_release_id: str = "",
) -> pd.DataFrame:
    """Fill gaps from a prior release when a preferred provider fails.

    Prevents OpenBB-first routing (or transient provider errors) from dropping
    previously admitted series such as FRED:RRPONTSYD from a new release.
    """
    from harvester.registry import load_registry

    provider_outcome = panel.attrs.get("provider_outcome")
    if isinstance(provider_outcome, dict):
        provider_outcome = dict(provider_outcome)

    registry = load_registry()
    required_specs = registry.required_series() if hasattr(registry, "required_series") else []
    required_for_release = {
        series.source_series_id or series.canonical_id
        for series in required_specs
    }
    expected: set[str] = set()
    for series in registry.active_series():
        if series.is_derived:
            continue
        cid = series.canonical_id
        expected.add(cid)
        expected.add(f"FRED:{cid}")
        expected.add(f"fred:{cid}")
    present = panel_identity_set(panel)
    missing = {item for item in expected if item not in present}
    if not missing:
        return panel
    bare = {m.split(":", 1)[1] if ":" in m else m for m in missing}
    carried = pd.DataFrame()
    for path in _release_panel_candidates(exports_root, exclude_release_id=exclude_release_id):
        if not path.exists():
            continue
        try:
            previous = pd.read_parquet(path)
        except Exception as exc:
            logger.warning(
                "Unable to read prior release panel %s: %s",
                path,
                type(exc).__name__,
            )
            continue
        if previous.empty or "series_id" not in previous.columns:
            continue
        prev_ids = previous["series_id"].astype(str)
        mask = prev_ids.isin(missing) | prev_ids.map(
            lambda value: value.split(":", 1)[1] if ":" in value else value
        ).isin(bare)
        candidate = previous.loc[mask].copy()
        if candidate.empty:
            continue
        carried = candidate
        break
    if carried.empty:
        return panel
    if not panel.empty and "series_id" in panel.columns:
        have = set(panel["series_id"].astype(str))
        carried = carried[~carried["series_id"].astype(str).isin(have)]
    if carried.empty:
        return panel
    logger.warning(
        "carry-forward %d rows / %d series from previous release",
        len(carried),
        carried["series_id"].nunique(),
    )
    if isinstance(provider_outcome, dict):
        carried_ids = set()
        if "source_series_id" in carried.columns:
            carried_ids.update(carried["source_series_id"].dropna().astype(str))
        elif "series_id" in carried.columns:
            carried_ids.update(
                carried["series_id"].dropna().astype(str).map(
                    lambda value: value.split(":", 1)[1] if ":" in value else value
                )
            )
        provider_failed_ids = set(provider_outcome.get("failed_series", []))
        failed_ids = set(provider_failed_ids)
        failed_ids.update(carried_ids)
        provider_outcome["failed_series"] = sorted(failed_ids)
        provider_outcome["failed_count"] = len(failed_ids)
        # A provider failure for a required-for-release series cannot become
        # an authoritative release.  Classify from the provider's failed
        # identifiers first: a carried row can satisfy a required alias (for
        # example CBOE:MOVE/VXTLT) even when the failed request itself was an
        # optional series.  Treating every carried row whose source id happens
        # to be required would therefore turn an optional outage into a
        # whole-run failure.  Optional series remain degraded evidence; the
        # downstream admission policy stays CONDITIONAL and still blocks
        # decision/current publication.
        required_failed = provider_failed_ids & required_for_release
        if required_failed:
            provider_outcome["status"] = "reused_after_provider_failure"
            provider_outcome["fallback_reason"] = (
                "carried_forward_required_series_after_provider_failure"
            )
        else:
            provider_outcome["status"] = "partial_provider_success"
            provider_outcome["fallback_reason"] = (
                "carried_forward_optional_series_after_provider_failure"
            )
        deadline_skipped = {
            str(item) for item in (panel.attrs.get("deadline_skipped_series") or [])
        }
        if deadline_skipped & (carried_ids | provider_failed_ids):
            provider_outcome["carry_forward_reason"] = "deadline"
            provider_outcome["deadline_skipped_series"] = sorted(deadline_skipped)
    if panel.empty:
        result = carried.reset_index(drop=True)
    else:
        result = pd.concat([panel, carried], ignore_index=True)
    if isinstance(provider_outcome, dict):
        result.attrs["provider_outcome"] = provider_outcome
    skipped = panel.attrs.get("deadline_skipped_series")
    if skipped:
        result.attrs["deadline_skipped_series"] = list(skipped)
    return result
def stage_release(
    panel: pd.DataFrame,
    *,
    release_id: str,
    as_of_date: str,
    vintage_date: str,
    exports_root: str = "",
    notes: str = "",
) -> dict[str, Any]:
    validate_release_id(release_id)
    ex_root = (Path(exports_root) if exports_root else RuntimeContext.current_context().data_root / "exports").expanduser().resolve()
    release_dir = resolve_release_dir(ex_root, release_id)

    for sub in ("data", "manifests", "provenance"):
        (release_dir / sub).mkdir(parents=True, exist_ok=True)

    data_path = release_dir / "data" / "official_panel.parquet"
    panel.to_parquet(data_path, index=False)
    panel_coverage = observation_coverage_from_frame(panel, time_column="date")
    provider_outcome = panel.attrs.get("provider_outcome")
    if not isinstance(provider_outcome, dict):
        provider_outcome = None
    panel_sha = hashlib.sha256(data_path.read_bytes()).hexdigest()
    canonical_observations = canonical_official_observations(
        panel,
        release_id=release_id,
        vintage_date=vintage_date,
        source_snapshot_sha256=panel_sha,
        provider_outcome=provider_outcome,
    )
    from harvester.core.canonical_chain import build_recorded_observation_chains
    from harvester.core.canonical_lineage import write_canonical_lineage

    official_lineage = write_canonical_lineage(
        release_dir=release_dir,
        dataset_id="official_panel",
        release_id=release_id,
        observations=canonical_observations,
        chain_builder=lambda delta: build_recorded_observation_chains(
            delta,
            release_id=release_id,
            producer="harvester.official",
            measurement_definition="Official panel value recorded for the release",
            policy_version="harvester.official.v1",
            predicate="official_value_recorded_on",
            label_factory=lambda observation: str(
                observation.get("canonical_series_id") or "official series"
            ),
        ),
        exports_root=ex_root,
        measurement_definition="Official panel value recorded for the release",
        predicate="official_value_recorded_on",
    )
    canonical_observation_relpath = official_lineage.observation_relpath
    canonical_chain_relpath = official_lineage.chain_relpath

    columns = default_columns()
    manifest = make_manifest(
        dataset_id="official_panel",
        release_id=release_id,
        as_of_date=as_of_date,
        vintage_date=vintage_date,
        data_path=data_path,
        provider="harvester.official",
        source_url=OFFICIAL_SERIES_MAP.get("fred", {}).get("_url", "https://api.stlouisfed.org/fred"),
        columns=columns,
        provenance_path="provenance/official_panel.provenance.json",
        row_count=len(panel),
        provider_outcome=provider_outcome,
        notes=notes or (
            "Official public data panel aggregated from FRED, Treasury FiscalData, "
            "SEC EDGAR, and H.4.1 direct DDP CSV. "
            "SEC filing_pulse is a coarse filing_count proxy, NOT a credit-stress or risk-exposure metric. "
            "BTFP values of zero post-expiry are observed_zero (data quality OK, not an error)."
        ),
    )

    import json as _json
    manifest_path = release_dir / "manifests" / "official_panel.manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(_json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    provenance = make_provenance(
        dataset_id="official_panel",
        release_id=release_id,
        method="api_client",
        source_identifier="harvester.providers (fred, treasury, sec, h41)",
        final_sha256=manifest["data_file"]["sha256"],
        raw_sha256="",
        provider_outcome=provider_outcome,
        observation_start=(panel_coverage or {}).get("start"),
        observation_end=(panel_coverage or {}).get("end"),
        availability=(provider_outcome or {}).get("availability"),
        canonical_observation_path=canonical_observation_relpath,
        canonical_observation_count=official_lineage.provenance_fields["canonical_observation_count"],
        canonical_chain_path=canonical_chain_relpath,
        canonical_chain_count=official_lineage.provenance_fields["canonical_chain_count"],
        canonical_schema_version=official_lineage.provenance_fields["canonical_schema_version"],
        canonical_lineage_path=official_lineage.provenance_fields["canonical_lineage_path"],
        previous_release_id=official_lineage.provenance_fields.get("previous_release_id"),
        canonical_observation_delta_count=official_lineage.provenance_fields["canonical_observation_delta_count"],
        canonical_chain_delta_count=official_lineage.provenance_fields["canonical_chain_delta_count"],
        canonical_observation_merkle_root=official_lineage.provenance_fields["canonical_observation_merkle_root"],
        canonical_chain_merkle_root=official_lineage.provenance_fields["canonical_chain_merkle_root"],
        notes=notes or "Aggregated official data from multiple public sources.",
    )

    prov_path = release_dir / "provenance" / "official_panel.provenance.json"
    prov_path.parent.mkdir(parents=True, exist_ok=True)
    prov_path.write_text(_json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return {
        "release_id": release_id,
        "release_dir": str(release_dir),
        "data_path": str(data_path),
        "manifest_path": str(manifest_path),
        "provenance_path": str(prov_path),
        "row_count": len(panel),
        "canonical_observation_count": official_lineage.provenance_fields["canonical_observation_count"],
        "canonical_chain_count": official_lineage.provenance_fields["canonical_chain_count"],
    }


__all__ = [
    "_carry_forward_missing_series",
    "_release_panel_candidates",
    "default_columns",
    "make_manifest",
    "make_provenance",
    "save_processed_panel",
    "stage_release",
]
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
    acquisition_fn: Callable[..., pd.DataFrame] | None = None,
) -> dict[str, Any]:
    """Stage a complete Harvester release with registry-driven acquisition.

    This is the Phase C entry point that:
    1. Fetches all active series from the registry
    2. Builds derived series (TEDRATE replacements, MOVE_PROXY if needed)
    3. Optionally includes external indicators (OFR_FSI, etc.)
    4. Writes complete manifest and provenance for each panel
    5. Writes corpus_index status

    Returns a dict with release metadata suitable for finalization.
    """
    from harvester.derived import (
        build_derived_panel,
    )
    from harvester.quality import build_quality_report, write_quality_report
    from harvester.registry import load_registry

    from harvester.acquisition import fetch_official_series_from_registry as default_acquisition
    from harvester.canonical import (
        canonical_official_observations as build_canonical_observations,
        panel_identity_set as panel_identities,
    )
    from harvester.normalization import (
        build_complete_benchmark_panel as build_panel,
        build_proxy_candidate_panel as build_proxy_panel,
    )
    from harvester.provider_routing import (
        _external_indicator_timeout_seconds as external_timeout,
        _failed_attempt_failure_classes as failed_classes,
        _is_external_managed_series as is_external,
        _merge_external_provider_outcome as merge_outcome,
    )
    acquire = acquisition_fn or default_acquisition
    carry_forward = _carry_forward_missing_series

    registry = load_registry()
    if not vintage_date:
        vintage_date = datetime.now(UTC).strftime("%Y-%m-%d")
    if not as_of_date:
        as_of_date = vintage_date
    validate_release_id(release_id)
    ex_root = (Path(exports_root) if exports_root else RuntimeContext.current_context().data_root / "exports").expanduser().resolve()
    release_dir = resolve_release_dir(ex_root, release_id)

    for sub in ("data", "manifests", "provenance", "quality_reports"):
        (release_dir / sub).mkdir(parents=True, exist_ok=True)

    local_steps: list[dict[str, Any]] = []
    stage_started_at = utc_now()
    from harvester.core.concurrent_policy import (
        EXTERNAL_MAX_WORKERS,
        budget_seconds,
        concurrent_enabled,
    )

    deadline_monotonic = None
    if concurrent_enabled():
        deadline_monotonic = time.monotonic() + budget_seconds()

    # ------------------------------------------------------------------
    # 1. Fetch acquired series
    # ------------------------------------------------------------------
    resolved_api_keys = dict(api_keys or {})
    if secret_provider is not None:
        # Resolve logical secrets once at the provider boundary. Downstream
        # providers receive canonical values, never host-specific aliases.
        fred_key = secret_provider.get("FRED_API_KEY", "") or ""
        resolved_api_keys.setdefault("fred", fred_key)
        resolved_api_keys.setdefault("h41", fred_key)
        resolved_api_keys.setdefault("openbb_fred", fred_key)
        resolved_api_keys.setdefault(
            "tiingo", secret_provider.get("TIINGO_API_KEY", "") or ""
        )
        resolved_api_keys.setdefault(
            "massive", secret_provider.get("MASSIVE_API_KEY", "") or ""
        )

    panel = acquire(
        as_of_date=as_of_date,
        data_root=str(RuntimeContext.current_context().data_root),
        providers=providers,
        cache=cache,
        api_keys=resolved_api_keys,
        deadline_monotonic=deadline_monotonic,
    )
    acquisition_sources = list(panel.attrs.get("acquisition_sources") or [])
    panel = carry_forward(
        panel,
        exports_root=ex_root,
        exclude_release_id=release_id,
    )
    provider_outcome = panel.attrs.get("provider_outcome")
    if not isinstance(provider_outcome, dict):
        provider_outcome = None

    external_managed_series = {
        str(s.source_series_id or s.canonical_id)
        for s in registry.active_series()
        if not s.is_derived and is_external(s)
    }
    from harvester.providers.external_indicators import KNOWN_INDICATORS

    manual_external_series = {
        indicator.series_id
        for indicator in KNOWN_INDICATORS
        if indicator.acquisition_mode == "manual"
    }
    automated_external_series = external_managed_series - manual_external_series
    external_succeeded_series: dict[str, str] = {}
    external_failed_series: dict[str, str] = {
        series_id: "not_loaded"
        for series_id in automated_external_series
    }
    manual_series_status: dict[str, str] = {
        series_id: "manual_refresh_required"
        for series_id in sorted(external_managed_series & manual_external_series)
    }

    # ------------------------------------------------------------------
    # 2. Build derived series
    # ------------------------------------------------------------------
    derived_series = registry.derived_series()
    with track_local_step(local_steps, "derived_panel"):
        derived_panel = build_derived_panel(
            list(derived_series),
            panel,
            as_of_date=as_of_date,
            vintage_date=vintage_date,
        )

    # ------------------------------------------------------------------
    # 3. External indicators (OFR_FSI)
    # ------------------------------------------------------------------
    ext_panel = pd.DataFrame()
    if include_external:
        try:
            from harvester.providers.external_indicators import (
                ManualDownloadRequired,
                external_series_to_long_panel,
                fetch_external_indicator,
                read_cached_external_indicator,
            )
            ext_results: dict[str, pd.Series] = {}
            ext_lock = threading.Lock()
            cache_dir = RuntimeContext.current_context().data_root / "harvester" / "raw" / "external_indicators"
            cache_dir.mkdir(parents=True, exist_ok=True)

            def _consume_indicator(indicator: Any) -> None:
                indicator_started_at = utc_now()
                indicator_t0 = time.perf_counter()
                indicator_outcome = "failed"
                indicator_provider = ""
                try:
                    if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
                        with ext_lock:
                            if indicator.series_id in automated_external_series:
                                external_failed_series[indicator.series_id] = "deadline"
                            skipped = list(panel.attrs.get("deadline_skipped_series") or [])
                            skipped.append(indicator.series_id)
                            panel.attrs["deadline_skipped_series"] = skipped
                        return
                    if indicator.acquisition_mode == "manual":
                        result = read_cached_external_indicator(indicator, cache_dir=cache_dir)
                        if result is not None and not result.empty:
                            with ext_lock:
                                ext_results[indicator.series_id] = result
                                if indicator.series_id in manual_series_status:
                                    manual_series_status[indicator.series_id] = "cached"
                            indicator_outcome = "success"
                            indicator_provider = str(indicator.authority_id)
                        else:
                            indicator_outcome = "manual"
                        return
                    try:
                        result = fetch_external_indicator(
                            indicator,
                            cache_dir=cache_dir,
                            refresh=not cache,
                            timeout_sec=external_timeout(),
                        )
                    except ManualDownloadRequired as exc:
                        logger.warning("external indicator unavailable: %s", exc)
                        if indicator.series_id in automated_external_series:
                            with ext_lock:
                                external_failed_series[indicator.series_id] = type(exc).__name__
                        return
                    if result is not None and not result.empty:
                        with ext_lock:
                            ext_results[indicator.series_id] = result
                            if indicator.series_id in automated_external_series:
                                external_succeeded_series[indicator.series_id] = indicator.authority_id
                                external_failed_series.pop(indicator.series_id, None)
                        indicator_outcome = "success"
                        indicator_provider = str(indicator.authority_id)
                finally:
                    with ext_lock:
                        acquisition_sources.append(
                            source_record(
                                source_id=indicator.series_id,
                                series_id=indicator.series_id,
                                provider=indicator_provider,
                                started_at=indicator_started_at,
                                t0=indicator_t0,
                                attempts=1,
                                outcome=indicator_outcome,
                            )
                        )

            if concurrent_enabled():
                with ThreadPoolExecutor(max_workers=EXTERNAL_MAX_WORKERS) as pool:
                    list(pool.map(_consume_indicator, KNOWN_INDICATORS))
            else:
                for indicator in KNOWN_INDICATORS:
                    _consume_indicator(indicator)
            if ext_results:
                ext_panel = external_series_to_long_panel(ext_results, vintage_date=vintage_date)
        except Exception:
            logger.warning("external indicator fetch failed", exc_info=True)

    if include_external:
        provider_outcome = merge_outcome(
            provider_outcome,
            requested_series=automated_external_series,
            succeeded_series=external_succeeded_series,
            failed_series=external_failed_series,
            manual_series=manual_series_status,
        )
    skipped = [str(item) for item in (panel.attrs.get("deadline_skipped_series") or [])]
    if skipped and isinstance(provider_outcome, dict):
        provider_outcome["carry_forward_reason"] = "deadline"
        provider_outcome["deadline_skipped_series"] = sorted(set(skipped))

    # ------------------------------------------------------------------
    # 4. Combine into benchmark_panel and proxy_candidate_panel
    # ------------------------------------------------------------------
    benchmark = build_panel(
        panel,
        external_indicators=ext_panel if not ext_panel.empty else None,
        derived_panel=derived_panel,
    )
    proxy_candidates = build_proxy_panel(derived_panel)

    # ------------------------------------------------------------------
    # 5. Write benchmark_panel
    # ------------------------------------------------------------------
    bench_path = release_dir / "data" / "benchmark_panel.parquet"
    benchmark.to_parquet(bench_path, index=False)
    bench_sha = hashlib.sha256(bench_path.read_bytes()).hexdigest()
    bench_size = bench_path.stat().st_size
    from harvester.core.canonical_chain import build_recorded_observation_chains
    from harvester.core.canonical_lineage import write_canonical_lineage

    with track_local_step(local_steps, "jsonl_observations"):
        benchmark_observations = build_canonical_observations(
            benchmark,
            release_id=release_id,
            vintage_date=vintage_date,
            source_snapshot_sha256=bench_sha,
            provider_outcome=provider_outcome,
            canonical_prefix="BENCHMARK",
            producer="harvester.complete",
        )

    with track_local_step(local_steps, "jsonl_chains"):
        benchmark_lineage = write_canonical_lineage(
            release_dir=release_dir,
            dataset_id="benchmark_panel",
            release_id=release_id,
            observations=benchmark_observations,
            chain_builder=lambda delta: build_recorded_observation_chains(
                delta,
                release_id=release_id,
                producer="harvester.complete",
                measurement_definition="Benchmark panel value recorded for the release",
                policy_version="harvester.benchmark_panel.v1",
                predicate="benchmark_value_recorded_on",
                label_factory=lambda observation: str(
                    observation.get("canonical_series_id") or "benchmark series"
                ),
            ),
            exports_root=ex_root,
            measurement_definition="Benchmark panel value recorded for the release",
            predicate="benchmark_value_recorded_on",
        )
    benchmark_observation_relpath = benchmark_lineage.observation_relpath
    benchmark_chain_relpath = benchmark_lineage.chain_relpath

    panel_dates = pd.to_datetime(benchmark["date"])
    benchmark_coverage = observation_coverage_from_frame(benchmark, time_column="date")
    bench_manifest = make_manifest(
        dataset_id="benchmark_panel",
        release_id=release_id,
        as_of_date=as_of_date,
        vintage_date=vintage_date,
        data_path=bench_path,
        provider="harvester.complete",
        source_url="registry:configs/series_registry.yaml",
        columns=default_columns(),
        provenance_path="provenance/benchmark_panel.provenance.json",
        quality_report_path="quality_reports/benchmark_panel.quality.json",
        row_count=len(benchmark),
        provider_outcome=provider_outcome,
        notes=notes or "Complete benchmark panel: acquired + derived + external indicators.",
    )
    bench_manifest["data_file"]["sha256"] = bench_sha
    bench_manifest["data_file"]["byte_size"] = bench_size
    if not panel_dates.empty and panel_dates.notna().any():
        bench_manifest["time_coverage"]["start"] = panel_dates.min().strftime("%Y-%m-%d")
        bench_manifest["time_coverage"]["end"] = panel_dates.max().strftime("%Y-%m-%d")

    manifest_path = release_dir / "manifests" / "benchmark_panel.manifest.json"
    manifest_path.write_text(json.dumps(bench_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    bench_prov = make_provenance(
        dataset_id="benchmark_panel",
        release_id=release_id,
        method="api_client",
        source_identifier="harvester.registry + derived + external_indicators",
        final_sha256=bench_sha,
        provider_outcome=provider_outcome,
        observation_start=(benchmark_coverage or {}).get("start"),
        observation_end=(benchmark_coverage or {}).get("end"),
        canonical_observation_path=benchmark_observation_relpath,
        canonical_observation_count=benchmark_lineage.provenance_fields["canonical_observation_count"],
        canonical_chain_path=benchmark_chain_relpath,
        canonical_chain_count=benchmark_lineage.provenance_fields["canonical_chain_count"],
        canonical_schema_version=benchmark_lineage.provenance_fields["canonical_schema_version"],
        canonical_lineage_path=benchmark_lineage.provenance_fields["canonical_lineage_path"],
        previous_release_id=benchmark_lineage.provenance_fields.get("previous_release_id"),
        canonical_observation_delta_count=benchmark_lineage.provenance_fields["canonical_observation_delta_count"],
        canonical_chain_delta_count=benchmark_lineage.provenance_fields["canonical_chain_delta_count"],
        canonical_observation_merkle_root=benchmark_lineage.provenance_fields["canonical_observation_merkle_root"],
        canonical_chain_merkle_root=benchmark_lineage.provenance_fields["canonical_chain_merkle_root"],
        notes=notes or "Aggregated from registry-defined providers + derived computations.",
        acquisition_sources=acquisition_sources,
        local_steps=local_steps,
        started_at=stage_started_at,
        completed_at=utc_now(),
    )
    (release_dir / "provenance" / "benchmark_panel.provenance.json").write_text(
        json.dumps(bench_prov, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_quality_report(
        build_quality_report(
            "benchmark_panel",
            benchmark,
            as_of_date=as_of_date,
            required_columns=["date", "series_id", "source_id", "source_series_id", "value"],
            provider_outcome=provider_outcome,
        ),
        release_dir,
        "benchmark_panel",
    )

    # ------------------------------------------------------------------
    # 6. Write proxy_candidate_panel (or document emptiness)
    # ------------------------------------------------------------------
    proxy_path = release_dir / "data" / "proxy_candidate_panel.parquet"
    if not proxy_candidates.empty:
        proxy_candidates.to_parquet(proxy_path, index=False)
    else:
        # Write an empty parquet with the right schema
        pd.DataFrame(columns=[
            "date", "series_id", "source_id", "source_series_id",
            "value", "unit", "frequency", "vintage_date", "quality_flag",
        ]).to_parquet(proxy_path, index=False)

    proxy_sha = hashlib.sha256(proxy_path.read_bytes()).hexdigest()
    proxy_size = proxy_path.stat().st_size
    proxy_row_count = len(proxy_candidates)
    proxy_coverage = observation_coverage_from_frame(proxy_candidates, time_column="date")

    # Keep proxy candidates explicit and non-authoritative.  The measurement
    # specification records the source ladder, missingness semantics, and
    # promotion ceiling without emitting a canonical Observation->Claim chain.
    from harvester.core.proxy_measurement import (
        SCHEMA_VERSION as PROXY_MEASUREMENT_SPEC_VERSION,
    )
    from harvester.core.proxy_measurement import (
        build_proxy_measurement_spec,
    )

    proxy_measurement_spec = build_proxy_measurement_spec(
        release_id=release_id,
        derived_series=derived_series,
        registry=registry,
        candidate_panel=proxy_candidates,
    )
    proxy_measurement_spec_relpath = "provenance/proxy_candidate_panel.measurement_spec.json"
    (release_dir / proxy_measurement_spec_relpath).write_text(
        json.dumps(proxy_measurement_spec, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    proxy_manifest = make_manifest(
        dataset_id="proxy_candidate_panel",
        release_id=release_id,
        as_of_date=as_of_date,
        vintage_date=vintage_date,
        data_path=proxy_path,
        provider="harvester.derived",
        source_url="registry:configs/series_registry.yaml",
        columns=default_columns(),
        provenance_path="provenance/proxy_candidate_panel.provenance.json",
        quality_report_path="quality_reports/proxy_candidate_panel.quality.json",
        row_count=proxy_row_count,
        notes="Derived TEDRATE replacement proxies and synthetic series. "
              "Not canonical input — available for Deformation routing.",
    )
    proxy_manifest["data_file"]["sha256"] = proxy_sha
    proxy_manifest["data_file"]["byte_size"] = proxy_size

    (release_dir / "manifests" / "proxy_candidate_panel.manifest.json").write_text(
        json.dumps(proxy_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    proxy_prov = make_provenance(
        dataset_id="proxy_candidate_panel",
        release_id=release_id,
        method="computed",
        source_identifier="harvester.derived",
        final_sha256=proxy_sha,
        observation_start=(proxy_coverage or {}).get("start"),
        observation_end=(proxy_coverage or {}).get("end"),
        measurement_spec_path=proxy_measurement_spec_relpath,
        measurement_spec_version=PROXY_MEASUREMENT_SPEC_VERSION,
        notes="Derived proxy series for Deformation routing.",
    )
    (release_dir / "provenance" / "proxy_candidate_panel.provenance.json").write_text(
        json.dumps(proxy_prov, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_quality_report(
        build_quality_report(
            "proxy_candidate_panel",
            proxy_candidates,
            as_of_date=as_of_date,
            required_columns=["date", "series_id", "source_id", "source_series_id", "value"],
            allow_empty=True,
        ),
        release_dir,
        "proxy_candidate_panel",
    )

    # ------------------------------------------------------------------
    # 6b. Cross-asset ETF panel (Harvester evidence bundle)
    # ------------------------------------------------------------------
    from harvester.cross_asset_panel import (
        prefetched_panel_from_registry,
        stage_cross_asset_panel,
    )

    with track_local_step(local_steps, "cross_asset_panel"):
        cross_asset_info = stage_cross_asset_panel(
            release_dir,
            release_id=release_id,
            as_of_date=as_of_date,
            vintage_date=vintage_date,
            # CLI is normally launched from packages/harvester; derive the shared
            # System workspace from the canonical data root so history is merged
            # from /System/Data rather than an accidental package-local /Data.
            workspace=RuntimeContext.current_context().workspace,
            # HYG/LQD/TLT may already have been acquired by the registry phase.
            # Reuse those rows and request only the remaining cross-asset symbols.
            prefetched_panel=prefetched_panel_from_registry(
                panel,
                workspace=RuntimeContext.current_context().workspace,
            ),
            data_contract_mode=data_contract_mode,
            api_keys=resolved_api_keys,
        )

    # ------------------------------------------------------------------
    # 7. Write corpus_index status
    # ------------------------------------------------------------------
    corpus_status = {
        "panel": "corpus_index",
        "status": "disabled",
        "reason": "narrative corpus not part of current Phase C release",
        "release_id": release_id,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    corpus_path = release_dir / "data" / "corpus_index.parquet"
    corpus_columns = [
        {"name": "doc_id", "dtype": "string", "nullable": False,
         "description": "Stable document identifier.", "semantic_role": "primary_key"},
        {"name": "date", "dtype": "date", "nullable": True,
         "description": "Document publication date when known.", "semantic_role": "time_index"},
        {"name": "source", "dtype": "string", "nullable": True,
         "description": "Document source.", "semantic_role": "category"},
        {"name": "text_snippet", "dtype": "string", "nullable": True,
         "description": "Short preview text for audit indexing.", "semantic_role": "metadata"},
    ]
    pd.DataFrame(columns=[c["name"] for c in corpus_columns]).to_parquet(corpus_path, index=False)
    corpus_sha = hashlib.sha256(corpus_path.read_bytes()).hexdigest()
    corpus_size = corpus_path.stat().st_size
    corpus_manifest = build_manifest(
        dataset_id="corpus_index",
        release_id=release_id,
        as_of_date=as_of_date,
        vintage_date=vintage_date,
        source={
            "provider": "harvester.corpus",
            "kind": "internal_corpus",
            "url_or_reference": "data/corpus",
            "retrieved_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "access_notes": corpus_status["reason"],
        },
        data_file={
            "path": "data/corpus_index.parquet",
            "format": "parquet",
            "sha256": corpus_sha,
            "byte_size": corpus_size,
            "row_count": 0,
        },
        columns=corpus_columns,
        time_coverage={
            "start": as_of_date,
            "end": as_of_date,
            "frequency": "irregular",
            "time_column": "date",
        },
        provenance_path="provenance/corpus_index.provenance.json",
        quality_report_path="quality_reports/corpus_index.quality.json",
        notes=f"{corpus_status['status']}: {corpus_status['reason']}",
    )
    (release_dir / "manifests" / "corpus_index.manifest.json").write_text(
        json.dumps(corpus_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    corpus_prov = make_provenance(
        dataset_id="corpus_index",
        release_id=release_id,
        method="computed",
        source_identifier="harvester.corpus disabled status",
        final_sha256=corpus_sha,
        notes=f"{corpus_status['status']}: {corpus_status['reason']}",
    )
    (release_dir / "provenance" / "corpus_index.provenance.json").write_text(
        json.dumps(corpus_prov, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_quality_report(
        build_quality_report(
            "corpus_index",
            pd.DataFrame(columns=[c["name"] for c in corpus_columns]),
            as_of_date=as_of_date,
            required_columns=["doc_id", "date", "source", "text_snippet"],
            allow_empty=True,
        ),
        release_dir,
        "corpus_index",
    )

    # ------------------------------------------------------------------
    # 8. Run promotion gate on staged release
    # ------------------------------------------------------------------
    from harvester.promotion import run_promotion_gate, write_gate_report

    panel_ids = panel_identities(benchmark)
    with track_local_step(local_steps, "promotion_gate"):
        gate_result = run_promotion_gate(
        release_dir,
        registry,
        panel_series_ids=panel_ids,
        sha256_verified=True,
        empty_panels=["corpus_index"] if proxy_row_count == 0 else [],
        cross_asset_row_count=int(cross_asset_info.get("row_count", 0)),
        cross_asset_symbol_count=int(cross_asset_info.get("symbol_count", 0)),
        cross_asset_provider_status=(
            cross_asset_info.get("provider_outcome", {}).get("status")
            if isinstance(cross_asset_info.get("provider_outcome"), dict)
            else None
        ),
        benchmark_provider_status=(
            provider_outcome.get("status")
            if isinstance(provider_outcome, dict)
            else None
        ),
        provider_failure_classes={
            scope: categories
            for scope, categories in {
                "cross_asset": failed_classes(cross_asset_info.get("provider_outcome")),
                "benchmark": failed_classes(provider_outcome),
            }.items()
            if categories
        },
    )
    write_gate_report(gate_result, release_id, release_dir)
    replace_local_steps(
        release_dir / "provenance" / "benchmark_panel.provenance.json",
        local_steps,
    )

    return {
        "release_id": release_id,
        "release_dir": str(release_dir),
        "benchmark_path": str(bench_path),
        "proxy_path": str(proxy_path),
        "proxy_measurement_spec_path": str(release_dir / proxy_measurement_spec_relpath),
        "cross_asset_path": cross_asset_info.get("data_path"),
        "benchmark_rows": len(benchmark),
        "proxy_rows": proxy_row_count,
        "cross_asset_rows": cross_asset_info.get("row_count", 0),
        "cross_asset_provider_outcome": cross_asset_info.get("provider_outcome", {}),
        "derived_series": [s.canonical_id for s in derived_series],
        "gate_state": gate_result.state,
        "gate_passed": gate_result.passed,
        "gate_blockers": gate_result.blockers,
        "gate_warnings": gate_result.warnings,
    }

__all__ = [
    "_carry_forward_missing_series",
    "_release_panel_candidates",
    "default_columns",
    "make_manifest",
    "make_provenance",
    "save_processed_panel",
    "stage_complete_release",
    "stage_release",
]
