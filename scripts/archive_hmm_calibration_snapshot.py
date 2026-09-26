"""Compatibility shim. Canonical implementation: workbench.measurement.archive_hmm_calibration_snapshot."""
from __future__ import annotations

import sys
from importlib import import_module

_impl = import_module('workbench.measurement.archive_hmm_calibration_snapshot')
if __name__ != "__main__":
    sys.modules[__name__] = _impl
else:
    import runpy
    runpy.run_module('workbench.measurement.archive_hmm_calibration_snapshot', run_name="__main__")
