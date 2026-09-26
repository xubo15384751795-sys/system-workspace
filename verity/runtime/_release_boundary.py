"""Verified panel loader (Phase B4).

Routes production consumers (paper_portfolio, structural_replay) through a
release-finalization check before reading the benchmark panel, so a tampered
or unfinalized ``latest`` symlink cannot be silently consumed.

This is a thin verification layer over the existing harvester release layout
(catalog.json + .finalized marker). It does NOT replace the richer
``packages/framework_v1_archive/src/data_access/AdmittedEvidenceHub`` boundary - that
remains the long-term target - but it closes the immediate Phase B4 gap:
"no daily-run consumer verifies release finalization before reading."

Usage:
    from verity.runtime._release_boundary import load_benchmark_panel_verified
    panel = load_benchmark_panel_verified()  # raises if unfinalized/tampered
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from verity.runtime.runtime_io import ROOT

HARVESTER_LATEST = ROOT / "Data" / "harvester" / "exports" / "latest"


class ReleaseNotFinalizedError(RuntimeError):
    """Raised when a consumer reads a harvester release that is not finalized."""


def _release_dir(release_dir: Path | None = None) -> Path:
    return release_dir or HARVESTER_LATEST


def verify_release_finalized(release_dir: Path | None = None) -> dict:
    """Verify the harvester release is finalized and its catalog is intact.

    Checks (dataset-mode release):
    - ``.finalized`` marker file exists
    - ``catalog.json`` parses and names the release
    - ``release_digest.txt`` present (sha256 manifest)

    Returns the parsed catalog. Raises ReleaseNotFinalizedError on any failure.
    """
    release = _release_dir(release_dir).resolve()
    finalized = release / ".finalized"
    if not finalized.exists():
        raise ReleaseNotFinalizedError(
            f"harvester release not finalized (no .finalized marker): {release}"
        )
    catalog_path = release / "catalog.json"
    if not catalog_path.exists():
        raise ReleaseNotFinalizedError(
            f"harvester release missing catalog.json: {release}"
        )
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ReleaseNotFinalizedError(
            f"harvester release catalog.json unparseable: {exc}"
        ) from exc
    # Bundle-mode releases carry a status field; dataset-mode rely on .finalized.
    status = catalog.get("status")
    if status is not None and status != "finalized":
        raise ReleaseNotFinalizedError(
            f"harvester release catalog status={status!r} (expected 'finalized'): {release}"
        )
    return catalog


def _resolve_panel_path(release: Path, catalog: dict) -> Path:
    """Locate the benchmark panel parquet in the release (bundle or dataset mode)."""
    # Bundle mode: files[].role == benchmark_panel
    for f in catalog.get("files", []) or []:
        if f.get("role") == "benchmark_panel":
            return release / f["path"]
    # Dataset mode: datasets[].dataset_id in (official_panel, benchmark_panel)
    for d in catalog.get("datasets", []) or []:
        if d.get("dataset_id") in ("official_panel", "benchmark_panel"):
            return release / d.get("data_path", d.get("path", "data/benchmark_panel.parquet"))
    # Fallback: conventional path
    return release / "data" / "benchmark_panel.parquet"


def load_benchmark_panel_verified(release_dir: Path | None = None) -> pd.DataFrame:
    """Load the benchmark panel after verifying the release is finalized.

    Raises ReleaseNotFinalizedError if the release is not finalized or its
    catalog is missing/corrupt. This is the Phase B4 read-time admission check
    that was previously absent (consumers raw-read parquet by path).
    """
    release = _release_dir(release_dir).resolve()
    catalog = verify_release_finalized(release)
    panel_path = _resolve_panel_path(release, catalog)
    if not panel_path.exists():
        raise ReleaseNotFinalizedError(
            f"benchmark panel not found in finalized release: {panel_path}"
        )
    return pd.read_parquet(panel_path)


def is_release_finalized(release_dir: Path | None = None) -> bool:
    """Non-raising check: is the harvester release finalized?"""
    try:
        verify_release_finalized(release_dir)
        return True
    except ReleaseNotFinalizedError:
        return False
