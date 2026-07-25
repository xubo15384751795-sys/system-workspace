"""Path resolution — delegates to RuntimePaths for all new code.

Legacy functions are kept for backward compatibility but now resolve
through RuntimePaths.discover() instead of hardcoded strings.
New code should inject RuntimePaths directly rather than calling these.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.core.runtime_context import RuntimePaths


def _paths(config: dict[str, Any] | None = None) -> RuntimePaths:
    """Resolve RuntimePaths, preferring config override."""
    cfg = config or {}
    project_root = cfg.get("project_root")
    if project_root:
        return RuntimePaths.from_project_root(project_root)
    data_cfg = (config or {}).get("data", {}) or {}
    data_project_root = data_cfg.get("project_root")
    if data_project_root:
        return RuntimePaths.from_project_root(data_project_root)
    return RuntimePaths.discover()


def default_system_root() -> Path:
    return _paths().data_root


def default_lab_root() -> Path:
    return _paths().lab_root


def resolve_system_root(config: dict[str, Any] | None = None) -> Path:
    data_cfg = (config or {}).get("data", {}) or {}
    configured = data_cfg.get("system_root")
    if configured:
        return Path(str(configured)).expanduser()
    legacy_root = data_cfg.get("root")
    if legacy_root:
        return Path(str(legacy_root)).expanduser()
    return _paths(config).data_root


def resolve_lab_root(config: dict[str, Any] | None = None) -> Path:
    data_cfg = (config or {}).get("data", {}) or {}
    configured = data_cfg.get("lab_root")
    if configured:
        return Path(str(configured)).expanduser()
    legacy_root = data_cfg.get("root")
    if legacy_root:
        return Path(str(legacy_root)).expanduser()
    # Cascade through system_root config for backward compatibility
    system_root_configured = data_cfg.get("system_root")
    if system_root_configured:
        return Path(str(system_root_configured)).expanduser() / "structural_lab"
    return _paths(config).lab_root


def resolve_data_root(config: dict[str, Any] | None = None) -> Path:
    return resolve_lab_root(config)


def resolve_snapshot_store_path(config: dict[str, Any] | None = None) -> Path:
    data_cfg = (config or {}).get("data", {}) or {}
    if data_cfg.get("root"):
        return resolve_lab_root(config) / "runtime" / "system.duckdb"
    explicit = ((config or {}).get("runtime", {}) or {}).get("duckdb_path")
    if explicit:
        return Path(str(explicit)).expanduser()
    explicit = ((config or {}).get("snapshot_store", {}) or {}).get("path")
    if explicit:
        return Path(str(explicit)).expanduser()
    # Cascade through config-based lab_root resolution for backward compat
    if data_cfg.get("system_root"):
        return resolve_lab_root(config) / "runtime" / "system.duckdb"
    return _paths(config).snapshot_store_path


def resolve_processed_dir(config: dict[str, Any] | None = None) -> Path:
    explicit = ((config or {}).get("runtime", {}) or {}).get("processed_dir")
    if explicit:
        return Path(str(explicit)).expanduser()
    return _paths(config).processed_dir


def resolve_snapshots_dir(config: dict[str, Any] | None = None) -> Path:
    explicit = ((config or {}).get("runtime", {}) or {}).get("snapshots_dir")
    if explicit:
        return Path(str(explicit)).expanduser()
    return _paths(config).snapshot_dir


def resolve_fred_cache_dir(config: dict[str, Any] | None = None) -> Path:
    ds_cfg = ((config or {}).get("data_sources", {}) or {})
    explicit = ds_cfg.get("fred_cache_dir")
    if explicit:
        return Path(str(explicit)).expanduser()
    # Cascade through config-based lab_root for backward compat
    data_cfg = (config or {}).get("data", {}) or {}
    if data_cfg.get("system_root"):
        return resolve_lab_root(config) / "runtime" / "fred_cache"
    return _paths(config).fred_cache_dir
