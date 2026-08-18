"""Compatibility entrypoint for the Framework dual-path comparison utility.

The implementation remains owned by ``packages/framework/scripts``.  This
thin root wrapper keeps the workspace's ``scripts`` import path and registry
entrypoints pointed at the canonical implementation without duplicating it.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def _load_impl() -> ModuleType:
    target = (
        Path(__file__).resolve().parents[1]
        / "packages"
        / "framework"
        / "scripts"
        / "dual_path_compare.py"
    )
    spec = importlib.util.spec_from_file_location("_framework_dual_path_compare", target)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load canonical dual-path utility: {target}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_IMPL = _load_impl()

DualPathResult = _IMPL.DualPathResult
compare_fetch_results = _IMPL.compare_fetch_results
dual_path_report = _IMPL.dual_path_report
run_dual_path = _IMPL.run_dual_path

__all__ = [
    "DualPathResult",
    "compare_fetch_results",
    "dual_path_report",
    "run_dual_path",
]
