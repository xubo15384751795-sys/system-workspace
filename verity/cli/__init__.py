"""Canonical Verity command-line entrypoint.

The implementation lives in this package.  ``system_cli`` remains a thin
compatibility module for one release cycle so existing operator commands keep
working without making the legacy package the default entrypoint.
"""

from ._application import main

__all__ = ["main"]
