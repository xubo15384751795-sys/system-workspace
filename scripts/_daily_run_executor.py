"""Compatibility shim — canonical executor lives in packages/orchestration.

Default path: Dagster jobs import ``orchestration.sequence_executor``.
Emergency path: ``SYSTEM_USE_LEGACY_DAILY_RUN=1`` uses
``scripts/_legacy_daily_run_executor.py``.

Tests that ``patch.object`` this module's ``execute_step`` continue to work:
``execute_daily_sequence`` temporarily rebinds the canonical module global.
"""
from __future__ import annotations

import sys

from orchestration.sequence_executor import (  # noqa: F401
    CUSTOM_COMMAND_BUILDERS,
    STEP_ENV,
    STEP_EXTRA_ARGV,
    STEP_INPUT_ARTIFACTS,
    WEEKLY_STEPS,
    DailyRunContext,
    build_step_invocation,
    should_run_step,
)
from orchestration.sequence_executor import execute_step as _canonical_execute_step
from orchestration import sequence_executor as _sequence_executor

execute_step = _canonical_execute_step


def execute_daily_sequence(ctx):
    """Delegate to canonical executor while honoring patches on this module."""
    this = sys.modules[__name__]
    original = _sequence_executor.execute_step
    _sequence_executor.execute_step = this.execute_step
    try:
        return _sequence_executor.execute_daily_sequence(ctx)
    finally:
        _sequence_executor.execute_step = original


__all__ = [
    "CUSTOM_COMMAND_BUILDERS",
    "DailyRunContext",
    "STEP_ENV",
    "STEP_EXTRA_ARGV",
    "STEP_INPUT_ARTIFACTS",
    "WEEKLY_STEPS",
    "build_step_invocation",
    "execute_daily_sequence",
    "execute_step",
    "should_run_step",
]
