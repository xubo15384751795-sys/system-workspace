"""Compatibility shim. Canonical implementation: workbench.measurement.paper_freshness."""
from __future__ import annotations

import sys
from importlib import import_module

_impl = import_module('workbench.measurement.paper_freshness')
if __name__ != "__main__":
    sys.modules[__name__] = _impl
else:
    import runpy
    runpy.run_module('workbench.measurement.paper_freshness', run_name="__main__")
