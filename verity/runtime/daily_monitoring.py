"""Daily-run freshness and warning monitoring semantics.

The application coordinator invokes these checks before publication.  The
checks themselves live in runtime monitoring so daily-run orchestration does
not own freshness or Harvester observation semantics.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Callable

from verity.runtime import runtime_io

logger = logging.getLogger(__name__)
SurfaceDir = Callable[[str], Path]


def check_freshness(
    *,
    root: Path | None = None,
    surface_dir_fn: SurfaceDir | None = None,
) -> dict:
    """Check if the published neutral pressure snapshot is stale."""
    resolved_root = root or runtime_io.ROOT
    surface_dir_fn = surface_dir_fn or (lambda name: resolved_root / "Output" / name)
    fw_path = surface_dir_fn("current") / "neutral_pressure_snapshot.json"
    if not fw_path.exists():
        return {"status": "missing", "stale_hours": None}
    mtime = datetime.fromtimestamp(fw_path.stat().st_mtime, tz=UTC)
    age_hours = (datetime.now(UTC) - mtime).total_seconds() / 3600
    stale = age_hours > 24
    return {"status": "stale" if stale else "fresh", "stale_hours": round(age_hours, 1)}


def check_warnings(
    *,
    root: Path | None = None,
    surface_dir_fn: SurfaceDir | None = None,
    freshness_fn: Callable[[], dict] | None = None,
) -> list[str]:
    """Collect freshness, coverage, and Harvester observation warnings."""
    root = root or runtime_io.ROOT
    surface_dir_fn = surface_dir_fn or (lambda name: root / "Output" / name)
    warnings: list[str] = []

    # 1. Framework output freshness
    freshness = freshness_fn() if freshness_fn is not None else check_freshness(
        root=root,
        surface_dir_fn=surface_dir_fn,
    )
    if freshness["status"] == "stale":
        warnings.append(f"STALE: framework_output is {freshness['stale_hours']}h old")
    elif freshness["status"] == "missing":
        warnings.append("MISSING: neutral_pressure_snapshot.json does not exist")

    # 2. Coverage status — ACTIVE_PARTIAL / DEGRADED_PARTIAL are normal
    # research operating modes and must not page every nightly run.
    fw_path = surface_dir_fn("current") / "neutral_pressure_snapshot.json"
    _benign_coverage = {"ACTIVE_FULL", "ACTIVE_PARTIAL", "DEGRADED_PARTIAL"}
    if fw_path.exists():
        try:
            fw = json.loads(fw_path.read_text(encoding="utf-8"))
            overall = fw.get("basic", {}).get("overall", "UNKNOWN")
            quality = fw.get("basic", {}).get("quality_status", "UNKNOWN")
            if overall not in _benign_coverage:
                warnings.append(f"COVERAGE: overall={overall}")
            if "PROXY_REDUCED" in str(quality):
                warnings.append(f"QUALITY: {quality}")
        except Exception:
            warnings.append("PARSE_ERROR: cannot read neutral_pressure_snapshot.json")

    # 3. Harvester observation freshness. Finalization time is not data
    # freshness: a repaired old release can be finalized today while its
    # observations remain stale. Require both decision-facing panels to have
    # coverage and compare their oldest observation end date.
    latest = root / "Data" / "harvester" / "exports" / "latest"
    if latest.exists():
        observation_ends: dict[str, date] = {}
        for dataset_id in ("benchmark_panel", "cross_asset_daily_panel"):
            manifest = latest / "manifests" / f"{dataset_id}.manifest.json"
            try:
                payload = json.loads(manifest.read_text(encoding="utf-8"))
                raw_end = str(payload.get("time_coverage", {}).get("end", ""))[:10]
                if raw_end:
                    observation_ends[dataset_id] = date.fromisoformat(raw_end)
                outcome = payload.get("provider_outcome")
                if isinstance(outcome, dict):
                    status = str(outcome.get("status") or "").strip()
                    if status in {
                        "reused_after_provider_failure",
                        "provider_failed_no_acceptable_fallback",
                        "environmentally_blocked",
                    }:
                        failed = outcome.get("failed_count")
                        requested = outcome.get("requested_count")
                        counts = (
                            f" failed={failed}/{requested}"
                            if failed is not None and requested is not None
                            else ""
                        )
                        warnings.append(
                            f"HARVESTER_PROVIDER_DEGRADED: {dataset_id} "
                            f"status={status}{counts}"
                        )
            except Exception:
                logger.debug("Failed to parse Harvester observation manifest", exc_info=True)
        if len(observation_ends) == 2:
            oldest = min(observation_ends.values())
            age = (datetime.now(UTC).date() - oldest).days
            if age > 3:
                detail = ", ".join(
                    f"{name}={value.isoformat()}" for name, value in sorted(observation_ends.items())
                )
                warnings.append(f"HARVESTER_STALE: observations are {age} days old ({detail})")
        else:
            missing = sorted({"benchmark_panel", "cross_asset_daily_panel"} - observation_ends.keys())
            warnings.append(f"HARVESTER_OBSERVATION_MISSING: {missing}")
    else:
        warnings.append("HARVESTER_MISSING: no latest release")

    return warnings
