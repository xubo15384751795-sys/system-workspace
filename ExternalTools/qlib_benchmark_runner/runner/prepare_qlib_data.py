"""Prepare Qlib-compatible data from sandbox input.

Converts exported parquet/JSON files into Qlib's expected directory layout.
"""

from __future__ import annotations

from pathlib import Path


def prepare_qlib_data(input_dir: Path, workspace_dir: Path) -> Path:
    """Set up Qlib data directory from sandbox input files."""
    qlib_data_dir = workspace_dir / "qlib_data"
    qlib_data_dir.mkdir(parents=True, exist_ok=True)

    # Qlib expects: qlib_data/
    #   features/  (daily parquet dirs)
    #   calendars/ (calendar files)
    #   instruments/ (instrument list)

    (qlib_data_dir / "features").mkdir(exist_ok=True)
    (qlib_data_dir / "calendars").mkdir(exist_ok=True)
    (qlib_data_dir / "instruments").mkdir(exist_ok=True)

    return qlib_data_dir
