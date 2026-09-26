"""Schedule and compatibility admission policy for the daily application."""
from __future__ import annotations

import argparse
import os
from datetime import datetime


def legacy_daily_run_enabled() -> bool:
    """Return whether the explicitly opted-in archived executor is enabled."""
    return os.environ.get("SYSTEM_USE_LEGACY_DAILY_RUN", "").strip() in {
        "1",
        "true",
        "TRUE",
        "yes",
        "YES",
    }


def generation_transaction_enabled() -> bool:
    """Return whether immutable-generation publication is enabled."""
    return os.environ.get("SYSTEM_GENERATION_MODE", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def detect_schedule_slot(hour: int) -> str:
    """Map a UTC hour to the stable run-bundle schedule label."""
    if hour < 10:
        return "overnight"
    if hour < 17:
        return "mid_session"
    if hour < 22:
        return "post_close"
    return "daily_summary"


def weekly_cadence_due(start_time: datetime, args: argparse.Namespace) -> bool:
    """Return whether the weekly compatibility readout is due."""
    return start_time.weekday() == 0 or bool(getattr(args, "force_weekly", False))
