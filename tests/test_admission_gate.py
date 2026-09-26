"""Phase A step 5: admission gate tests.

Verifies admit_for_consumption aggregates release-level (workbench.freshness)
and content-level (check_content_freshness) blockers, and that
require_admission exits non-zero when blocked.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "packages" / "workbench" / "src"))

from verity.runtime._admission_gate import (  # noqa: E402
    admit_for_consumption,
    require_admission,
)


@pytest.fixture
def no_declared_blocks(monkeypatch):
    """Evaluate the general blocking rules with no environmentally-blocked
    sources declared, so these tests do not silently change meaning when
    configs/freshness_policy.yaml declares one."""
    monkeypatch.setattr("verity.runtime._admission_gate._environmentally_blocked", dict)


def _write_release(release: Path, *, ofr=True, nfci=True, ciss=True,
                   as_of="2026-07-17", ofr_stale=False, nfci_stale=False):
    """Build a release with controllable public-component freshness."""
    data_dir = release / "data"
    data_dir.mkdir(parents=True)
    rows = [
        {"date": pd.Timestamp("2026-07-16"), "series_id": "VIXCLS",
         "source_id": "fred", "source_series_id": "VIXCLS", "value": 20.0,
         "unit": "index", "frequency": "daily",
         "vintage_date": pd.Timestamp(as_of), "quality_flag": "observed"},
        {"date": pd.Timestamp("2026-07-16"), "series_id": "BAMLH0A0HYM2",
         "source_id": "fred", "source_series_id": "BAMLH0A0HYM2", "value": 5.0,
         "unit": "pct", "frequency": "daily",
         "vintage_date": pd.Timestamp(as_of), "quality_flag": "observed"},
    ]
    if ofr:
        rows.append({"date": pd.Timestamp("2026-05-01" if ofr_stale else "2026-07-16"),
                     "series_id": "OFR_FSI", "source_id": "ofr",
                     "source_series_id": "OFR_FSI", "value": 0.3, "unit": "index",
                     "frequency": "daily", "vintage_date": pd.Timestamp(as_of),
                     "quality_flag": "observed"})
    if nfci:
        # weekly, acceptable_lag 21d. stale => >21d behind.
        rows.append({"date": pd.Timestamp("2026-05-01" if nfci_stale else "2026-07-12"),
                     "series_id": "NFCI", "source_id": "fred_chicago_fed",
                     "source_series_id": "NFCI", "value": -0.4, "unit": "index",
                     "frequency": "weekly", "vintage_date": pd.Timestamp(as_of),
                     "quality_flag": "observed"})
    if ciss:
        rows.append({"date": pd.Timestamp("2026-07-16"), "series_id": "CISS",
                     "source_id": "ecb", "source_series_id": "CISS", "value": 0.2,
                     "unit": "index", "frequency": "daily",
                     "vintage_date": pd.Timestamp(as_of), "quality_flag": "observed"})
    pd.DataFrame(rows).to_parquet(data_dir / "benchmark_panel.parquet")
    (release / "catalog.json").write_text(
        __import__("json").dumps({
            "bundle_id": release.name,
            "created_at": "2026-07-17T00:00:00Z",
            "files": [{"role": "benchmark_panel", "path": "data/benchmark_panel.parquet"}],
        }),
        encoding="utf-8",
    )


class TestAdmitForConsumption:
    def test_missing_ofr_blocks(self, tmp_path, monkeypatch, no_declared_blocks):
        release = tmp_path / "release"
        _write_release(release, ofr=False)
        monkeypatch.setattr(
            "verity.runtime._admission_gate._content_level_blockers",
            lambda now: ([], []),
        )
        decision = admit_for_consumption("paper_portfolio", release_dir=release,
                                          now=pd.Timestamp("2026-07-17"))
        assert decision.allowed is False
        assert any("OFR_FSI" in b for b in decision.blockers)

    def test_stale_nfci_blocks(self, tmp_path, monkeypatch):
        release = tmp_path / "release"
        _write_release(release, nfci_stale=True)
        monkeypatch.setattr(
            "verity.runtime._admission_gate._content_level_blockers",
            lambda now: ([], []),
        )
        decision = admit_for_consumption("paper_portfolio", release_dir=release,
                                          now=pd.Timestamp("2026-07-17"))
        assert decision.allowed is False
        assert any("NFCI" in b for b in decision.blockers)

    def test_all_fresh_allowed(self, tmp_path, monkeypatch):
        release = tmp_path / "release"
        _write_release(release)
        # Stub content checks — they read operator Data/ which is absent in CI.
        monkeypatch.setattr(
            "verity.runtime._admission_gate._content_level_blockers",
            lambda now: ([], []),
        )
        decision = admit_for_consumption("paper_portfolio", release_dir=release,
                                          now=pd.Timestamp("2026-07-17"))
        assert decision.allowed is True, f"expected allowed, blockers={decision.blockers}"

    def test_content_stale_ciss_blocks(self, tmp_path, monkeypatch):
        """A stale CISS content cache is a blocker even if the release is fine."""
        release = tmp_path / "release"
        _write_release(release)

        def fake_content(now):
            return (["ciss_cache:stale (behind=69d)"],
                    [{"name": "ciss_cache", "status": "STALE", "trading_days_behind": 69}])
        monkeypatch.setattr("verity.runtime._admission_gate._content_level_blockers", fake_content)
        decision = admit_for_consumption("paper_portfolio", release_dir=release,
                                          now=pd.Timestamp("2026-07-17"))
        assert decision.allowed is False
        assert any("ciss" in b.lower() for b in decision.blockers)


class TestRequireAdmission:
    def test_blocks_exit_nonzero(self, tmp_path, monkeypatch, no_declared_blocks):
        release = tmp_path / "release"
        _write_release(release, ofr=False)
        monkeypatch.setattr(
            "verity.runtime._admission_gate._content_level_blockers",
            lambda now: ([], []),
        )
        with pytest.raises(SystemExit) as exc:
            require_admission("paper_portfolio", release_dir=release,
                              now=pd.Timestamp("2026-07-17"))
        assert exc.value.code == 1

    def test_allows_proceeds(self, tmp_path, monkeypatch):
        release = tmp_path / "release"
        _write_release(release)
        monkeypatch.setattr(
            "verity.runtime._admission_gate._content_level_blockers",
            lambda now: ([], []),
        )
        decision = require_admission("paper_portfolio", release_dir=release,
                                     now=pd.Timestamp("2026-07-17"))
        assert decision.allowed is True


class TestEnvironmentallyBlockedSources:
    """A source declared unreachable in configs/freshness_policy.yaml stops
    halting the pipeline, but is still reported — never silently dropped."""

    def test_declared_source_degrades_instead_of_blocking(self, tmp_path, monkeypatch):
        release = tmp_path / "release"
        _write_release(release, ofr=False)
        monkeypatch.setattr(
            "verity.runtime._admission_gate._content_level_blockers",
            lambda now: ([], []),
        )
        monkeypatch.setattr(
            "verity.runtime._admission_gate._environmentally_blocked",
            lambda: {"OFR_FSI": {"reason": "host unreachable from this network"}},
        )
        decision = admit_for_consumption("paper_portfolio", release_dir=release,
                                         now=pd.Timestamp("2026-07-17"))
        assert decision.allowed is True
        assert decision.blockers == []
        # Reported, not hidden.
        assert any("OFR_FSI" in d for d in decision.degradations)
        assert any("host unreachable" in d for d in decision.degradations)

    def test_undeclared_source_still_blocks_alongside_declared_one(
        self, tmp_path, monkeypatch
    ):
        """Declaring one source must not wave through a different failure."""
        release = tmp_path / "release"
        _write_release(release, ofr=False, nfci_stale=True)
        monkeypatch.setattr(
            "verity.runtime._admission_gate._content_level_blockers",
            lambda now: ([], []),
        )
        monkeypatch.setattr(
            "verity.runtime._admission_gate._environmentally_blocked",
            lambda: {"OFR_FSI": {"reason": "host unreachable"}},
        )
        decision = admit_for_consumption("paper_portfolio", release_dir=release,
                                         now=pd.Timestamp("2026-07-17"))
        assert decision.allowed is False
        assert any("NFCI" in b for b in decision.blockers)
        assert not any("NFCI" in d for d in decision.degradations)

    def test_content_level_check_maps_to_declared_indicator(self, tmp_path, monkeypatch):
        """Content checks are named ofr_fsi_cache, not OFR_FSI; the mapping
        must resolve or the declaration silently fails to apply."""
        release = tmp_path / "release"
        _write_release(release)
        monkeypatch.setattr(
            "verity.runtime._admission_gate._content_level_blockers",
            lambda now: (["ofr_fsi_cache:stale (behind=17d)"], []),
        )
        monkeypatch.setattr(
            "verity.runtime._admission_gate._environmentally_blocked",
            lambda: {"OFR_FSI": {"reason": "host unreachable"}},
        )
        decision = admit_for_consumption("paper_portfolio", release_dir=release,
                                         now=pd.Timestamp("2026-07-17"))
        assert decision.allowed is True
        assert any("ofr_fsi_cache" in d for d in decision.degradations)


def test_content_gate_checks_decision_critical_etf_panel(monkeypatch) -> None:
    """The consumer gate must inspect ETF content, not only public caches."""
    import workbench.measurement.freshness_validator as freshness_validator

    from verity.runtime._admission_gate import _content_level_blockers

    monkeypatch.setattr(
        freshness_validator,
        "CONTENT_FRESHNESS",
        {
            "etf_panel": {
                "path": "Data/panel.parquet",
                "date_column": "date",
                "max_trading_days_behind": 2,
            }
        },
    )

    def stale_check(**kwargs):
        return {
            "name": kwargs["name"],
            "status": "STALE",
            "trading_days_behind": 3,
        }

    monkeypatch.setattr(freshness_validator, "check_content_freshness", stale_check)
    blockers, checks = _content_level_blockers(
        pd.Timestamp("2026-08-12").to_pydatetime()
    )

    assert checks[0]["name"] == "etf_panel"
    assert blockers == ["etf_panel:stale (behind=3d)"]
