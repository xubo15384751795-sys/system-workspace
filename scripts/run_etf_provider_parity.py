"""Compatibility shim. Canonical implementation: harvester.operators.run_etf_provider_parity."""
from __future__ import annotations

import sys
from importlib import import_module

_impl = import_module('harvester.operators.run_etf_provider_parity')
if __name__ != "__main__":
    sys.modules[__name__] = _impl
else:
    import runpy
    runpy.run_module('harvester.operators.run_etf_provider_parity', run_name="__main__")
