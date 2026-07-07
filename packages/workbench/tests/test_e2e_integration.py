"""End-to-end integration test.

Uses the minimal_provider_release example data to run:
  1. Contract validation  (contract_validator.validate_provider_release)
  2. Freshness manifest   (freshness.build_release_freshness_manifest)
  3. Dashboard rendering  (evidence_dashboard._series_summary, _render_markdown)

Verifies all three modules produce consistent output.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
import yaml

import workbench.contract_validator as cv
import workbench.evidence_dashboard as ed
import workbench.freshness as freshness


# ── Example data ────────────────────────────────────────────────────────

EXAMPLE_PROVIDER_RELEASE = {
    "schema_version": "workbench.data_provider_release.v1",
    "provider_id": "minimal_provider",
    "release_id": "20260504T120000Z",
    "created_at": "2026-05-04T12:00:00Z",
    "status": "finalized",
    "artifacts": [
        {"path": "data/evidence_panel.parquet", "role": "evidence_panel", "format": "parquet", "sha256": "test_sha256"},
        {"path": "source_registry.json", "role": "source_registry", "format": "json", "sha256": "test_sha256"},
        {"path": "provenance.jsonl", "role": "provenance", "format": "jsonl", "sha256": "test_sha256"},
    ],
    "provider_payload": {"example": True},
}

EXAMPLE_EVIDENCE_ROWS = [
    {"date": "2026-04-23", "series_id": "VIXCLS", "source_id": "fred", "source_series_id": "VIXCLS",
     "value": 19.31, "unit": "index", "frequency": "business_daily", "vintage_date": "2026-04-26", "quality_flag": "observed"},
    {"date": "2026-04-17", "series_id": "NFCI", "source_id": "fred_chicago_fed", "source_series_id": "NFCI",
     "value": -0.497, "unit": "index", "frequency": "weekly", "vintage_date": "2026-04-26", "quality_flag": "observed"},
]

FRESHNESS_POLICY = {
    "frequency_thresholds": {
        "weekly": {"fresh_lag_days": 10, "acceptable_lag_days": 21},
        "business_daily": {"fresh_lag_days": 3, "acceptable_lag_days": 10},
        "unknown": {"fresh_lag_days": 30, "acceptable_lag_days": 90},
    },
    "indicators": {
        "VIXCLS": {"frequency": "business_daily", "required": True},
        "NFCI": {"frequency": "weekly", "required": True},
    },
    "gate_defaults": {
        "stale_required_severity": "warn",
        "missing_required_severity": "block",
        "retired_used_severity": "block",
    },
}

CATALOG = {
    "created_at": "2026-05-04T12:00:00Z",
    "files": [{"role": "benchmark_panel", "path": "data/evidence_panel.parquet"}],
}

DESIRED_SERIES = ["VIXCLS", "NFCI"]


# ── Test ─────────────────────────────────────────────────────────────────

class TestE2EIntegration:
    def test_validate_contract(self, tmp_path, monkeypatch):
        """Step 1: contract validation on example data."""
        release = self._write_release(tmp_path)
        self._patch_cv(tmp_path, monkeypatch)
        cv.validate_provider_release(release / "provider_release.json")

    def test_freshness_manifest(self, tmp_path, monkeypatch):
        """Step 2: freshness manifest with explicit policy path."""
        release = self._write_release(tmp_path)
        policy_path = self._write_policy(tmp_path)
        monkeypatch.setattr(freshness, "ROOT", tmp_path)

        manifest = freshness.build_release_freshness_manifest(
            release, policy_path=policy_path,
        )
        assert manifest["schema_version"] == "workbench.freshness_manifest.v1"
        assert "indicators" in manifest
        ids = {i["series_id"] for i in manifest["indicators"]}
        assert "VIXCLS" in ids
        assert "NFCI" in ids
        assert "model_input_validity" in manifest
        assert "gate_result" in manifest

    def test_dashboard_rendering(self, tmp_path, monkeypatch):
        """Step 3: dashboard series summary + markdown rendering."""
        release = self._write_release(tmp_path)
        policy_path = self._write_policy(tmp_path)

        # Build freshness manifest (needed for series summary)
        monkeypatch.setattr(freshness, "ROOT", tmp_path)
        freshness_manifest = freshness.build_release_freshness_manifest(
            release, policy_path=policy_path,
        )
        freshness_by_series = {i["series_id"]: i for i in freshness_manifest["indicators"]}

        # Read panel + source registry
        panel = pd.read_parquet(release / "data" / "evidence_panel.parquet")
        sources = ed._source_lookup(
            json.loads((release / "source_registry.json").read_text(encoding="utf-8"))
        )

        # Generate series summaries (same logic as evidence_dashboard.build())
        series = [
            ed._series_summary(panel, sid, sources, freshness_by_series)
            for sid in DESIRED_SERIES
        ]

        series_ids = {s["series_id"] for s in series}
        assert "VIXCLS" in series_ids
        assert "NFCI" in series_ids

        vix = next(s for s in series if s["series_id"] == "VIXCLS")
        assert vix["status"] == "available"
        assert vix["latest_value"] == 19.31

        nfci = next(s for s in series if s["series_id"] == "NFCI")
        assert nfci["status"] == "available"
        assert nfci["latest_value"] == -0.497

        # Render markdown (test the rendering pipeline)
        payload = {
            "provider_release": release.name,
            "generated_at": "2026-05-04T12:00:00Z",
            "source_catalog": "catalog.json",
            "evidence_panel": "data/evidence_panel.parquet",
            "freshness_manifest": "freshness_manifest.json",
            "freshness": freshness_manifest,
            "chart_path": None,
            "series": series,
        }
        md = ed._render_markdown(payload)
        assert "VIXCLS" in md
        assert "NFCI" in md
        assert "fresh" in md

    # ── helpers (self-contained, no conftest dependency) ────────────────

    def _write_release(self, root: Path) -> Path:
        release = root / "Data" / "harvester" / "exports" / "20260504T120000Z"
        data_dir = release / "data"
        data_dir.mkdir(parents=True)

        # Provider release
        (release / "provider_release.json").write_text(
            json.dumps(EXAMPLE_PROVIDER_RELEASE, indent=2), encoding="utf-8")
        # Panel as parquet (freshness module requires it)
        pd.DataFrame(EXAMPLE_EVIDENCE_ROWS).to_parquet(
            data_dir / "evidence_panel.parquet", index=False)
        # Catalog
        (release / "catalog.json").write_text(
            json.dumps(CATALOG, indent=2), encoding="utf-8")
        # Source registry
        (release / "source_registry.json").write_text(
            json.dumps({"sources": [], "provider_id": "minimal", "created_at": "2026-05-04T12:00:00Z"}),
            encoding="utf-8")
        # Provenance (empty)
        (release / "provenance.jsonl").write_text("", encoding="utf-8")

        return release

    def _write_policy(self, root: Path) -> Path:
        policy_dir = root / "configs"
        policy_dir.mkdir(parents=True, exist_ok=True)
        path = policy_dir / "freshness_policy.yaml"
        path.write_text(yaml.dump(FRESHNESS_POLICY), encoding="utf-8")
        return path

    def _patch_cv(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(cv, "ROOT", root)
        monkeypatch.setattr(cv, "CONTRACTS", root / "contracts" / "workbench")
