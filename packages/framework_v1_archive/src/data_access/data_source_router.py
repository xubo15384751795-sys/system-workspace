from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any
import warnings

from src.data_access.errors import EvidenceBoundaryError
from src.data_access.harvester_adapter import HarvesterAdapter
from src.data_access.legacy_adapter import LegacyDataAdapter


class DataBackend(str, Enum):
    LEGACY = "legacy"
    HARVESTER = "harvester"


class DataSourceRouter:
    """Choose the admitted-evidence backend from config.

    The default backend is Harvester. The legacy provider path is available
    only when explicitly enabled for migration support.
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        *,
        backend: str | None = None,
        allow_legacy: bool = False,
    ) -> None:
        self.config = config or {}
        self.configured_backend = backend
        self.allow_legacy = allow_legacy or bool(self.config.get("allow_legacy"))
        self.allow_legacy = self.allow_legacy or bool((self.config.get("data_access") or {}).get("allow_legacy"))
        self.allow_legacy = self.allow_legacy or bool((self.config.get("legacy") or {}).get("allow_data_backend"))

    @property
    def backend(self) -> DataBackend:
        configured = self.configured_backend or self.config.get("data_backend")
        if configured is None:
            configured = ((self.config.get("data_access") or {}).get("backend"))
        if configured is None:
            configured = ((self.config.get("data") or {}).get("backend"))
        if configured is None:
            configured = DataBackend.HARVESTER.value
        try:
            return DataBackend(str(configured))
        except ValueError as exc:
            allowed = ", ".join(item.value for item in DataBackend)
            raise ValueError(f"unknown data_backend {configured!r}; expected one of: {allowed}") from exc

    def create_adapter(self) -> LegacyDataAdapter | HarvesterAdapter:
        if self.backend == DataBackend.LEGACY:
            if not self.allow_legacy:
                raise EvidenceBoundaryError(
                    "Legacy provider backend is disabled by default. "
                    "Use Harvester admitted evidence or pass allow_legacy=True for migration only."
                )
            warnings.warn(
                "data_backend=legacy is a migration-only legacy acquisition path.",
                DeprecationWarning,
                stacklevel=2,
            )
            return LegacyDataAdapter(self.config)
        harvester_config = self.config.get("harvester") or {}
        exports_root = harvester_config.get("exports_root")
        harvester_root = harvester_config.get("root")
        if harvester_root is None:
            harvester_root = (self.config.get("data_access") or {}).get("harvester_root")
        if harvester_root is None:
            harvester_root = (self.config.get("data_access") or {}).get("harvester_export_root")
        if harvester_root is None and exports_root is None:
            raise ValueError("data_backend=harvester requires harvester.exports_root or harvester.root")
        return HarvesterAdapter(
            _resolve_config_path(Path(str(harvester_root))) if harvester_root is not None else None,
            exports_root=_resolve_config_path(Path(str(exports_root))) if exports_root is not None else None,
            release=str(harvester_config.get("release", "latest")),
            catalog_file=str(harvester_config.get("catalog_file", "catalog.json")),
            require_finalized=bool(harvester_config.get("require_finalized", True)),
            validate_hashes=bool(harvester_config.get("validate_hashes", True)),
            validate_schema=bool(harvester_config.get("validate_schema", True)),
        )


def _resolve_config_path(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_absolute():
        return expanded
    return (Path.cwd() / expanded).resolve()


def create_data_adapter(
    config: dict[str, Any] | None = None,
    *,
    allow_legacy: bool = False,
) -> LegacyDataAdapter | HarvesterAdapter:
    return DataSourceRouter(config, allow_legacy=allow_legacy).create_adapter()


__all__ = ["DataBackend", "DataSourceRouter", "create_data_adapter"]
