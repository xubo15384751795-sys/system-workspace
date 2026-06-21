"""Verify check_output_freshness detects stale artifacts."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from check_output_freshness import (
    check_artifact_freshness,
    check_symlink_freshness,
    get_freshness_rules,
)


def test_get_freshness_rules():
    """Extracts max_age_hours from constitution."""
    constitution = {
        "freshness_rules": {
            "max_age_hours": {
                "readme": 24,
                "framework_output": 48,
            }
        }
    }
    rules = get_freshness_rules(constitution)
    assert rules["readme"] == 24
    assert rules["framework_output"] == 48


def test_get_freshness_rules_empty():
    """Returns empty dict when no freshness rules."""
    assert get_freshness_rules({}) == {}


def test_artifact_fresh(tmp_path):
    """No finding when artifact is within freshness window."""
    p = tmp_path / "artifact.json"
    p.write_text('{"status": "ok"}')
    now = time.time()
    result = check_artifact_freshness(p, 48, now)
    assert result is None


def test_artifact_stale(tmp_path):
    """Finding reported when artifact exceeds freshness window."""
    p = tmp_path / "artifact.json"
    p.write_text('{"status": "ok"}')
    # Set mtime to 100 hours ago
    old_time = time.time() - (100 * 3600)
    os.utime(p, (old_time, old_time))
    result = check_artifact_freshness(p, 48, time.time())
    assert result is not None
    assert result["status"] == "STALE"
    assert result["age_hours"] > 99


def test_symlink_fresh(tmp_path):
    """No finding when symlink target is fresh."""
    target = tmp_path / "target.json"
    target.write_text('{"status": "ok"}')
    link = tmp_path / "link.json"
    os.symlink(target, link)
    result = check_symlink_freshness(link, 48, time.time())
    assert result is None


def test_symlink_broken(tmp_path):
    """Finding reported for broken symlink."""
    link = tmp_path / "broken.link"
    os.symlink("/nonexistent/path", link)
    result = check_symlink_freshness(link, 48, time.time())
    assert result is not None
    assert result["status"] == "BROKEN_SYMLINK"


def test_artifact_exactly_at_boundary(tmp_path):
    """Artifact exactly at max_age boundary should be considered fresh."""
    p = tmp_path / "artifact.json"
    p.write_text('{"status": "ok"}')
    # Set mtime to exactly 48 hours ago
    boundary_time = time.time() - (48 * 3600)
    os.utime(p, (boundary_time, boundary_time))
    # Check with now = time.time() — age will be slightly > 48 due to execution time
    # So we pass a "now" that's 1 second after the mtime + 48h
    now = boundary_time + (48 * 3600) + 1
    result = check_artifact_freshness(p, 48, now)
    # At exactly 48h + 1s, it should be stale
    assert result is not None
    assert result["status"] == "STALE"


def test_artifact_just_within_window(tmp_path):
    """Artifact just within freshness window should be fresh."""
    p = tmp_path / "artifact.json"
    p.write_text('{"status": "ok"}')
    # Set mtime to 47 hours ago
    recent_time = time.time() - (47 * 3600)
    os.utime(p, (recent_time, recent_time))
    result = check_artifact_freshness(p, 48, time.time())
    assert result is None


def test_missing_artifact(tmp_path):
    """Non-existent artifact returns finding."""
    p = tmp_path / "nonexistent.json"
    result = check_artifact_freshness(p, 48, time.time())
    assert result is not None
    assert result["status"] == "MISSING"
