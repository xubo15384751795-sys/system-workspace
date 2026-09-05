"""Tests for the legacy DuckDB snapshot store freeze guard.

Mirrors tests/test_phase_def.py::TestLegacyFreeze (F.1 DataHub freeze).
The guard blocks DuckDBSnapshotStore write methods once frozen, unless
ALLOW_LEGACY_DUCKDB=1 is set for migration testing.
"""

from __future__ import annotations

import pytest


class TestSnapshotStoreFreeze:
    """Legacy DuckDB snapshot store freeze mechanism."""

    def test_freeze_not_active_by_default(self):
        from src.data.snapshot_store_freeze import (
            check_legacy_allowed,
            is_frozen,
            unfreeze_legacy_snapshot_store,
        )

        unfreeze_legacy_snapshot_store()
        assert is_frozen() is False
        # Should not raise
        check_legacy_allowed("save")

    def test_freeze_blocks_when_active(self):
        from src.data.snapshot_store_freeze import (
            LegacySnapshotStoreFrozen,
            check_legacy_allowed,
            freeze_legacy_snapshot_store,
            is_frozen,
            unfreeze_legacy_snapshot_store,
        )

        freeze_legacy_snapshot_store()
        try:
            assert is_frozen() is True
            with pytest.raises(LegacySnapshotStoreFrozen, match="frozen"):
                check_legacy_allowed("save")
        finally:
            unfreeze_legacy_snapshot_store()

    def test_allow_legacy_env_var_bypasses_freeze(self, monkeypatch):
        from src.data.snapshot_store_freeze import (
            check_legacy_allowed,
            freeze_legacy_snapshot_store,
            is_frozen,
            unfreeze_legacy_snapshot_store,
        )

        monkeypatch.setenv("ALLOW_LEGACY_DUCKDB", "1")
        freeze_legacy_snapshot_store()
        try:
            assert is_frozen() is True
            # Should NOT raise because ALLOW_LEGACY_DUCKDB=1
            check_legacy_allowed("save")
        finally:
            unfreeze_legacy_snapshot_store()

    def test_unfreeze_restores_access(self):
        from src.data.snapshot_store_freeze import (
            check_legacy_allowed,
            freeze_legacy_snapshot_store,
            unfreeze_legacy_snapshot_store,
        )

        freeze_legacy_snapshot_store()
        unfreeze_legacy_snapshot_store()
        # Should not raise after unfreeze
        check_legacy_allowed("save")

    def test_guard_method_blocks_when_frozen(self):
        from src.data.snapshot_store_freeze import (
            LegacySnapshotStoreFrozen,
            freeze_legacy_snapshot_store,
            guard_method,
            unfreeze_legacy_snapshot_store,
        )

        @guard_method
        def fake_save(date_str: str) -> str:
            return f"saved {date_str}"

        freeze_legacy_snapshot_store()
        try:
            with pytest.raises(LegacySnapshotStoreFrozen, match="fake_save"):
                fake_save("2026-07-07")
        finally:
            unfreeze_legacy_snapshot_store()

    def test_guard_method_allows_when_unfrozen(self):
        from src.data.snapshot_store_freeze import (
            guard_method,
            unfreeze_legacy_snapshot_store,
        )

        unfreeze_legacy_snapshot_store()

        @guard_method
        def fake_save(date_str: str) -> str:
            return f"saved {date_str}"

        assert fake_save("2026-07-07") == "saved 2026-07-07"
