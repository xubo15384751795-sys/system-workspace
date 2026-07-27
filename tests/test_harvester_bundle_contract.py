"""Harvester bundle contract tests (hermetic).

Verifies evidence_release schema shape and a synthetic sample validation.
Operator export-tree presence lives in test_harvester_bundle_operator.py.
See: governance/architecture_reality_decisions.md §3
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "protocols" / "evidence_release.schema.json"

try:
    import jsonschema

    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False


def test_evidence_release_schema_exists() -> None:
    assert SCHEMA_PATH.exists(), "evidence_release.schema.json missing from protocols/"


def test_evidence_release_schema_is_valid_json() -> None:
    data = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert "$schema" in data
    assert "properties" in data


def test_evidence_release_schema_has_required_fields() -> None:
    data = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    required = data.get("required", [])
    for field in (
        "id",
        "source",
        "created_at",
        "ttl_days",
        "quality_status",
        "schema_version",
        "allowed_use",
    ):
        assert field in required, f"evidence_release schema missing required field: {field}"


def test_evidence_release_schema_has_ttl_default() -> None:
    data = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert data["properties"]["ttl_days"]["default"] == 3


def test_evidence_release_schema_quality_status_enum() -> None:
    data = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    qs = data["properties"]["quality_status"]["enum"]
    assert "fresh" in qs
    assert "acceptable_lag" in qs
    assert "stale" in qs
    assert "missing" in qs


def test_evidence_release_schema_allowed_use_enum() -> None:
    data = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    au = data["properties"]["allowed_use"]["items"]["enum"]
    assert "core_judgment" in au
    assert "research" in au
    assert "training_feedback" in au


def test_sample_release_validates() -> None:
    if not HAS_JSONSCHEMA:
        pytest.skip("jsonschema not installed")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    sample = {
        "id": "test-release-001",
        "source": "FRED",
        "created_at": "2026-06-16T00:00:00Z",
        "ttl_days": 3,
        "quality_status": "fresh",
        "schema_version": "evidence_release.v1",
        "allowed_use": ["core_judgment"],
    }
    jsonschema.validate(sample, schema)
