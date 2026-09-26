"""Compatibility shim. Canonical implementation: verity.runtime.run_bundle."""
from __future__ import annotations

import sys
from importlib import import_module

_impl = import_module('verity.runtime.run_bundle')
if __name__ != "__main__":
    sys.modules[__name__] = _impl
else:
    import runpy
    runpy.run_module('verity.runtime.run_bundle', run_name="__main__")
