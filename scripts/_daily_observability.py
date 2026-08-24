"""Best-effort daily-run notification summary and heartbeat publication."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from orchestration.quality.contract_observation import record_launchd_observation

from scripts._runtime_io import ROOT
from system_runtime.daily_heartbeat import write_daily_run_heartbeat

logger = logging.getLogger(__name__)


def publish_daily_run_observability(
    outcome: Mapping[str, Any],
    *,
    output_root: Path | None = None,
    source: str | None = None,
    failed_steps: list[str] | None = None,
    warnings: list[str] | None = None,
    workspace_root: Path | None = None,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    """Record the local ``I ran`` signal and send the configured summary.

    Both sinks are deliberately non-authoritative.  A sink failure is visible
    in logs/return metadata but never rewrites the typed daily-run outcome.
    """
    result: dict[str, Any] = {
        "heartbeat": None,
        "summary_sent": False,
        "data_contract_observation": None,
    }
    try:
        result["heartbeat"] = write_daily_run_heartbeat(
            outcome,
            output_root=output_root,
            source=source,
            observed_at=observed_at,
        )
    except Exception:  # noqa: BLE001 - observability must not change run authority
        logger.exception("Failed to write daily-run heartbeat")

    try:
        result["data_contract_observation"] = record_launchd_observation(
            workspace_root=workspace_root or ROOT,
            output_root=output_root or (ROOT / "Output"),
            outcome=outcome,
            source=source,
            observed_at=observed_at,
        )
    except Exception:  # noqa: BLE001 - observation counting must not change run authority
        logger.exception("Failed to record data-contract observation window")

    try:
        from scripts._notify import notify_daily_run_summary

        result["summary_sent"] = notify_daily_run_summary(
            status=str(outcome.get("status") or "unknown"),
            outcome=dict(outcome),
            failed_steps=failed_steps,
            warnings=warnings,
        )
    except Exception:  # noqa: BLE001 - observability must not change run authority
        logger.exception("Failed to send daily-run notification summary")
    return result


__all__ = ["publish_daily_run_observability"]
