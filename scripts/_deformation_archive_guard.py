"""Fail-closed execution guard for the Deformation v1 evidence archive."""
from __future__ import annotations

import os
from pathlib import Path

from scripts._runtime_io import ROOT

ARCHIVE_ENV = "ALLOW_ARCHIVED_DEFORMATION_REPRODUCTION"


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
    authoritative = (ROOT / "Output" / "current").resolve()
    if target == authoritative or authoritative in target.parents:
        raise SystemExit("Archived bridge reproduction cannot write authoritative Output/current.")
