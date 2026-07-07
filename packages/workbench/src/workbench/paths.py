"""Portable workspace and Workbench root discovery.

Priority order (both functions):
1. ``WORKBENCH_ROOT`` / ``WORKSPACE_ROOT`` environment variable
2. Walk up from cwd looking for a marker file
3. RuntimeError with a clear message
"""

from __future__ import annotations

import os
from pathlib import Path

_WORKSPACE_MARKER = "FRAMEWORK_CONTRACT.md"
_WORKBENCH_MARKER = "pyproject.toml"


def workspace_root() -> Path:
    """Root of the shared workspace (where ``governance/``, ``Output/``, ``Data/`` live).

    Set ``WORKBENCH_ROOT`` or ``WORKSPACE_ROOT`` to override.
    """
    if env := os.environ.get("WORKBENCH_ROOT") or os.environ.get("WORKSPACE_ROOT"):
        return Path(env).resolve()
    candidate = Path.cwd().resolve()
    for p in [candidate, *candidate.parents]:
        if (p / _WORKSPACE_MARKER).exists():
            return p
    raise RuntimeError(
        "Cannot locate workspace root.\n"
        "Set the WORKBENCH_ROOT environment variable to the directory that contains\n"
        f"{_WORKSPACE_MARKER!r}, or run from within the workspace directory.\n"
        "Example:  export WORKBENCH_ROOT=/path/to/workspace"
    )


def workbench_root() -> Path:
    """Root of the Workbench repo (where ``pyproject.toml`` lives).

    Defaults to ``workspace_root() / "Workbench"``.  Set ``WORKBENCH_ROOT``
    to the repo root directly to override.
    """
    if env := os.environ.get("WORKBENCH_ROOT"):
        return Path(env).resolve()
    candidate = Path.cwd().resolve()
    for p in [candidate, *candidate.parents]:
        if (p / _WORKBENCH_MARKER).exists():
            return p
    return workspace_root() / "Workbench"
