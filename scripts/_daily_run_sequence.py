"""Load daily_run_sequence.yaml — single source for step order."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
SEQUENCE_PATH = ROOT / "governance" / "daily_run_sequence.yaml"


def load_daily_run_sequence(path: Path = SEQUENCE_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return list(data.get("steps", []))


def step_ids(path: Path = SEQUENCE_PATH) -> list[str]:
    return [str(step["id"]) for step in load_daily_run_sequence(path) if step.get("id")]


def dry_run_labels(path: Path = SEQUENCE_PATH) -> list[str]:
    steps = load_daily_run_sequence(path)
    return [f"{index}. {step['id']}" for index, step in enumerate(steps, start=1)]
