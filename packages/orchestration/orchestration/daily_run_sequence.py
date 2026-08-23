"""Compile the daily sequence from the authoritative pipeline registry.

``governance/daily_run_sequence.yaml`` is now a generated compatibility view.
Runtime order, schedule, and skip flags come only from
``governance/daily_pipeline_registry.yaml`` via the typed
``CompiledPipeline`` compiler (WP1B).  This module no longer performs a
raw-YAML sort; it delegates to the single compiler so the executor, runner,
and entrypoint all use the same authoritative ordering.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts._runtime_io import ROOT

PIPELINE_PATH = ROOT / "governance" / "daily_pipeline_registry.yaml"
SEQUENCE_PATH = ROOT / "governance" / "daily_run_sequence.yaml"  # generated view


def load_daily_run_sequence(path: Path = PIPELINE_PATH) -> list[dict[str, Any]]:
    """Return ordered runnable steps compiled from the pipeline registry.

    Delegates to ``system_runtime.pipeline.load_pipeline`` (the single
    compiler) so ordering, filtering, and duplicate-order detection are
    authoritative. A compiler/schema failure is intentionally propagated:
    an invalid plan must start zero steps.
    """
    if not path.exists():
        raise FileNotFoundError(f"authoritative pipeline registry missing: {path}")
    if path != PIPELINE_PATH:
        raise ValueError(
            "custom sequence paths are not execution authorities; "
            "compile governance/daily_pipeline_registry.yaml instead"
        )
    from system_runtime.paths import WorkspacePaths
    from system_runtime.pipeline import load_pipeline

    ws = WorkspacePaths(root=ROOT)
    return load_pipeline(ws).sequence()


def step_ids(path: Path = PIPELINE_PATH) -> list[str]:
    return [str(step["id"]) for step in load_daily_run_sequence(path) if step.get("id")]


def weekly_step_ids(path: Path = PIPELINE_PATH) -> set[str]:
    """Return set of step IDs that are scheduled weekly."""
    steps = load_daily_run_sequence(path)
    return {str(s["id"]) for s in steps if s.get("schedule") == "weekly"}


def dry_run_labels(path: Path = PIPELINE_PATH) -> list[str]:
    steps = load_daily_run_sequence(path)
    weekly = weekly_step_ids(path)
    labels = []
    for index, step in enumerate(steps, start=1):
        sid = step["id"]
        tag = " [weekly]" if sid in weekly else ""
        labels.append(f"{index}. {sid}{tag}")
    return labels
