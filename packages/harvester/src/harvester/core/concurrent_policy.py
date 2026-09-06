"""Opt-in concurrent acquisition policy for harvester.official.

Default is off. FRED in-flight stays at most 4. A global budget skips
remaining series so carry-forward can stamp ``deadline``. Any scheduled
``HARVESTER_NOT_COMMITTED`` disables the switch via a state file.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

ENV_NAME = "SYSTEM_HARVESTER_CONCURRENT"
BUDGET_ENV = "HARVESTER_CONCURRENT_BUDGET_SEC"
# Cap is ≤ 4. OpenBB/aiohttp is not thread-safe, so FRED stays on one
# worker; the family still overlaps ETF and external pools.
FRED_MAX_WORKERS = 1
# ETF provider_state files are not safe under threaded writes.
ETF_MAX_WORKERS = 1
EXTERNAL_MAX_WORKERS = 4
DEFAULT_BUDGET_SEC = 30 * 60
FRED_PROVIDERS = frozenset({"fred", "openbb_fred"})
ETF_PROVIDERS = frozenset(
    {"etf_provider_chain", "openbb_tiingo", "openbb_yfinance", "etf_yfinance"}
)
DISABLE_RELPATH = "state/harvester_concurrent.disabled"


def concurrent_enabled() -> bool:
    if os.environ.get(ENV_NAME, "").strip() != "1":
        return False
    if _disable_path().is_file():
        return False
    return True


def budget_seconds() -> int:
    raw = os.environ.get(BUDGET_ENV, "").strip()
    if not raw:
        return DEFAULT_BUDGET_SEC
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_BUDGET_SEC
    return max(1, value)


def family_for_priority(priority: tuple[str, ...] | list[str]) -> str:
    names = {str(item) for item in priority}
    if names & ETF_PROVIDERS:
        return "etf"
    if names & FRED_PROVIDERS:
        return "fred"
    return "other"


def disable_concurrent(reason: str) -> Path:
    """Latch the switch off after a harvester commit failure."""
    path = _disable_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "disabled_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "reason": reason,
        "env": ENV_NAME,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    logger.error("disabled %s: %s (%s)", ENV_NAME, reason, path)
    return path


def _disable_path() -> Path:
    try:
        from system_runtime.paths import WorkspacePaths

        return WorkspacePaths.discover().output / DISABLE_RELPATH
    except Exception:
        return Path("Output") / DISABLE_RELPATH


__all__ = [
    "BUDGET_ENV",
    "DEFAULT_BUDGET_SEC",
    "ENV_NAME",
    "ETF_MAX_WORKERS",
    "ETF_PROVIDERS",
    "EXTERNAL_MAX_WORKERS",
    "FRED_MAX_WORKERS",
    "FRED_PROVIDERS",
    "budget_seconds",
    "concurrent_enabled",
    "disable_concurrent",
    "family_for_priority",
]
