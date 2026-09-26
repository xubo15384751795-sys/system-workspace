"""Compatibility shim. Canonical implementation: workbench.surfaces.build_artifact_navigator."""
from __future__ import annotations

import sys
from importlib import import_module

_impl = import_module('workbench.surfaces.build_artifact_navigator')
if __name__ != "__main__":
    sys.modules[__name__] = _impl
else:
    import runpy
    runpy.run_module('workbench.surfaces.build_artifact_navigator', run_name="__main__")
