"""Load daily_run_sequence.yaml — single source for step order."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from _runtime_io import ROOT, load_yaml

SEQUENCE_PATH = ROOT / "governance" / "daily_run_sequence.yaml"


def load_daily_run_sequence(path: Path = SEQUENCE_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = load_yaml(path)
    return list(data.get("steps", []))


def step_ids(path: Path = SEQUENCE_PATH) -> list[str]:
    return [str(step["id"]) for step in load_daily_run_sequence(path) if step.get("id")]


def weekly_step_ids(path: Path = SEQUENCE_PATH) -> set[str]:
    """Return set of step IDs that are scheduled weekly."""
    steps = load_daily_run_sequence(path)
    return {str(s["id"]) for s in steps if s.get("schedule") == "weekly"}


def dry_run_labels(path: Path = SEQUENCE_PATH) -> list[str]:
    steps = load_daily_run_sequence(path)
    weekly = weekly_step_ids(path)
    labels = []
    for index, step in enumerate(steps, start=1):
        sid = step["id"]
        tag = " [weekly]" if sid in weekly else ""
        labels.append(f"{index}. {sid}{tag}")
    return labels
