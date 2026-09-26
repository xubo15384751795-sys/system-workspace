"""Explicit adapter for the archived emergency daily executor.

The default scheduled path never imports this module.  The adapter keeps the
operator-selected ``SYSTEM_USE_LEGACY_DAILY_RUN=1`` escape hatch intact while
making the compatibility boundary visible to the application runtime instead
of coupling ``verity.cli`` to a root ``scripts`` module.
"""
from __future__ import annotations

import runpy
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
ARCHIVED_EXECUTOR = ROOT / "packages" / "framework_v1_archive" / "scripts" / "_legacy_daily_run_executor.py"
MODULE_NAME = "verity._archived_legacy_daily_run_executor"


def _load_archived_executor() -> ModuleType:
    existing = sys.modules.get(MODULE_NAME)
    if existing is not None:
        return existing
    spec = spec_from_file_location(MODULE_NAME, ARCHIVED_EXECUTOR)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load archived executor: {ARCHIVED_EXECUTOR}")
    module = module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


_IMPL = _load_archived_executor()
DailyRunContext = _IMPL.DailyRunContext

# Keep the archived dispatch seam patchable for the explicit emergency path.
# The production default never imports this adapter, but legacy contract tests
# and operators may replace one step without replacing the whole sequence.
execute_step = _IMPL.execute_step


def execute_daily_sequence(ctx):
    """Run the archived sequence while honoring this adapter's dispatch seam."""
    original = _IMPL.execute_step
    _IMPL.execute_step = execute_step
    try:
        return _IMPL.execute_daily_sequence(ctx)
    finally:
        _IMPL.execute_step = original

__all__ = ["DailyRunContext", "execute_daily_sequence", "execute_step"]


if __name__ == "__main__":
    runpy.run_path(str(ARCHIVED_EXECUTOR), run_name="__main__")
