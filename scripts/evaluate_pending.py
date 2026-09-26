"""Compatibility shim. Canonical implementation: workbench.judgment.evaluate_pending."""
from __future__ import annotations

import sys
from importlib import import_module

_impl = import_module('workbench.judgment.evaluate_pending')
if __name__ != "__main__":
    sys.modules[__name__] = _impl
else:
    import runpy
    runpy.run_module('workbench.judgment.evaluate_pending', run_name="__main__")
