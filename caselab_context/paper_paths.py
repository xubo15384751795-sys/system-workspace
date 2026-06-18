"""Shared Paper vault path — use PAPER_ROOT env or default sibling checkout."""
from __future__ import annotations

import os
from pathlib import Path

_DEFAULT = "/Users/a1/Paper"


def paper_root() -> Path:
    return Path(os.environ.get("PAPER_ROOT", _DEFAULT)).expanduser().resolve()
