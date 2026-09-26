"""Compatibility shim. Canonical implementation: workbench.caselab.migrate_caselab_embeddings_to_lancedb."""
from __future__ import annotations

import sys
from importlib import import_module

_impl = import_module('workbench.caselab.migrate_caselab_embeddings_to_lancedb')
if __name__ != "__main__":
    sys.modules[__name__] = _impl
else:
    import runpy
    runpy.run_module('workbench.caselab.migrate_caselab_embeddings_to_lancedb', run_name="__main__")
