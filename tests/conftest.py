"""Centralized test path setup.

Adds scripts/ and package src/ directories to sys.path so individual test
files don't need their own sys.path.insert calls.

CI sets PYTHONPATH to the same package paths — this conftest replicates
that for local development.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

_paths_to_add = [
    str(_ROOT / "scripts"),
    str(_ROOT / "packages" / "framework"),
    str(_ROOT / "packages" / "framework" / "src"),
    str(_ROOT / "packages" / "harvester" / "src"),
    str(_ROOT / "packages" / "learning_hub" / "src"),
    # workbench/src last so it wins path priority (richer nlp/workbench packages
    # must not be shadowed by framework's slimmer nlp/event_translator package).
    str(_ROOT / "packages" / "workbench" / "src"),
]

for _p in _paths_to_add:
    if _p not in sys.path:
        sys.path.insert(0, _p)
