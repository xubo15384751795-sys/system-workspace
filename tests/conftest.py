"""Centralized test path setup.

Adds scripts/ and Workbench/src/ to sys.path so individual test files
don't need their own sys.path.insert calls.

CI already sets PYTHONPATH="Workbench/src:scripts" — this conftest
replicates that for local development.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

_paths_to_add = [
    str(_ROOT / "scripts"),
    str(_ROOT / "Workbench" / "src"),
    str(_ROOT / "deformation-framework" / "src"),
    str(_ROOT / "system-learning-hub" / "src"),
]

for _p in _paths_to_add:
    if _p not in sys.path:
        sys.path.insert(0, _p)
