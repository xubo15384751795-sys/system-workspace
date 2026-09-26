"""Compatibility shim. Canonical implementation: workbench.judgment.judgment_promotion_gate."""
from __future__ import annotations

import sys
from importlib import import_module

_impl = import_module('workbench.judgment.judgment_promotion_gate')
if __name__ != "__main__":
    sys.modules[__name__] = _impl
else:
    import runpy
    runpy.run_module('workbench.judgment.judgment_promotion_gate', run_name="__main__")
