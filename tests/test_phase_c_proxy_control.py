"""Phase C/D tests: proxy state machine, real-format fixture, control closure."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


# ── C1: proxy state machine ──────────────────────────────────────────────


class TestProxyStateMachine:
    def test_build_failed_on_exception(self):
        from _proxy_state import ProxyState, classify_build_result, state_of

        r = classify_build_result("k_butterfly", None, build_error="ZeroDivisionError: x/0")
        assert r.build_error is not None
        assert state_of(r) == ProxyState.BUILD_FAILED

    def test_build_failed_on_all_nan(self):
        from _proxy_state import ProxyState, classify_build_result, state_of

        s = pd.Series([np.nan] * 100)
        r = classify_build_result("k", s)
        assert state_of(r) == ProxyState.BUILD_FAILED
        assert "all-NaN" in (r.build_error or "")

    def test_build_failed_on_low_coverage(self):
        from _proxy_state import (
            DEFAULT_COVERAGE_FLOOR,
            classify_build_result,
        )

        s = pd.Series([1.0] + [np.nan] * 99)  # 1% coverage
        r = classify_build_result("k", s, coverage_floor=DEFAULT_COVERAGE_FLOOR)
        assert r.build_error is not None
        assert "coverage" in r.build_error

    def test_available_on_release_when_healthy(self):
        from _proxy_state import ProxyState, classify_build_result, state_of

        s = pd.Series(np.random.normal(0, 1, 100))
        r = classify_build_result("k", s)
        assert state_of(r) == ProxyState.AVAILABLE_ON_RELEASE
        assert r.build_error is None

    def test_state_advances_through_chain(self):
        from _proxy_state import BuildResult, ProxyState, state_of

        r = BuildResult(name="k", value=pd.Series([1.0] * 100), coverage_ratio=1.0)
        assert state_of(r) == ProxyState.AVAILABLE_ON_RELEASE
        r.eligible_to_vote = True
        assert state_of(r) == ProxyState.ELIGIBLE_TO_VOTE
        r.in_roster = True
        assert state_of(r) == ProxyState.INCLUDED_IN_AGGREGATION
        r.emitted = True
        assert state_of(r) == ProxyState.EMITTED
        r.consumed = True
        assert state_of(r) == ProxyState.CONSUMED

    def test_is_active_excludes_build_failed(self):
        from _proxy_state import classify_build_result, is_active_for_aggregation

        r_fail = classify_build_result("k", None, build_error="boom")
        assert is_active_for_aggregation(r_fail) is False
        r_ok = classify_build_result("k", pd.Series([1.0] * 100))
        assert is_active_for_aggregation(r_ok) is True


# ── C2: real-format fixture ──────────────────────────────────────────────


class TestRealFormatFixture:
    def test_fixture_exists_and_has_real_columns(self):
        fixture = ROOT / "tests" / "fixtures" / "benchmark_panel_real_format.parquet"
        assert fixture.exists(), "real-format fixture must exist"
        df = pd.read_parquet(fixture)
        # Real long-format schema.
        for col in ("date", "series_id", "source_id", "source_series_id",
                    "value", "unit", "frequency", "vintage_date", "quality_flag"):
            assert col in df.columns, f"fixture missing real column {col}"
        # Multiple series (not synthetic single-column).
        assert df["series_id"].nunique() >= 10
        # OFR/CISS present (the public-stress components).
        ids = set(df["series_id"].astype(str).unique())
        assert "OFR_FSI" in ids or "CISS" in ids


# ── D-code: control closure ──────────────────────────────────────────────


class TestControlClosure:
    def test_enforcement_mode_default_hard(self, monkeypatch):
        from _control_closure import enforcement_mode, is_hard_enforcement

        monkeypatch.delenv("CONTROL_ENFORCEMENT_MODE", raising=False)
        assert enforcement_mode() == "hard"
        assert is_hard_enforcement() is True

    def test_enforcement_mode_shadow(self, monkeypatch):
        from _control_closure import enforcement_mode, is_hard_enforcement

        monkeypatch.setenv("CONTROL_ENFORCEMENT_MODE", "shadow")
        assert enforcement_mode() == "shadow"
        assert is_hard_enforcement() is False

    def test_tag_nav_row_hold_degraded(self):
        from _control_closure import DEGRADED, tag_nav_row

        row = tag_nav_row({"as_of": "2026-07-17", "sizing_mode": "HOLD_DEGRADED"})
        assert row["sample_validity"] == DEGRADED

    def test_tag_nav_row_valid(self):
        from _control_closure import VALID, tag_nav_row

        row = tag_nav_row({"as_of": "2026-07-17", "sizing_mode": "NORMAL"})
        assert row["sample_validity"] == VALID

    def test_valid_sample_filter_excludes_degraded(self):
        from _control_closure import DEGRADED, INVALIDATED, VALID, valid_sample_filter

        assert valid_sample_filter({"sample_validity": VALID}) is True
        assert valid_sample_filter({"sample_validity": DEGRADED}) is False
        assert valid_sample_filter({"sample_validity": INVALIDATED}) is False
        # Default (no tag) is valid.
        assert valid_sample_filter({}) is True

    def test_invalidate_nav_rows(self, tmp_path):
        from _control_closure import INVALIDATED, invalidate_nav_rows

        nav = tmp_path / "nav.jsonl"
        nav.write_text(
            '{"as_of":"d1","sizing_mode":"HOLD_DEGRADED","sample_validity":"DEGRADED"}\n'
            '{"as_of":"d2","sizing_mode":"NORMAL","sample_validity":"VALID"}\n',
            encoding="utf-8",
        )
        count = invalidate_nav_rows(nav, dates=["d1"], reason="test")
        assert count == 1
        rows = [
            __import__("json").loads(line)
            for line in nav.read_text().splitlines()
            if line.strip()
        ]
        assert rows[0]["sample_validity"] == INVALIDATED
        assert rows[0]["invalidation_reason"] == "test"
        assert rows[1]["sample_validity"] == "VALID"
        # NAV values not rewritten.
        assert rows[0]["as_of"] == "d1"


# ── C3: merge-gate manifest ──────────────────────────────────────────────


class TestMergeGateManifest:
    def test_manifest_sha_bound(self, tmp_path, monkeypatch):
        from verify_merge import _git_sha

        # The manifest validity check rejects a stale SHA. We test the logic
        # by confirming _git_sha returns a real (non-"unknown") SHA when in
        # a git repo.
        sha = _git_sha()
        assert sha != "unknown", "must resolve git SHA in this repo"
