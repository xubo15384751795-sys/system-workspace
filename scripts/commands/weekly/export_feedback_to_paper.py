"""Compatibility shim. Canonical implementation: workbench.caselab.export_feedback_to_paper."""
from __future__ import annotations

import sys
from importlib import import_module

_impl = import_module('workbench.caselab.export_feedback_to_paper')
if __name__ != "__main__":
    sys.modules[__name__] = _impl
else:
    import runpy
    runpy.run_module('workbench.caselab.export_feedback_to_paper', run_name="__main__")
