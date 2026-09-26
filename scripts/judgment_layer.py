"""Compatibility shim. Canonical implementation: workbench.judgment.judgment_layer."""
from __future__ import annotations

import sys
from importlib import import_module

_impl = import_module('workbench.judgment.judgment_layer')
if __name__ != "__main__":
    sys.modules[__name__] = _impl
else:
    import runpy
    runpy.run_module('workbench.judgment.judgment_layer', run_name="__main__")
