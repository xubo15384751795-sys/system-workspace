"""Compatibility shim. Canonical implementation: workbench.measurement.public_residual_stress."""
from __future__ import annotations

import sys
from importlib import import_module

_impl = import_module('workbench.measurement.public_residual_stress')
if __name__ != "__main__":
    sys.modules[__name__] = _impl
else:
    import runpy
    runpy.run_module('workbench.measurement.public_residual_stress', run_name="__main__")
