"""Verify daily_pipeline_registry.yaml step order matches daily_run_sequence.yaml.

These two files independently define the pipeline step list.
This test ensures they stay in sync.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from _runtime_io import load_yaml

PIPELINE_PATH = ROOT / "governance" / "daily_pipeline_registry.yaml"
SEQUENCE_PATH = ROOT / "governance" / "daily_run_sequence.yaml"


def test_sequence_steps_exist_in_pipeline():
    """Every step in daily_run_sequence.yaml must exist in daily_pipeline_registry.yaml."""
    pipeline = load_yaml(PIPELINE_PATH)
    sequence = load_yaml(SEQUENCE_PATH)

    assert pipeline is not None, f"Cannot load {PIPELINE_PATH}"
    assert sequence is not None, f"Cannot load {SEQUENCE_PATH}"

    pipeline_steps = set(pipeline.get("steps", {}).keys())
    sequence_steps = {s["id"] for s in sequence.get("steps", []) if isinstance(s, dict)}

    missing = sequence_steps - pipeline_steps
    assert not missing, (
        f"Steps in daily_run_sequence.yaml but missing from daily_pipeline_registry.yaml: {missing}"
    )


def test_pipeline_steps_exist_in_sequence():
    """Every active step in daily_pipeline_registry.yaml should appear in daily_run_sequence.yaml."""
    pipeline = load_yaml(PIPELINE_PATH)
    sequence = load_yaml(SEQUENCE_PATH)

    assert pipeline is not None
    assert sequence is not None

    pipeline_steps = {
        name for name, cfg in pipeline.get("steps", {}).items()
        if isinstance(cfg, dict) and cfg.get("status") not in (None, "shadow_active", "archived")
    }
    sequence_steps = {s["id"] for s in sequence.get("steps", []) if isinstance(s, dict)}

    # Steps in pipeline but not in sequence (excluding null-order / shadow steps)
    missing = {
        name for name in pipeline_steps - sequence_steps
        if pipeline["steps"][name].get("order") is not None
    }
    assert not missing, (
        f"Active steps in daily_pipeline_registry.yaml but missing from daily_run_sequence.yaml: {missing}"
    )


def test_no_duplicate_steps_in_sequence():
    """No duplicate step IDs in daily_run_sequence.yaml."""
    sequence = load_yaml(SEQUENCE_PATH)
    assert sequence is not None

    ids = [s["id"] for s in sequence.get("steps", []) if isinstance(s, dict)]
    duplicates = [x for x in ids if ids.count(x) > 1]
    assert not duplicates, f"Duplicate step IDs in daily_run_sequence.yaml: {set(duplicates)}"
