"""Compatibility wrapper for the canonical Workbench methodology runner."""
from __future__ import annotations

from workbench.measurement.professional_methodology import *  # noqa: F401,F403

if __name__ == "__main__":
    from workbench.measurement.professional_methodology import main

    main()
