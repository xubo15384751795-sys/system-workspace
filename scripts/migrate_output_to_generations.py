"""Compatibility shim. Canonical implementation: verity.cli.migrate_output_to_generations."""
from __future__ import annotations

import sys
from importlib import import_module

_impl = import_module('verity.cli.migrate_output_to_generations')
if __name__ != "__main__":
    sys.modules[__name__] = _impl
else:
    import runpy
    runpy.run_module('verity.cli.migrate_output_to_generations', run_name="__main__")
