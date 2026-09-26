"""Compatibility shim. Canonical implementation: workbench.judgment.backfill_judgment_calibration."""
from __future__ import annotations

import sys
from importlib import import_module

_impl = import_module('workbench.judgment.backfill_judgment_calibration')
if __name__ != "__main__":
    sys.modules[__name__] = _impl
else:
    import runpy
    runpy.run_module('workbench.judgment.backfill_judgment_calibration', run_name="__main__")
