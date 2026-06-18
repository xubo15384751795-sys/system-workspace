"""Verify check_retire_after detects expired entrypoints."""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from check_retire_after import check_retire_after


def test_no_violations_when_all_future():
    """No violations when all retire_after dates are in the future."""
    future = str(date.today() + timedelta(days=365))
    mock_registry = {
        "test_entry": {
            "status": "active",
            "retire_after": future,
            "script": "scripts/test.py",
        }
    }
    with patch("check_retire_after.load_yaml", return_value=mock_registry):
        assert check_retire_after() == []


def test_violation_when_past_date():
    """Violation reported when retire_after is in the past."""
    past = "2020-01-01"
    mock_registry = {
        "old_entry": {
            "status": "active",
            "retire_after": past,
            "script": "scripts/old.py",
        }
    }
    with patch("check_retire_after.load_yaml", return_value=mock_registry):
        violations = check_retire_after()
        assert len(violations) == 1
        assert violations[0]["entrypoint"] == "old_entry"
        assert violations[0]["retire_after"] == past


def test_no_violation_when_no_retire_after():
    """No violation when entry has no retire_after field."""
    mock_registry = {
        "no_retire": {
            "status": "active",
            "script": "scripts/test.py",
        }
    }
    with patch("check_retire_after.load_yaml", return_value=mock_registry):
        assert check_retire_after() == []


def test_no_violation_when_none_registry():
    """No violation when registry is None (file missing)."""
    with patch("check_retire_after.load_yaml", return_value=None):
        assert check_retire_after() == []
