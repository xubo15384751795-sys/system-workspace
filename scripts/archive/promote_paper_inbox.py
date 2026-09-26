"""Compatibility shim. Canonical implementation: workbench.caselab.promote_paper_inbox."""
from __future__ import annotations

import sys
from importlib import import_module

_impl = import_module('workbench.caselab.promote_paper_inbox')
if __name__ != "__main__":
    sys.modules[__name__] = _impl
else:
    import runpy
    runpy.run_module('workbench.caselab.promote_paper_inbox', run_name="__main__")
