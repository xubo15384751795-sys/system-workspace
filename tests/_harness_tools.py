"""Temporarily bind ``tools`` to the Workbench harness tools package.

Repo-root ``tools/`` (audit/ci) and ``packages/workbench/agents/harness/tools``
share the import name. Tests that need harness tools must own the name for the
duration of the call, then restore the root package for other tests.
"""
from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

HARNESS_ROOT = (
    Path(__file__).resolve().parents[1] / "packages" / "workbench" / "agents" / "harness"
)


@contextmanager
def harness_tools_owner() -> Iterator[Path]:
    saved = {
        name: sys.modules.pop(name)
        for name in list(sys.modules)
        if name == "tools" or name.startswith("tools.")
    }
    inserted = False
    if str(HARNESS_ROOT) not in sys.path:
        sys.path.insert(0, str(HARNESS_ROOT))
        inserted = True
    try:
        yield HARNESS_ROOT
    finally:
        if inserted and str(HARNESS_ROOT) in sys.path:
            sys.path.remove(str(HARNESS_ROOT))
        for name in list(sys.modules):
            if name == "tools" or name.startswith("tools."):
                del sys.modules[name]
        sys.modules.update(saved)
