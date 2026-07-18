"""Compile the daily sequence from the authoritative pipeline registry.

``governance/daily_run_sequence.yaml`` is now a generated compatibility view.
Runtime order, schedule, and skip flags come only from
``governance/daily_pipeline_registry.yaml``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts._runtime_io import ROOT, load_yaml

PIPELINE_PATH = ROOT / "governance" / "daily_pipeline_registry.yaml"
SEQUENCE_PATH = ROOT / "governance" / "daily_run_sequence.yaml"  # generated view


def load_daily_run_sequence(path: Path = PIPELINE_PATH) -> list[dict[str, Any]]:
    """Return ordered runnable steps compiled from the pipeline registry."""
    if not path.exists():
        return []
    data = load_yaml(path)
    defaults = data.get("_defaults", {}) or {}
    compiled: list[tuple[float, str, dict[str, Any]]] = []
    for step_id, raw in (data.get("steps", {}) or {}).items():
        if not isinstance(raw, dict):
            continue
        if raw.get("status", "active") in {"archived", "inactive"}:
            continue
        schedule = raw.get("schedule", defaults.get("schedule", "daily"))
        if schedule == "on_demand":
            continue
        record: dict[str, Any] = {"id": str(step_id)}
        if schedule != "daily":
            record["schedule"] = schedule
        if raw.get("skip_flag"):
            record["skip_flag"] = raw["skip_flag"]
        order = raw.get("order")
        compiled.append((float(order if order is not None else 9999), str(step_id), record))
    compiled.sort(key=lambda item: (item[0], item[1]))
    return [record for _, _, record in compiled]


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
