"""Full daily pipeline invocation for the Dagster ``daily_job`` op."""
from __future__ import annotations

import logging
import os
from typing import Sequence

logger = logging.getLogger(__name__)


def run_scheduled_daily(argv: Sequence[str] | None = None) -> None:
    """Run the full scheduled batch (bundle + sequence + publish).

    Invoked by Dagster ``daily_job``. Uses ``scripts.daily_run.run_daily`` so
    launchd → Dagster → pipeline is one authority path.
    """
    import sys
    from pathlib import Path

    # Prevent nested ``python -m orchestration.cli daily`` re-entry.
    os.environ["SYSTEM_INSIDE_DAGSTER_DAILY_JOB"] = "1"
    root = Path(__file__).resolve().parents[3]
    for extra in (str(root), str(root / "scripts"), str(root / "packages" / "orchestration")):
        if extra not in sys.path:
            sys.path.insert(0, extra)
    from scripts import daily_run as daily_run_mod

    args = daily_run_mod.parse_args(list(argv) if argv is not None else None)
    daily_run_mod.run_daily(args)
