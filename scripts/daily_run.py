"""Compatibility shim. Canonical implementation: verity.cli.daily_run."""
from __future__ import annotations

import sys
from importlib import import_module

_impl = import_module('verity.cli.daily_run')
if __name__ != "__main__":
    sys.modules[__name__] = _impl
else:
    import runpy
    runpy.run_module('verity.cli.daily_run', run_name="__main__")
