"""Operator-workspace checks for the live current readout.

These checks intentionally inspect generated Data/Output state. They are not
clean-checkout merge evidence and are listed in STATEFUL_ROOT_TESTS.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_output_freshness import (
    _missing_required_artifacts,
    run_freshness_check,
)

ROOT = Path(__file__).resolve().parents[1]
CURRENT = ROOT / "Output" / "current"


def _require_live_current() -> None:
    if not CURRENT.is_dir():
        pytest.skip("operator Output/current is not initialized")


def test_operator_required_readout_chain_exists() -> None:
    _require_live_current()
    assert _missing_required_artifacts(ROOT) == []


def test_operator_readme_has_no_na_placeholders() -> None:
    _require_live_current()
    readme = CURRENT / "00_READ_ME_FIRST.md"
    assert readme.is_file()
    na_lines = [
        line.strip()
        for line in readme.read_text(encoding="utf-8").splitlines()
        if "N/A" in line and not line.strip().startswith("#")
    ]
    assert not na_lines, "live READ_ME_FIRST contains N/A:\n" + "\n".join(na_lines[:5])


def test_operator_current_readout_is_fresh() -> None:
    _require_live_current()
    findings = run_freshness_check(ROOT)
    assert findings == []
