"""Fail-closed execution guard for the Deformation v1 evidence archive."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from scripts._runtime_io import surface_dir

ARCHIVE_ENV = "ALLOW_ARCHIVED_DEFORMATION_REPRODUCTION"
ARCHIVE_SRC = Path(__file__).resolve().parents[1] / "packages" / "framework_v1_archive" / "src"


def prepend_archive_src() -> None:
    """Let isolated archive entrypoints import their own implementation tree."""
    value = str(ARCHIVE_SRC)
    if ARCHIVE_SRC.is_dir() and value not in sys.path:
        sys.path.insert(0, value)



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
