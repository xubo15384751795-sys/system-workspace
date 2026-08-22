"""Best-effort daily-run summary and heartbeat publication."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Mapping

from system_runtime.daily_heartbeat import write_daily_run_heartbeat

logger = logging.getLogger(__name__)


def publish_daily_run_observability(
    outcome: Mapping[str, Any],
    *,
    output_root: Path | None = None,
    source: str | None = None,
    failed_steps: list[str] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Record the local ``I ran`` signal and send the Feishu summary.

    Both sinks are deliberately non-authoritative.  A sink failure is visible
    in logs/return metadata but never rewrites the typed daily-run outcome.
    """
    result: dict[str, Any] = {"heartbeat": None, "summary_sent": False}
    try:
        result["heartbeat"] = write_daily_run_heartbeat(
            outcome,
            output_root=output_root,
            source=source,
        )
    except Exception:  # noqa: BLE001 - observability must not change run authority
        logger.exception("Failed to write daily-run heartbeat")

    try:
        from scripts._notify import notify_daily_run_summary

        result["summary_sent"] = notify_daily_run_summary(
            status=str(outcome.get("status") or "unknown"),
            outcome=dict(outcome),
            failed_steps=failed_steps,
            warnings=warnings,
        )
    except Exception:  # noqa: BLE001 - observability must not change run authority
        logger.exception("Failed to send daily-run Feishu summary")
    return result


__all__ = ["publish_daily_run_observability"]
