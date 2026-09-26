"""Compatibility shim. Canonical implementation: workbench.surfaces.ask_evidence."""
from __future__ import annotations

import sys
from importlib import import_module

_impl = import_module('workbench.surfaces.ask_evidence')
if __name__ != "__main__":
    sys.modules[__name__] = _impl
else:
    import runpy
    runpy.run_module('workbench.surfaces.ask_evidence', run_name="__main__")
