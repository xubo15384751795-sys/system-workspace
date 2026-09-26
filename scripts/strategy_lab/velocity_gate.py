"""Compatibility shim. Canonical file: packages/workbench/src/strategy_lab/velocity_gate.py."""
from __future__ import annotations

import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_CANON = Path(__file__).resolve().parents[2] / 'packages/workbench/src/strategy_lab/velocity_gate.py'
_NAME = '_canon.packages.workbench.src.strategy_lab.velocity_gate'
if _NAME in sys.modules:
    _impl = sys.modules[_NAME]
else:
    _spec = spec_from_file_location(_NAME, _CANON)
    _impl = module_from_spec(_spec)
    sys.modules[_NAME] = _impl
    assert _spec.loader is not None
    _spec.loader.exec_module(_impl)
if __name__ != "__main__":
    sys.modules[__name__] = _impl
else:
    import runpy
    runpy.run_path(str(_CANON), run_name="__main__")
