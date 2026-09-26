"""Compatibility wrapper for the canonical Workbench judgment replay audit."""
from __future__ import annotations

from workbench.judgment.replay import *  # noqa: F401,F403

if __name__ == "__main__":
    from workbench.judgment.replay import main

    main()
