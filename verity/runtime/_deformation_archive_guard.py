"""Fail-closed execution guard for the Deformation v1 evidence archive."""
from __future__ import annotations

import os
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from system_runtime.paths import discover_workspace
from verity.runtime.runtime_io import surface_dir

ARCHIVE_ENV = "ALLOW_ARCHIVED_DEFORMATION_REPRODUCTION"
ARCHIVE_SRC = discover_workspace() / "packages" / "framework_v1_archive" / "src"


def prepend_archive_src() -> None:
    """Load the archived ``src`` namespace without mutating ``sys.path``.

    The archive is an explicitly isolated evidence surface.  Its historical
    modules still import each other as ``src.*``; registering a package spec is
    sufficient for that namespace and keeps the live interpreter import path
    immutable.
    """
    if "src" in sys.modules or not ARCHIVE_SRC.is_dir():
        return
    init_file = ARCHIVE_SRC / "__init__.py"
    spec = spec_from_file_location(
        "src",
        init_file,
        submodule_search_locations=[str(ARCHIVE_SRC)],
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load archived namespace from {init_file}")
    module = module_from_spec(spec)
    sys.modules["src"] = module
    spec.loader.exec_module(module)



def require_archived_reproduction(*, current_writer: bool = False) -> None:
    """Permit explicit evidence reproduction but deny operational execution."""
    if os.environ.get(ARCHIVE_ENV) != "1":
        raise SystemExit(
            "Deformation v1 is ARCHIVED_FALSIFIED and cannot execute. "
            f"Set {ARCHIVE_ENV}=1 only for isolated evidence reproduction."
        )
    if os.environ.get("ZCODE_BUNDLE_RUN_ID"):
        raise SystemExit("Archived Deformation reproduction is forbidden inside a daily run bundle.")
    if not current_writer:
        return
    override = os.environ.get("CURRENT_OUTPUT_DIR")
    if not override:
        raise SystemExit("Archived bridge reproduction requires an isolated CURRENT_OUTPUT_DIR.")
    target = Path(override).resolve()
    authoritative = surface_dir("current").resolve()
    if target == authoritative or authoritative in target.parents:
        raise SystemExit("Archived bridge reproduction cannot write authoritative Output/current.")
