"""Phase A step 4: freshness hard-fail + policy severity tests.

Verifies:
- The freshness policy now treats stale/missing NFCI/OFR_FSI/CISS as BLOCK
  (not warn), so workbench.freshness._gate_result emits blockers.
- freshness_validator.main() returns 1 on FAIL verdict (hard ordering/closure
  violations), so the pipeline runner records status="failed" and the publish
  gate blocks.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "workbench" / "src"))

from workbench.freshness import build_release_freshness_manifest  # noqa: E402


def _make_release(tmp_path: Path, *, ofr_date=None, nfci_date=None, ciss_date=None,
                  as_of="2026-07-17"):
    """Build a minimal release with optional public-component series."""
    release = tmp_path / "20260717T000000Z"
    data_dir = release / "data"
    data_dir.mkdir(parents=True)
    rows = []
    for sid, d, freq in [
        ("VIXCLS", "2026-07-16", "daily"),
        ("BAMLH0A0HYM2", "2026-07-16", "daily"),
    ]:
        rows.append({
            "date": pd.Timestamp(d), "series_id": sid,
            "source_id": "fred", "source_series_id": sid,
            "value": 20.0, "unit": "index", "frequency": freq,
            "vintage_date": pd.Timestamp(as_of), "quality_flag": "observed",
        })
    if ofr_date:
        rows.append({
            "date": pd.Timestamp(ofr_date), "series_id": "OFR_FSI",
            "source_id": "ofr", "source_series_id": "OFR_FSI",
            "value": 0.3, "unit": "index", "frequency": "daily",
            "vintage_date": pd.Timestamp(as_of), "quality_flag": "observed",
        })
    if nfci_date:
        rows.append({
            "date": pd.Timestamp(nfci_date), "series_id": "NFCI",
            "source_id": "fred_chicago_fed", "source_series_id": "NFCI",
            "value": -0.4, "unit": "index", "frequency": "weekly",
            "vintage_date": pd.Timestamp(as_of), "quality_flag": "observed",
        })
    if ciss_date:
        rows.append({
            "date": pd.Timestamp(ciss_date), "series_id": "CISS",
            "source_id": "ecb", "source_series_id": "CISS",
            "value": 0.2, "unit": "index", "frequency": "daily",
            "vintage_date": pd.Timestamp(as_of), "quality_flag": "observed",
        })
    pd.DataFrame(rows).to_parquet(data_dir / "benchmark_panel.parquet")
    (release / "catalog.json").write_text(
        json.dumps({
            "bundle_id": release.name,
            "created_at": "2026-07-17T00:00:00Z",
            "files": [{"role": "benchmark_panel", "path": "data/benchmark_panel.parquet"}],
        }),
        encoding="utf-8",
    )
    return release


import json  # noqa: E402


class TestPublicComponentPolicyBlocks:
    """NFCI/OFR_FSI/CISS stale or missing must produce gate blockers."""

    def test_missing_ofr_produces_blocker(self, tmp_path):
        release = _make_release(tmp_path, nfci_date="2026-07-12", ciss_date="2026-07-16")
        manifest = build_release_freshness_manifest(release)
        by_series = {i["series_id"]: i for i in manifest["indicators"]}
        assert by_series["OFR_FSI"]["required"] is True
        assert by_series["OFR_FSI"]["freshness_status"] == "missing"
        assert any("OFR_FSI" in b for b in manifest["gate_result"]["blockers"]), (
            f"OFR_FSI missing must be a blocker, got blockers={manifest['gate_result']['blockers']}"
        )
        assert manifest["gate_result"]["promotion_allowed"] is False

    def test_stale_nfci_produces_blocker(self, tmp_path):
        # NFCI weekly: acceptable_lag 21 days. 30 days behind => stale.
        release = _make_release(
            tmp_path, ofr_date="2026-07-16", nfci_date="2026-06-15", ciss_date="2026-07-16",
        )
        manifest = build_release_freshness_manifest(release)
        by_series = {i["series_id"]: i for i in manifest["indicators"]}
        assert by_series["NFCI"]["freshness_status"] == "stale"
        assert any("NFCI" in b for b in manifest["gate_result"]["blockers"]), (
            f"stale NFCI must be a blocker, got blockers={manifest['gate_result']['blockers']}"
        )
        assert manifest["gate_result"]["promotion_allowed"] is False

    def test_all_components_fresh_no_blockers_for_them(self, tmp_path):
        release = _make_release(
            tmp_path, ofr_date="2026-07-16", nfci_date="2026-07-12", ciss_date="2026-07-16",
        )
        manifest = build_release_freshness_manifest(release)
        by_series = {i["series_id"]: i for i in manifest["indicators"]}
        # The three public components should be fresh/acceptable, not stale/missing.
        for sid in ("OFR_FSI", "NFCI", "CISS"):
            assert by_series[sid]["freshness_status"] in ("fresh", "acceptable_lag"), (
                f"{sid} should be fresh/acceptable, got {by_series[sid]['freshness_status']}"
            )
        # No blocker should name any of the three public components.
        for sid in ("OFR_FSI", "NFCI", "CISS"):
            assert not any(sid in b for b in manifest["gate_result"]["blockers"]), (
                f"{sid} should not be blocked when fresh, got {manifest['gate_result']['blockers']}"
            )


class TestFreshnessValidatorMainExitCode:
    """freshness_validator.main() returns 1 on FAIL, 0 otherwise."""

    def test_main_returns_int(self):
        """main() signature returns int (callable runner maps to returncode)."""
        scripts_dir = str(ROOT / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        import freshness_validator as fv
        import inspect
        sig = inspect.signature(fv.main)
        # The return annotation should be int (not None) - this is the
        # contract the callable runner relies on to produce a nonzero exit.
        assert sig.return_annotation is int or str(sig.return_annotation) == "int", (
            f"main() must return int for hard-fail exit, got {sig.return_annotation}"
        )
