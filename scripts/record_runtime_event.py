"""Compatibility shim. Canonical implementation: verity.runtime.record_runtime_event."""
from __future__ import annotations

import sys
from importlib import import_module

_impl = import_module('verity.runtime.record_runtime_event')
if __name__ != "__main__":
    sys.modules[__name__] = _impl
else:
    import runpy
    runpy.run_module('verity.runtime.record_runtime_event', run_name="__main__")
