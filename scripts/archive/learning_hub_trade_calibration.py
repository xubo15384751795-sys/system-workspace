"""Compatibility shim. Canonical implementation: system_learning.operators.learning_hub_trade_calibration."""
from __future__ import annotations

import sys
from importlib import import_module

_impl = import_module('system_learning.operators.learning_hub_trade_calibration')
if __name__ != "__main__":
    sys.modules[__name__] = _impl
else:
    import runpy
    runpy.run_module('system_learning.operators.learning_hub_trade_calibration', run_name="__main__")
