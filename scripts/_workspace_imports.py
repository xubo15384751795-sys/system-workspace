"""Unified workspace import helpers — transitional path management.

Instead of hand-writing sys.path.insert(0, ...) in every script, use these
helpers.  This makes sys.path management auditable and prepares for the
future module runner migration.

Usage::

    from _workspace_imports import add_workbench_src
    add_workbench_src()

Audit rule: root scripts must NOT use raw sys.path.insert.
Only _workspace_imports.py and architecture_reality_audit.py may touch sys.path.

See: governance/deferred_work_register.yaml (sys.path consolidation)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _add(path: Path) -> None:
    """Add *path* to sys.path if not already present."""
    s = str(path)
    if s not in sys.path:
        sys.path.insert(0, s)


def add_workbench_src() -> None:
    """Add Workbench/src to sys.path."""
    _add(ROOT / "Workbench" / "src")


def add_learning_hub_src() -> None:
    """Add system-learning-hub/src to sys.path."""
    _add(ROOT / "system-learning-hub" / "src")


def add_framework_src() -> None:
    """Add Structural Deformation Research System/src to sys.path."""
    _add(ROOT / "Structural Deformation Research System" / "src")


def add_harvester_src() -> None:
    """Add Harvester/src to sys.path."""
    _add(ROOT / "Harvester" / "src")


def add_root() -> None:
    """Add project root to sys.path."""
    _add(ROOT)


def add_scripts() -> None:
    """Add scripts/ to sys.path."""
    _add(ROOT / "scripts")
