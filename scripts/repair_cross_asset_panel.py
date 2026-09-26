"""Compatibility shim. Canonical implementation: harvester.operators.repair_cross_asset_panel."""
from __future__ import annotations

import sys
from importlib import import_module

_impl = import_module('harvester.operators.repair_cross_asset_panel')
if __name__ != "__main__":
    sys.modules[__name__] = _impl
else:
    import runpy
    runpy.run_module('harvester.operators.repair_cross_asset_panel', run_name="__main__")
