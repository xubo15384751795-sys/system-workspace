"""Compatibility shim. Canonical implementation: workbench.judgment.trade_decision_replay."""
from __future__ import annotations

import sys
from importlib import import_module

_impl = import_module('workbench.judgment.trade_decision_replay')
if __name__ != "__main__":
    sys.modules[__name__] = _impl
else:
    import runpy
    runpy.run_module('workbench.judgment.trade_decision_replay', run_name="__main__")
