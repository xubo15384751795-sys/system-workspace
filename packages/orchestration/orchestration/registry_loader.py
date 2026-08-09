"""Load compiled pipeline steps from the workspace registry authority."""
from __future__ import annotations

from typing import Any

from system_runtime.paths import WorkspacePaths
from system_runtime.pipeline import CompiledPipeline, load_pipeline

from scripts._daily_run_sequence import dry_run_labels, load_daily_run_sequence, weekly_step_ids


def compiled_pipeline(paths: WorkspacePaths | None = None) -> CompiledPipeline:
    return load_pipeline(paths or WorkspacePaths.discover())


def daily_sequence() -> list[dict[str, Any]]:
    return load_daily_run_sequence()


def weekly_ids() -> set[str]:
    return weekly_step_ids()


def dry_run_plan() -> list[str]:
    return dry_run_labels()
