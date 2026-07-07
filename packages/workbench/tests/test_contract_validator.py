"""Tests for workbench.contract_validator — pure logic and filesystem."""
from __future__ import annotations

import csv
import json
from io import StringIO
from pathlib import Path

import pandas as pd
import pytest

import workbench.contract_validator as cv


# ---------------------------------------------------------------------------
# _path_is_relative
# ---------------------------------------------------------------------------

class TestPathIsRelative:
    def test_simple_relative(self):
        assert cv._path_is_relative("reports/foo.json") is True

    def test_filename_only(self):
        assert cv._path_is_relative("foo.json") is True

    def test_absolute_path_rejected(self):
        assert cv._path_is_relative("/absolute/path.json") is False

    def test_dotdot_rejected(self):
        assert cv._path_is_relative("../escape.json") is False

    def test_empty_string_rejected(self):
        assert cv._path_is_relative("") is False

    def test_nested_relative_ok(self):
        assert cv._path_is_relative("a/b/c/d.parquet") is True


# ---------------------------------------------------------------------------
# _validate_schema
# ---------------------------------------------------------------------------

class TestValidateSchema:
    def _schema(self, required=None, version_const=None):
        s = {}
        if required:
            s["required"] = required
        if version_const:
            s["properties"] = {"schema_version": {"const": version_const}}
        return s

    def test_missing_required_field(self):
        errors = cv._validate_schema({"foo": 1}, self._schema(required=["foo", "bar"]))
        assert any("bar" in e for e in errors)

    def test_all_required_present(self):
        errors = cv._validate_schema({"foo": 1, "bar": 2}, self._schema(required=["foo", "bar"]))
        assert errors == []

    def test_wrong_schema_version(self):
        errors = cv._validate_schema(
            {"schema_version": "v9"},
            self._schema(version_const="workbench.model_run.v1"),
        )
        assert any("schema_version" in e for e in errors)

    def test_correct_schema_version(self):
        errors = cv._validate_schema(
            {"schema_version": "workbench.model_run.v1"},
            self._schema(version_const="workbench.model_run.v1"),
        )
        assert errors == []


# ---------------------------------------------------------------------------
# validate_evidence_panel — CSV
# ---------------------------------------------------------------------------

REQUIRED_COLS = {"date", "series_id", "source_id", "source_series_id", "value",
                 "unit", "frequency", "vintage_date", "quality_flag"}


def _make_csv(tmp_path, cols=None, rows=1):
    cols = cols or list(REQUIRED_COLS)
    path = tmp_path / "panel.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        for _ in range(rows):
            writer.writerow({col: "x" for col in cols})
    return path


class TestValidateEvidencePanelCsv:
    def test_valid_csv_passes(self, tmp_path):
        path = _make_csv(tmp_path)
        cv.validate_evidence_panel(path)  # no exception

    def test_missing_column_raises(self, tmp_path):
        cols = list(REQUIRED_COLS - {"value"})
        path = _make_csv(tmp_path, cols=cols)
        with pytest.raises(cv.ValidationError, match="value"):
            cv.validate_evidence_panel(path)

    def test_empty_csv_raises(self, tmp_path):
        path = tmp_path / "empty.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(REQUIRED_COLS))
            writer.writeheader()
        with pytest.raises(cv.ValidationError, match="no rows"):
            cv.validate_evidence_panel(path)

    def test_unsupported_format_raises(self, tmp_path):
        path = tmp_path / "panel.txt"
        path.write_text("data")
        with pytest.raises(cv.ValidationError, match="unsupported"):
            cv.validate_evidence_panel(path)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(cv.ValidationError, match="missing"):
            cv.validate_evidence_panel(tmp_path / "nonexistent.csv")


# ---------------------------------------------------------------------------
# validate_evidence_panel — Parquet
# ---------------------------------------------------------------------------

class TestValidateEvidencePanelParquet:
    def _make_parquet(self, tmp_path, extra_cols=None):
        cols = list(REQUIRED_COLS) + (extra_cols or [])
        df = pd.DataFrame([{col: "x" for col in cols}])
        path = tmp_path / "panel.parquet"
        df.to_parquet(path, index=False)
        return path

    def test_valid_parquet_passes(self, tmp_path):
        path = self._make_parquet(tmp_path)
        cv.validate_evidence_panel(path)

    def test_missing_column_raises(self, tmp_path):
        cols = list(REQUIRED_COLS - {"series_id"})
        df = pd.DataFrame([{col: "x" for col in cols}])
        path = tmp_path / "bad.parquet"
        df.to_parquet(path, index=False)
        with pytest.raises(cv.ValidationError, match="series_id"):
            cv.validate_evidence_panel(path)

    def test_empty_parquet_raises(self, tmp_path):
        df = pd.DataFrame(columns=list(REQUIRED_COLS))
        path = tmp_path / "empty.parquet"
        df.to_parquet(path, index=False)
        with pytest.raises(cv.ValidationError, match="no rows"):
            cv.validate_evidence_panel(path)


# ---------------------------------------------------------------------------
# validate_model_run
# ---------------------------------------------------------------------------

def _model_run_payload(artifacts_root: Path, artifact_paths: dict[str, str]) -> dict:
    return {
        "schema_version": "workbench.model_run.v1",
        "model_id": "deformation",
        "run_id": "run_20260507",
        "run_date": "2026-05-07",
        "generated_at": "2026-05-07T10:00:00Z",
        "status": "complete",
        "artifacts": {
            key: {"path": rel, "kind": "json", "description": "test"}
            for key, rel in artifact_paths.items()
        },
    }


class TestValidateModelRun:
    def test_valid_run_passes(self, tmp_path):
        artifact = tmp_path / "report.json"
        artifact.write_text("{}")
        payload = _model_run_payload(tmp_path, {"report": "report.json"})
        run_path = tmp_path / "model_run.json"
        run_path.write_text(json.dumps(payload))
        cv.validate_model_run(run_path)

    def test_missing_required_field_raises(self, tmp_path):
        payload = {"schema_version": "workbench.model_run.v1"}  # missing run_id etc.
        run_path = tmp_path / "model_run.json"
        run_path.write_text(json.dumps(payload))
        with pytest.raises(cv.ValidationError):
            cv.validate_model_run(run_path)

    def test_wrong_schema_version_raises(self, tmp_path):
        artifact = tmp_path / "a.json"
        artifact.write_text("{}")
        payload = _model_run_payload(tmp_path, {"a": "a.json"})
        payload["schema_version"] = "wrong.version.v99"
        run_path = tmp_path / "model_run.json"
        run_path.write_text(json.dumps(payload))
        with pytest.raises(cv.ValidationError, match="schema_version"):
            cv.validate_model_run(run_path)

    def test_missing_artifact_file_raises(self, tmp_path):
        payload = _model_run_payload(tmp_path, {"ghost": "does_not_exist.json"})
        run_path = tmp_path / "model_run.json"
        run_path.write_text(json.dumps(payload))
        with pytest.raises(cv.ValidationError, match="does not exist"):
            cv.validate_model_run(run_path)

    def test_absolute_artifact_path_raises(self, tmp_path):
        payload = _model_run_payload(tmp_path, {"bad": "/absolute/path.json"})
        run_path = tmp_path / "model_run.json"
        run_path.write_text(json.dumps(payload))
        with pytest.raises(cv.ValidationError, match="safe relative"):
            cv.validate_model_run(run_path)

    def test_unknown_artifact_kind_raises(self, tmp_path):
        artifact = tmp_path / "x.json"
        artifact.write_text("{}")
        payload = _model_run_payload(tmp_path, {"x": "x.json"})
        payload["artifacts"]["x"]["kind"] = "docx"
        run_path = tmp_path / "model_run.json"
        run_path.write_text(json.dumps(payload))
        with pytest.raises(cv.ValidationError, match="unknown kind"):
            cv.validate_model_run(run_path)
