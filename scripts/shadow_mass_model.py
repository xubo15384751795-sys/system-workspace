"""Compatibility shim. Canonical implementation: workbench.measurement.shadow_mass_model."""
from __future__ import annotations

import sys
from importlib import import_module

_impl = import_module('workbench.measurement.shadow_mass_model')
if __name__ != "__main__":
    sys.modules[__name__] = _impl
else:
    import runpy
    runpy.run_module('workbench.measurement.shadow_mass_model', run_name="__main__")
