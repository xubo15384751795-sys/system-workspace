"""Compatibility wrapper for the canonical Workbench judgment replay."""
from __future__ import annotations

from workbench.judgment.backward_pass import *  # noqa: F401,F403

if __name__ == "__main__":
    from workbench.judgment.backward_pass import main

    main()
