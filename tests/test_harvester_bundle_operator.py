"""Operator-bound Harvester export tree checks (not merge-gate evidence)."""
from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.operator

ROOT = Path(__file__).resolve().parents[1]


def test_harvester_exports_exist() -> None:
    """Data/harvester/exports/ must exist on an initialized operator workspace."""
    exports = ROOT / "Data" / "harvester" / "exports"
    assert exports.exists(), "Data/harvester/exports/ missing - Harvester not configured"
