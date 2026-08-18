"""Load compiled pipeline steps from the workspace registry authority."""
from __future__ import annotations

from typing import Any, cast

from scripts._daily_run_sequence import (
    dry_run_labels,
    load_daily_run_sequence,
    weekly_step_ids,
)
from system_runtime.paths import WorkspacePaths
from system_runtime.pipeline import CompiledPipeline, load_pipeline


def compiled_pipeline(paths: WorkspacePaths | None = None) -> CompiledPipeline:
    return load_pipeline(paths or WorkspacePaths.discover())


def daily_sequence() -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], load_daily_run_sequence())


def weekly_ids() -> set[str]:
    return cast(set[str], weekly_step_ids())


def dry_run_plan() -> list[str]:
    return cast(list[str], dry_run_labels())
