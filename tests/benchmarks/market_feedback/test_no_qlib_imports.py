"""Test: main system source must not import qlib."""

import re
from pathlib import Path

import pytest
pytestmark = pytest.mark.benchmark


MAIN_SRC = Path("Workbench/src")
QLIB_IMPORT_RE = re.compile(r'^\s*(import\s+qlib\b|from\s+qlib\b)', re.MULTILINE)


def test_main_src_does_not_import_qlib():
    if not MAIN_SRC.exists():
        pytest.skip("Workbench/src not found")

    offenders = []
    for path in MAIN_SRC.rglob("*.py"):
        try:
            text = path.read_text(encoding="utf-8")
            if QLIB_IMPORT_RE.search(text):
                offenders.append(str(path))
        except Exception:
            pass

    assert not offenders, (
        f"Main system must not import qlib. Found in: {offenders}"
    )
