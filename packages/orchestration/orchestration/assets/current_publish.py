"""Helpers wrapping candidate begin/publish for Dagster daily jobs."""
from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from verity.runtime._current_publish import (
    begin_candidate,
    clear_candidate_env,
    publish_candidate,
    should_publish,
)


def start_candidate(run_dir: Path) -> Path:
    return cast(Path, begin_candidate(run_dir))


def finish_publish(
    *,
    candidate_dir: Path,
    run_id: str,
    run_status: str,
    freshness_report: dict[str, Any],
) -> tuple[bool, str, dict[str, Any] | None]:
    can_publish, reason = should_publish(run_status, freshness_report)
    published = None
    if can_publish:
        published = publish_candidate(candidate_dir, run_id=run_id)
    clear_candidate_env()
    return can_publish, reason, published
