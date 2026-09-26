"""Compatibility shim. Canonical implementation: verity.cli.run_work_cycle."""
from __future__ import annotations

import sys
from importlib import import_module

_impl = import_module('verity.cli.run_work_cycle')
if __name__ != "__main__":
    sys.modules[__name__] = _impl
else:
    import runpy
    runpy.run_module('verity.cli.run_work_cycle', run_name="__main__")
