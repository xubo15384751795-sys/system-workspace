"""Compatibility shim. Canonical implementation: workbench.caselab.sync_caselab_index."""
from __future__ import annotations

import sys
from importlib import import_module

_impl = import_module('workbench.caselab.sync_caselab_index')
if __name__ != "__main__":
    sys.modules[__name__] = _impl
else:
    import runpy
    runpy.run_module('workbench.caselab.sync_caselab_index', run_name="__main__")
