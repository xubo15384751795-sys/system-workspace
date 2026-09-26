"""Compatibility shim. Canonical implementation: harvester.operators.validate_proxy_observation_catalog."""
from __future__ import annotations

import sys
from importlib import import_module

_impl = import_module('harvester.operators.validate_proxy_observation_catalog')
if __name__ != "__main__":
    sys.modules[__name__] = _impl
else:
    import runpy
    runpy.run_module('harvester.operators.validate_proxy_observation_catalog', run_name="__main__")
