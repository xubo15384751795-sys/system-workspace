"""F.1: Legacy DataHub Freeze.

When the freeze is active, DataHub.fetch_series() and similar methods raise
LegacyDataHubFrozen unless ALLOW_LEGACY_DATAHUB=1 is set in the environment.
"""

from __future__ import annotations

import os
from typing import Any


class LegacyDataHubFrozen(RuntimeError):
    """Raised when legacy DataHub acquisition is invoked while frozen."""


_FROZEN = False


def freeze_legacy_datahub() -> None:
    """Freeze legacy DataHub acquisition globally."""
    global _FROZEN
    _FROZEN = True


def unfreeze_legacy_datahub() -> None:
    """Unfreeze legacy DataHub (for testing)."""
    global _FROZEN
    _FROZEN = False


def is_frozen() -> bool:
    """Check if legacy DataHub is frozen."""
    return _FROZEN


def check_legacy_allowed(operation: str = "fetch_series") -> None:
    """Raise LegacyDataHubFrozen if legacy acquisition is blocked.

    Does not raise when ALLOW_LEGACY_DATAHUB=1.
    """
    if not _FROZEN:
        return
    if os.environ.get("ALLOW_LEGACY_DATAHUB") == "1":
        return
    raise LegacyDataHubFrozen(
        f"Legacy DataHub acquisition is frozen. Operation '{operation}' blocked. "
        "Use a Harvester release through DataHubLite. "
        "Set ALLOW_LEGACY_DATAHUB=1 only for migration testing."
    )


def guard_method(method: Any) -> Any:
    """Decorator to guard a DataHub method against frozen access."""
    from functools import wraps

    @wraps(method)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        check_legacy_allowed(method.__name__)
        return method(*args, **kwargs)

    return wrapper


__all__ = [
    "LegacyDataHubFrozen",
    "check_legacy_allowed",
    "freeze_legacy_datahub",
    "guard_method",
    "is_frozen",
    "unfreeze_legacy_datahub",
]
