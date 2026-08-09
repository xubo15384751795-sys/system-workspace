"""CLI smoke: Dagster daily_job dry-run succeeds."""
from __future__ import annotations

from orchestration.cli import cmd_daily


def test_cmd_daily_dry_run():
    assert cmd_daily(["--dry-run"]) == 0
