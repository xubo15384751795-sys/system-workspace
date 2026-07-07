"""Tests for workbench.freshness — pure-logic and filesystem."""
from __future__ import annotations

import json

import pandas as pd
import pytest
import yaml

import workbench.freshness as freshness


# ---------------------------------------------------------------------------
# classify_lag
# ---------------------------------------------------------------------------

class TestClassifyLag:
    POLICY = {
        "frequency_thresholds": {
            "weekly": {"fresh_lag_days": 10, "acceptable_lag_days": 21},
            "daily":  {"fresh_lag_days": 3,  "acceptable_lag_days": 10},
            "unknown": {"fresh_lag_days": 30, "acceptable_lag_days": 90},
        }
    }

    def test_none_lag_returns_missing(self):
        assert freshness.classify_lag(None, "weekly", self.POLICY) == "missing"

    def test_fresh_within_threshold(self):
        assert freshness.classify_lag(5, "weekly", self.POLICY) == "fresh"

    def test_fresh_at_boundary(self):
        assert freshness.classify_lag(10, "weekly", self.POLICY) == "fresh"

    def test_acceptable_lag(self):
        assert freshness.classify_lag(15, "weekly", self.POLICY) == "acceptable_lag"

    def test_stale_past_acceptable(self):
        assert freshness.classify_lag(25, "weekly", self.POLICY) == "stale"

    def test_daily_fresh(self):
        assert freshness.classify_lag(2, "daily", self.POLICY) == "fresh"

    def test_daily_acceptable(self):
        assert freshness.classify_lag(7, "daily", self.POLICY) == "acceptable_lag"

    def test_daily_stale(self):
        assert freshness.classify_lag(15, "daily", self.POLICY) == "stale"

    def test_unknown_frequency_falls_back(self):
        assert freshness.classify_lag(20, "quarterly", self.POLICY) == "fresh"

    def test_zero_lag_is_fresh(self):
        assert freshness.classify_lag(0, "weekly", self.POLICY) == "fresh"


# ---------------------------------------------------------------------------
# parse_timestamp / parse_date
# ---------------------------------------------------------------------------

class TestParseTimestamp:
    def test_none_returns_none(self):
        assert freshness.parse_timestamp(None) is None

    def test_empty_string_returns_none(self):
        assert freshness.parse_timestamp("") is None

    def test_valid_iso_string(self):
        result = freshness.parse_timestamp("2026-04-01T12:00:00Z")
        assert result is not None
        assert result.year == 2026

    def test_invalid_string_returns_none(self):
        assert freshness.parse_timestamp("not-a-date") is None


class TestParseDate:
    def test_none_returns_none(self):
        assert freshness.parse_date(None) is None

    def test_date_string(self):
        result = freshness.parse_date("2026-03-15")
        assert result is not None
        assert result.day == 15


# ---------------------------------------------------------------------------
# banner_lines
# ---------------------------------------------------------------------------

class TestBannerLines:
    def _freshness(self, indicators=None, **extra):
        return {
            "evidence_created_at": "2026-05-01T00:00:00Z",
            "run_generated_at": "2026-05-02T10:00:00Z",
            "model_input_validity": "usable",
            "gate_result": {"canonical_promotion_severity": "pass"},
            "indicators": indicators or [],
            **extra,
        }

    def test_returns_list_of_strings(self):
        lines = freshness.banner_lines(self._freshness())
        assert isinstance(lines, list)
        assert all(isinstance(line, str) for line in lines)

    def test_contains_validity(self):
        lines = freshness.banner_lines(self._freshness())
        combined = "\n".join(lines)
        assert "usable" in combined

    def test_freshness_counts_appear(self):
        indicators = [
            {"freshness_status": "fresh"},
            {"freshness_status": "stale"},
            {"freshness_status": "stale"},
        ]
        lines = freshness.banner_lines(self._freshness(indicators=indicators))
        combined = "\n".join(lines)
        assert "fresh=1" in combined
        assert "stale=2" in combined

    def test_missing_evidence_created_at(self):
        data = self._freshness()
        data["evidence_created_at"] = None
        lines = freshness.banner_lines(data)
        combined = "\n".join(lines)
        assert "unknown" in combined


# ---------------------------------------------------------------------------
# _model_input_validity
# ---------------------------------------------------------------------------

class TestModelInputValidity:
    def _indicator(self, status, required=True):
        return {"freshness_status": status, "required": required}

    def test_all_fresh_is_usable(self):
        indicators = [self._indicator("fresh"), self._indicator("fresh")]
        assert freshness._model_input_validity(indicators) == "usable"

    def test_acceptable_lag_is_usable_with_lag(self):
        indicators = [self._indicator("acceptable_lag"), self._indicator("fresh")]
        assert freshness._model_input_validity(indicators) == "usable_with_lag"

    def test_stale_required_is_degraded(self):
        indicators = [self._indicator("stale"), self._indicator("fresh")]
        assert freshness._model_input_validity(indicators) == "degraded"

    def test_missing_required_is_incomplete(self):
        indicators = [self._indicator("missing")]
        assert freshness._model_input_validity(indicators) == "incomplete"

    def test_non_required_missing_ignored(self):
        indicators = [self._indicator("missing", required=False), self._indicator("fresh")]
        assert freshness._model_input_validity(indicators) == "usable"


# ---------------------------------------------------------------------------
# _gate_result
# ---------------------------------------------------------------------------

class TestGateResult:
    POLICY = {"gate_defaults": {"stale_required_severity": "warn", "missing_required_severity": "block"}}

    def _ind(self, sid, status, required=True, severity="none"):
        return {"series_id": sid, "freshness_status": status, "required": required, "gate_severity": severity, "used_in_current_diagnostics": False}

    def test_all_ok_passes(self):
        indicators = [self._ind("NFCI", "fresh")]
        result = freshness._gate_result(indicators, self.POLICY, "usable")
        assert result["promotion_allowed"] is True
        assert result["canonical_promotion_severity"] == "pass"

    def test_stale_required_adds_warning(self):
        indicators = [self._ind("NFCI", "stale", severity="warn")]
        result = freshness._gate_result(indicators, self.POLICY, "degraded")
        assert "NFCI" in " ".join(result["warnings"])
        assert result["promotion_allowed"] is True

    def test_missing_required_blocks(self):
        indicators = [self._ind("MOVE", "missing", severity="block")]
        result = freshness._gate_result(indicators, self.POLICY, "incomplete")
        assert result["promotion_allowed"] is False
        assert result["canonical_promotion_severity"] == "block"

    def test_retired_used_in_diagnostics_blocks(self):
        ind = self._ind("TEDRATE", "retired_or_unavailable", required=False)
        ind["used_in_current_diagnostics"] = True
        result = freshness._gate_result([ind], self.POLICY, "usable")
        assert result["promotion_allowed"] is False


# ---------------------------------------------------------------------------
# build_release_freshness_manifest — filesystem fixture test
# ---------------------------------------------------------------------------

class TestBuildReleaseFreshnessManifest:
    def _write_release(self, tmp_path, sample_policy, sample_panel):
        release = tmp_path / "Data" / "harvester" / "exports" / "rel_20260501"
        release.mkdir(parents=True)
        catalog = {
            "created_at": "2026-05-01T08:00:00Z",
            "files": [{"role": "benchmark_panel", "path": "panel.parquet"}],
        }
        (release / "catalog.json").write_text(json.dumps(catalog))
        sample_panel.to_parquet(release / "panel.parquet", index=False)

        policy_path = tmp_path / "configs" / "freshness_policy.yaml"
        policy_path.parent.mkdir(parents=True, exist_ok=True)
        policy_path.write_text(yaml.dump(sample_policy))

        return release, policy_path

    def test_manifest_has_required_keys(self, tmp_path, sample_policy, sample_panel):
        release, policy_path = self._write_release(tmp_path, sample_policy, sample_panel)
        manifest = freshness.build_release_freshness_manifest(release, policy_path=policy_path)
        for key in ("schema_version", "indicators", "model_input_validity", "gate_result"):
            assert key in manifest

    def test_known_indicator_appears(self, tmp_path, sample_policy, sample_panel):
        release, policy_path = self._write_release(tmp_path, sample_policy, sample_panel)
        manifest = freshness.build_release_freshness_manifest(release, policy_path=policy_path)
        ids = {ind["series_id"] for ind in manifest["indicators"]}
        assert "NFCI" in ids

    def test_retired_indicator_status(self, tmp_path, sample_policy, sample_panel):
        release, policy_path = self._write_release(tmp_path, sample_policy, sample_panel)
        manifest = freshness.build_release_freshness_manifest(release, policy_path=policy_path)
        tedrate = next(i for i in manifest["indicators"] if i["series_id"] == "TEDRATE")
        assert tedrate["freshness_status"] == "retired_or_unavailable"

    def test_indicator_matches_provider_prefixed_canonical_id(self, tmp_path, sample_policy, sample_panel):
        sample_policy["indicators"]["MOVE"] = {"frequency": "daily", "required": True}
        move = pd.DataFrame([
            {
                "series_id": "CBOE:MOVE",
                "date": "2026-05-01",
                "value": 12.22,
                "vintage_date": "2026-05-01",
                "unit": "index",
                "frequency": "daily",
                "source_id": "cboe",
                "source_series_id": "VXTLT",
                "quality_flag": "ok",
            }
        ])
        panel = pd.concat([sample_panel, move], ignore_index=True)
        release, policy_path = self._write_release(tmp_path, sample_policy, panel)

        manifest = freshness.build_release_freshness_manifest(release, policy_path=policy_path)

        move_item = next(i for i in manifest["indicators"] if i["series_id"] == "MOVE")
        assert move_item["freshness_status"] == "fresh"
        assert move_item["observation_date"] == "2026-05-01"

    def test_raises_if_no_benchmark_panel(self, tmp_path, sample_policy):
        release = tmp_path / "release_bad"
        release.mkdir()
        catalog = {"created_at": "2026-05-01T08:00:00Z", "files": []}
        (release / "catalog.json").write_text(json.dumps(catalog))
        policy_path = tmp_path / "configs" / "freshness_policy.yaml"
        policy_path.parent.mkdir(parents=True, exist_ok=True)
        policy_path.write_text(yaml.dump(sample_policy))
        with pytest.raises(FileNotFoundError):
            freshness.build_release_freshness_manifest(release, policy_path=policy_path)


# ---------------------------------------------------------------------------
# build_release_freshness_manifest — dataset-mode catalog
# ---------------------------------------------------------------------------

class TestBuildReleaseFreshnessManifestDatasetMode:
    """Dataset-mode catalogs declare datasets[] rather than files[].role.

    The active 2026-05-05-r1 release uses this format; this suite locks the
    behaviour so the bundle/dataset split cannot silently regress.
    """

    def _write_dataset_release(self, tmp_path, sample_policy, sample_panel, *, dataset_id="official_panel"):
        release = tmp_path / "Data" / "harvester" / "exports" / "rel_20260510_ds"
        (release / "data").mkdir(parents=True)
        catalog = {
            "schema_version": "1.0",
            "release_id": "rel_20260510_ds",
            "harvester_version": "0.1.0",
            "finalized_at": "2026-05-10T08:00:00Z",
            "datasets": [
                {
                    "dataset_id": dataset_id,
                    "dataset_revision": 1,
                    "data_path": f"data/{dataset_id}.parquet",
                    "manifest_path": f"manifests/{dataset_id}.manifest.json",
                    "provenance_path": f"provenance/{dataset_id}.provenance.json",
                    "summary": "test fixture",
                }
            ],
        }
        (release / "catalog.json").write_text(json.dumps(catalog))
        sample_panel.to_parquet(release / "data" / f"{dataset_id}.parquet", index=False)

        policy_path = tmp_path / "configs" / "freshness_policy.yaml"
        policy_path.parent.mkdir(parents=True, exist_ok=True)
        policy_path.write_text(yaml.dump(sample_policy))
        return release, policy_path

    def test_dataset_mode_official_panel_resolves(self, tmp_path, sample_policy, sample_panel):
        release, policy_path = self._write_dataset_release(tmp_path, sample_policy, sample_panel)
        manifest = freshness.build_release_freshness_manifest(release, policy_path=policy_path)
        assert manifest["evidence_created_at"] == "2026-05-10T08:00:00Z"
        ids = {ind["series_id"] for ind in manifest["indicators"]}
        assert "NFCI" in ids
        assert "VIXCLS" in ids

    def test_dataset_mode_legacy_benchmark_panel_alias(self, tmp_path, sample_policy, sample_panel):
        release, policy_path = self._write_dataset_release(
            tmp_path, sample_policy, sample_panel, dataset_id="benchmark_panel"
        )
        manifest = freshness.build_release_freshness_manifest(release, policy_path=policy_path)
        ids = {ind["series_id"] for ind in manifest["indicators"]}
        assert "NFCI" in ids

    def test_dataset_mode_no_panel_raises(self, tmp_path, sample_policy):
        release = tmp_path / "release_no_panel"
        (release / "data").mkdir(parents=True)
        catalog = {
            "schema_version": "1.0",
            "release_id": "release_no_panel",
            "finalized_at": "2026-05-10T08:00:00Z",
            "datasets": [
                {
                    "dataset_id": "some_other_dataset",
                    "dataset_revision": 1,
                    "data_path": "data/some_other_dataset.parquet",
                    "manifest_path": "manifests/some_other_dataset.manifest.json",
                    "provenance_path": "provenance/some_other_dataset.provenance.json",
                }
            ],
        }
        (release / "catalog.json").write_text(json.dumps(catalog))
        policy_path = tmp_path / "configs" / "freshness_policy.yaml"
        policy_path.parent.mkdir(parents=True, exist_ok=True)
        policy_path.write_text(yaml.dump(sample_policy))
        with pytest.raises(FileNotFoundError, match="dataset-mode catalog"):
            freshness.build_release_freshness_manifest(release, policy_path=policy_path)

    def test_unknown_catalog_mode_raises(self, tmp_path, sample_policy):
        release = tmp_path / "release_weird"
        release.mkdir()
        catalog = {"schema_version": "1.0", "release_id": "rw", "comment": "no datasets, no files"}
        (release / "catalog.json").write_text(json.dumps(catalog))
        policy_path = tmp_path / "configs" / "freshness_policy.yaml"
        policy_path.parent.mkdir(parents=True, exist_ok=True)
        policy_path.write_text(yaml.dump(sample_policy))
        with pytest.raises(FileNotFoundError, match="unknown catalog mode"):
            freshness.build_release_freshness_manifest(release, policy_path=policy_path)


# ---------------------------------------------------------------------------
# _resolve_panel_from_catalog — helper coverage
# ---------------------------------------------------------------------------

class TestResolvePanelFromCatalog:
    def test_bundle_mode_returns_file_path(self, tmp_path):
        release = tmp_path / "rel_bundle"
        release.mkdir()
        catalog = {
            "bundle_id": "bundle_abc",
            "created_at": "2026-05-01T08:00:00Z",
            "files": [{"role": "benchmark_panel", "path": "panel.parquet"}],
        }
        path, evidence = freshness._resolve_panel_from_catalog(release, catalog)
        assert path == release / "panel.parquet"
        assert evidence == "2026-05-01T08:00:00Z"

    def test_dataset_mode_prefers_official_panel(self, tmp_path):
        release = tmp_path / "rel_ds"
        release.mkdir()
        catalog = {
            "release_id": "rel_ds",
            "finalized_at": "2026-05-10T00:00:00Z",
            "datasets": [
                {"dataset_id": "benchmark_panel", "data_path": "data/bp.parquet",
                 "manifest_path": "m.json", "provenance_path": "p.json"},
                {"dataset_id": "official_panel", "data_path": "data/op.parquet",
                 "manifest_path": "m2.json", "provenance_path": "p2.json"},
            ],
        }
        path, evidence = freshness._resolve_panel_from_catalog(release, catalog)
        assert path == release / "data" / "op.parquet"
        assert evidence == "2026-05-10T00:00:00Z"
