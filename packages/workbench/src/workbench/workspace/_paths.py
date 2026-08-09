"""Shared path constants for workspace-level Workbench utilities.

Every workspace utility resolves the workspace root from this module so that
relative paths in `Data/system_index/*.json` and `Output/.../*.json` remain
meaningful regardless of cwd.
"""
from __future__ import annotations

from workbench.paths import workspace_root as _workspace_root

WORKSPACE_ROOT = _workspace_root()

DATA_DIR = WORKSPACE_ROOT / "Data"
OUTPUT_DIR = WORKSPACE_ROOT / "Output"
REPORTS_DIR = OUTPUT_DIR / "reports"

HARVESTER_EXPORTS = DATA_DIR / "harvester" / "exports"
HARVESTER_LATEST = HARVESTER_EXPORTS / "latest"

DEFORMATION_RUNS = OUTPUT_DIR / "deformation_runs"
DEFORMATION_LATEST = DEFORMATION_RUNS / "latest"

CANONICAL_SNAPSHOTS = DATA_DIR / "deformation" / "snapshots"
CANONICAL_SNAPSHOT_INDEX = CANONICAL_SNAPSHOTS / "index.json"
QUARANTINE_SNAPSHOTS = DATA_DIR / "deformation" / "quarantine" / "snapshots"

SYSTEM_INDEX_DIR = DATA_DIR / "system_index"
SYSTEM_LATEST = SYSTEM_INDEX_DIR / "latest.json"
SYSTEM_CATALOG = SYSTEM_INDEX_DIR / "system_catalog.json"
LINEAGE_GRAPH = SYSTEM_INDEX_DIR / "lineage_graph.json"

LEARNING_LATEST_DIR = OUTPUT_DIR / "system_learning" / "latest"
LEARNING_SUMMARY = LEARNING_LATEST_DIR / "summary.json"

SANDBOX_OPENBB_RUNS = OUTPUT_DIR / "sandbox" / "openbb" / "runs"
SANDBOX_QLIB_RUNS = OUTPUT_DIR / "sandbox" / "qlib" / "runs"
