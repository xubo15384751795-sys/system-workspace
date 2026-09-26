"""Shared path constants for workspace-level Workbench utilities.

Every workspace utility resolves the workspace root from this module so that
relative paths in `Data/system_index/*.json` and `Output/.../*.json` remain
meaningful regardless of cwd.
"""
from __future__ import annotations

from pathlib import Path
from typing import cast

from workbench.paths import workspace_root as _workspace_root

WORKSPACE_ROOT = cast(Path, _workspace_root())

DATA_DIR = WORKSPACE_ROOT / "Data"
OUTPUT_DIR = WORKSPACE_ROOT / "Output"
REPORTS_DIR = OUTPUT_DIR / "archive" / "legacy_2026H1" / "reports"

HARVESTER_EXPORTS = DATA_DIR / "harvester" / "exports"
HARVESTER_LATEST = HARVESTER_EXPORTS / "latest"

CURRENT_DIR = OUTPUT_DIR / "current"
NEUTRAL_PRESSURE_SNAPSHOT = CURRENT_DIR / "neutral_pressure_snapshot.json"

# Archived Deformation v1 run packages. Not a live latest pointer.
DEFORMATION_RUNS = OUTPUT_DIR / "archive" / "legacy_2026H1" / "deformation_runs"
ARCHIVE_RUNS = DEFORMATION_RUNS

CANONICAL_SNAPSHOTS = DATA_DIR / "deformation" / "snapshots"
CANONICAL_SNAPSHOT_INDEX = CANONICAL_SNAPSHOTS / "index.json"
QUARANTINE_SNAPSHOTS = DATA_DIR / "deformation" / "quarantine" / "snapshots"

SYSTEM_INDEX_DIR = DATA_DIR / "system_index"
SYSTEM_LATEST = SYSTEM_INDEX_DIR / "latest.json"
SYSTEM_CATALOG = SYSTEM_INDEX_DIR / "system_catalog.json"
LINEAGE_GRAPH = SYSTEM_INDEX_DIR / "lineage_graph.json"

LEARNING_LATEST_DIR = OUTPUT_DIR / "system_learning" / "latest"
LEARNING_SUMMARY = LEARNING_LATEST_DIR / "summary.json"

SANDBOX_OPENBB_RUNS = OUTPUT_DIR / "state" / "sandbox" / "openbb" / "runs"
SANDBOX_QLIB_RUNS = OUTPUT_DIR / "state" / "sandbox" / "qlib" / "runs"
