"""Resolve repository root for Streamlit entrypoints (app + multipage scripts)."""

from __future__ import annotations

from pathlib import Path


def repo_root(here: Path) -> Path:
    here = here.resolve()
    if here.parent.name == "pages":
        return here.parents[3]
    return here.parents[2]
