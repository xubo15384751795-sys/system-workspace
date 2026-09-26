"""Compatibility shim. Canonical implementation: harvester.operators.dual_path_compare."""
from __future__ import annotations

import sys
from importlib import import_module

_impl = import_module('harvester.operators.dual_path_compare')
if __name__ != "__main__":
    sys.modules[__name__] = _impl
else:
    import runpy
    runpy.run_module('harvester.operators.dual_path_compare', run_name="__main__")
