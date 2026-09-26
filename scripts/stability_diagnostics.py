"""Compatibility shim. Canonical implementation: workbench.measurement.stability_diagnostics."""
from __future__ import annotations

import sys
from importlib import import_module

_impl = import_module('workbench.measurement.stability_diagnostics')
if __name__ != "__main__":
    sys.modules[__name__] = _impl
else:
    import runpy
    runpy.run_module('workbench.measurement.stability_diagnostics', run_name="__main__")
