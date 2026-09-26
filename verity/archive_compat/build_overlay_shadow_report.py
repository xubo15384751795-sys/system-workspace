"""Callable metadata adapter for the archived overlay shadow executable.

The default plan runs the archived file as an explicitly justified
subprocess.  This adapter exists only for tools that inspect or shadow-run the
registry's callable metadata; it does not create a second execution path for
the scheduled run.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

_ARCHIVE_PATH = (
    Path(__file__).resolve().parents[2]
    / "packages"
    / "framework_v1_archive"
    / "scripts"
    / "build_overlay_shadow_report.py"
)


def _load_archive_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "verity_archived_build_overlay_shadow_report", _ARCHIVE_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load archived executable: {_ARCHIVE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    """Delegate only when an explicit compatibility caller invokes the adapter."""
    _load_archive_module().main()
