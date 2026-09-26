"""Host-process adapters used at the application boundary.

These helpers contain scheduler/host-specific process behavior without
letting the daily application coordinator own its implementation details.
"""
from __future__ import annotations

import logging
import resource
from pathlib import Path

logger = logging.getLogger(__name__)


def truncate_launchd_logs(root: Path, *, max_bytes: int = 10 * 1024 * 1024) -> None:
    """Bound launchd log growth while retaining the most recent tail."""
    log_dir = root / "Output" / "state" / "logs" / "launchd"
    if not log_dir.exists():
        return
    for log_file in log_dir.glob("*.log"):
        try:
            size = log_file.stat().st_size
            if size <= max_bytes:
                continue
            keep = max_bytes // 2
            data = log_file.read_bytes()[-keep:]
            log_file.write_bytes(data)
            logger.info("Truncated %s (%d -> %d bytes)", log_file.name, size, keep)
        except OSError:
            logger.warning("Failed to truncate launchd log: %s", log_file, exc_info=True)


def raise_open_file_limit(*, target: int = 65536) -> None:
    """Raise the soft file-descriptor limit when the host permits it."""
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        if hard == resource.RLIM_INFINITY:
            new_soft = max(soft, target)
        else:
            new_soft = min(max(soft, target), hard)
        if new_soft > soft:
            resource.setrlimit(resource.RLIMIT_NOFILE, (new_soft, hard))
            logger.info("Raised RLIMIT_NOFILE soft limit %s -> %s (hard=%s)", soft, new_soft, hard)
    except (ValueError, OSError) as exc:
        logger.warning("Could not raise RLIMIT_NOFILE: %s", exc)
