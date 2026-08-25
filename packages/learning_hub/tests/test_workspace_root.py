from __future__ import annotations

from pathlib import Path

from system_learning.runtime.paths import default_system_root
from system_runtime.paths import WORKSPACE_MARKER


def test_default_system_root_ignores_retired_system_env(monkeypatch) -> None:
    monkeypatch.setenv("SYSTEM_ROOT", "/Users/a1/System")
    monkeypatch.delenv("SYSTEM_WORKSPACE_ROOT", raising=False)

    root = default_system_root()

    assert (root / WORKSPACE_MARKER).is_file()
    assert root.resolve() != Path("/Users/a1/System").resolve()
