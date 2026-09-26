"""Compatibility alias for :mod:`verity.cli`.

The root ``verity`` command owns the canonical CLI implementation.  This
module remains importable for the current compatibility release and forwards
both the public parser and entrypoint without introducing a second CLI.
"""
from __future__ import annotations

from verity.cli import _application as _canonical

build_parser = _canonical.build_parser
main = _canonical.main


def __getattr__(name: str):
    """Preserve legacy access to non-public helpers during the alias window."""
    return getattr(_canonical, name)


if __name__ == "__main__":
    raise SystemExit(main())
