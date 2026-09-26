"""Compatibility shim. Canonical file: packages/framework_v1_archive/scripts/build_overlay_shadow_report.py."""
from __future__ import annotations

import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_CANON = Path(__file__).resolve().parents[2] / 'packages/framework_v1_archive/scripts/build_overlay_shadow_report.py'
_NAME = '_canon.packages.framework_v1_archive.scripts.build_overlay_shadow_report'
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
