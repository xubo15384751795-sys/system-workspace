"""Harvester release retention reporting.

governance/data_retention_policy.yaml has declared
``harvester_exports.keep_last_n_daily: 7`` since 2026-06-17, but no check
evaluated it. Exports grew to 883MB across 146 directories while the policy's
own ``current_size_mb`` still read 205.

These tests cover the reporting only. The checker must never delete: releases
are finalized evidence and removing them is an operator decision.
"""
from __future__ import annotations

import pytest

from scripts import apply_data_retention_policy as mod


@pytest.fixture
def exports(tmp_path, monkeypatch):
    """A fake exports tree: 10 days, some with same-day retries."""
    root = tmp_path
    exports_dir = root / "Data" / "harvester" / "exports"
    exports_dir.mkdir(parents=True)
    for day in range(1, 11):
        # Days 3 and 7 got retried twice.
        revisions = 3 if day in (3, 7) else 1
        for rev in range(1, revisions + 1):
            d = exports_dir / f"2026-07-{day:02d}-r{rev}"
            d.mkdir()
            (d / "data.bin").write_bytes(b"x" * 1024)
    # Non-release entries must be ignored.
    (exports_dir / ".failures").mkdir()
    (exports_dir / "20260426T074656Z").mkdir()
    (exports_dir / "latest").symlink_to(exports_dir / "2026-07-10-r1")
    monkeypatch.setattr(mod, "ROOT", root)
    return exports_dir


def _by_status(findings):
    return {f["status"]: f for f in findings}


class TestHarvesterReleaseRetention:
    def test_counts_superseded_same_day_releases(self, exports):
        findings = mod._check_harvester_release_retention(
            {"harvester_exports": {"keep_last_n_daily": 7}}
        )
        # Days 3 and 7 have r1,r2,r3 → r1 and r2 superseded on each.
        assert _by_status(findings)["superseded_same_day_releases"]["count"] == "4"

    def test_counts_days_outside_the_window(self, exports):
        findings = mod._check_harvester_release_retention(
            {"harvester_exports": {"keep_last_n_daily": 7}}
        )
        outside = _by_status(findings)["outside_keep_last_n_daily"]
        # 10 days present, keep the last 7 → days 1-3 fall outside.
        assert outside["days"] == "3"
        # Day 3 has three revisions, days 1 and 2 have one each.
        assert outside["count"] == "5"

    def test_ignores_non_release_directories(self, exports):
        """`.failures`, the legacy timestamp dir, and the `latest` symlink are
        not releases; counting them would overstate what is reclaimable."""
        findings = mod._check_harvester_release_retention(
            {"harvester_exports": {"keep_last_n_daily": 7}}
        )
        total = sum(int(f["count"]) for f in findings)
        assert total == 9  # 4 superseded + 5 outside, nothing else

    def test_clean_when_within_budget(self, tmp_path, monkeypatch):
        exports_dir = tmp_path / "Data" / "harvester" / "exports"
        exports_dir.mkdir(parents=True)
        for day in (1, 2):
            (exports_dir / f"2026-07-{day:02d}-r1").mkdir()
        monkeypatch.setattr(mod, "ROOT", tmp_path)
        findings = mod._check_harvester_release_retention(
            {"harvester_exports": {"keep_last_n_daily": 7}}
        )
        assert findings == []

    def test_no_rule_declared_is_a_no_op(self, exports):
        assert mod._check_harvester_release_retention({"harvester_exports": {}}) == []

    def test_check_never_deletes(self, exports):
        """Reporting only. Releases are finalized evidence."""
        before = sorted(p.name for p in exports.iterdir())
        mod._check_harvester_release_retention(
            {"harvester_exports": {"keep_last_n_daily": 7}}
        )
        assert sorted(p.name for p in exports.iterdir()) == before

    def test_wired_into_the_check_run(self):
        """A check that is not registered reports nothing — which is how the
        rule went unevaluated for six weeks."""
        assert "harvester_release_retention" in mod.run_retention_check()["checks"]
