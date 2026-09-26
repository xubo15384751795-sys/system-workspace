"""Shared Paper vault path.

The vault is an external, optional input. Its location is supplied by
``PAPER_ROOT`` or discovered as a sibling checkout; the runtime never embeds an
operator's home-directory path.
"""
from __future__ import annotations

import os
from pathlib import Path

from system_runtime.paths import WorkspacePaths


def paper_root() -> Path:
    configured = os.environ.get("PAPER_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    try:
        workspace = WorkspacePaths.discover().root
    except RuntimeError:
        workspace = Path.cwd().resolve()
    return (workspace.parent / "Paper").resolve()
