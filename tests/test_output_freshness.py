"""Verify check_output_freshness detects stale artifacts."""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import patch

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


def test_artifact_fresh():
    """No finding when artifact is within freshness window."""
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        f.write(b'{"status": "ok"}')
        f.flush()
        now = time.time()
        result = check_artifact_freshness(Path(f.name), 48, now)
    Path(f.name).unlink()
    assert result is None


def test_artifact_stale():
    """Finding reported when artifact exceeds freshness window."""
    import os
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        f.write(b'{"status": "ok"}')
        f.flush()
        filepath = Path(f.name)
        # Set mtime to 100 hours ago
        old_time = time.time() - (100 * 3600)
        os.utime(filepath, (old_time, old_time))
        result = check_artifact_freshness(filepath, 48, time.time())
    filepath.unlink()
    assert result is not None
    assert result["status"] == "STALE"
    assert result["age_hours"] > 99


def test_symlink_fresh():
    """No finding when symlink target is fresh."""
    import tempfile
    import os
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as target_f:
        target_f.write(b'{"status": "ok"}')
        target_f.flush()
        target_path = Path(target_f.name)
        link_path = target_path.with_suffix(".link")
        os.symlink(target_path, link_path)
        result = check_symlink_freshness(link_path, 48, time.time())
    link_path.unlink()
    target_path.unlink()
    assert result is None


def test_symlink_broken():
    """Finding reported for broken symlink."""
    import tempfile
    import os
    link_path = Path(tempfile.mktemp(suffix=".link"))
    os.symlink("/nonexistent/path", link_path)
    result = check_symlink_freshness(link_path, 48, time.time())
    link_path.unlink(missing_ok=True)
    assert result is not None
    assert result["status"] == "BROKEN_SYMLINK"
