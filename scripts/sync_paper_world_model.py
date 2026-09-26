"""Compatibility shim. Canonical implementation: harvester.operators.sync_paper_world_model."""
from __future__ import annotations

import sys
from importlib import import_module

_impl = import_module('harvester.operators.sync_paper_world_model')
if __name__ != "__main__":
    sys.modules[__name__] = _impl
else:
    import runpy
    runpy.run_module('harvester.operators.sync_paper_world_model', run_name="__main__")
