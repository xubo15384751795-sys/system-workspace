"""Legacy DuckDB Snapshot Store Freeze.

When the freeze is active, DuckDBSnapshotStore write methods (save,
save_fast_signal, save_cross_validation, upsert_raw_series, upsert_event_log)
raise LegacySnapshotStoreFrozen unless ALLOW_LEGACY_DUCKDB=1 is set in the
environment. Reads remain permitted during the evidence window so that
DualWriteSnapshotStore can verify parity and dl_anomaly_detector /
result_renderer can serve historical queries.

Migration: 2026-07-07-duckdb-snapshot-store-migration (FREEZE→MOVE→SEAL).
The DuckDB store is sealed read-only once HarvesterSnapshotStore is canonical.
"""

from __future__ import annotations

import os
from typing import Any


class LegacySnapshotStoreFrozen(RuntimeError):
    """Raised when a frozen DuckDBSnapshotStore write method is invoked."""


_FROZEN = False


def freeze_legacy_snapshot_store() -> None:
    """Freeze legacy DuckDB snapshot store writes globally."""
    global _FROZEN
    _FROZEN = True


def unfreeze_legacy_snapshot_store() -> None:
    """Unfreeze legacy DuckDB snapshot store (for testing)."""
    global _FROZEN
    _FROZEN = False


def is_frozen() -> bool:
    """Check if legacy DuckDB snapshot store writes are frozen."""
    return _FROZEN


def check_legacy_allowed(operation: str = "save") -> None:
    """Raise LegacySnapshotStoreFrozen if a frozen write is blocked.

    Does not raise when ALLOW_LEGACY_DUCKDB=1.
    """
    if not _FROZEN:
        return
    if os.environ.get("ALLOW_LEGACY_DUCKDB") == "1":
        return
    raise LegacySnapshotStoreFrozen(
        f"Legacy DuckDB snapshot store writes are frozen. Operation '{operation}' blocked. "
        "Use HarvesterSnapshotStore (config snapshot_store.backend=harvester). "
        "Set ALLOW_LEGACY_DUCKDB=1 only for migration testing."
    )


def guard_method(method: Any) -> Any:
    """Decorator to guard a DuckDBSnapshotStore write method against frozen access."""
    from functools import wraps

    @wraps(method)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        check_legacy_allowed(method.__name__)
        return method(*args, **kwargs)

    return wrapper


__all__ = [
    "LegacySnapshotStoreFrozen",
    "check_legacy_allowed",
    "freeze_legacy_snapshot_store",
    "guard_method",
    "is_frozen",
    "unfreeze_legacy_snapshot_store",
]
