"""Harvester bundle contract tests.

Verifies that Harvester evidence releases conform to the evidence_release
schema and that the evidence flow architecture is respected.
See: governance/architecture_reality_decisions.md §3
"""
from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]

# Try to import jsonschema for validation
try:
    import jsonschema
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False


def test_evidence_release_schema_exists() -> None:
    """protocols/evidence_release.schema.json must exist."""
    schema_path = ROOT / "protocols" / "evidence_release.schema.json"
    assert schema_path.exists(), "evidence_release.schema.json missing from protocols/"


def test_evidence_release_schema_is_valid_json() -> None:
    """evidence_release.schema.json must be valid JSON."""
    schema_path = ROOT / "protocols" / "evidence_release.schema.json"
    if not schema_path.exists():
        return
    data = json.loads(schema_path.read_text(encoding="utf-8"))
    assert "$schema" in data
    assert "properties" in data


def test_evidence_release_schema_has_required_fields() -> None:
    """Schema must require id, source, created_at, ttl_days, quality_status."""
    schema_path = ROOT / "protocols" / "evidence_release.schema.json"
    if not schema_path.exists():
        return
    data = json.loads(schema_path.read_text(encoding="utf-8"))
    required = data.get("required", [])
    for field in ("id", "source", "created_at", "ttl_days", "quality_status", "schema_version", "allowed_use"):
        assert field in required, f"evidence_release schema missing required field: {field}"


def test_evidence_release_schema_has_ttl_default() -> None:
    """ttl_days must default to 3."""
    schema_path = ROOT / "protocols" / "evidence_release.schema.json"
    if not schema_path.exists():
        return
    data = json.loads(schema_path.read_text(encoding="utf-8"))
    ttl = data["properties"]["ttl_days"]
    assert ttl["default"] == 3


def test_evidence_release_schema_quality_status_enum() -> None:
    """quality_status must enumerate fresh/acceptable_lag/stale/missing."""
    schema_path = ROOT / "protocols" / "evidence_release.schema.json"
    if not schema_path.exists():
        return
    data = json.loads(schema_path.read_text(encoding="utf-8"))
    qs = data["properties"]["quality_status"]["enum"]
    assert "fresh" in qs
    assert "acceptable_lag" in qs
    assert "stale" in qs
    assert "missing" in qs


def test_evidence_release_schema_allowed_use_enum() -> None:
    """allowed_use must include core_judgment, research, training_feedback."""
    schema_path = ROOT / "protocols" / "evidence_release.schema.json"
    if not schema_path.exists():
        return
    data = json.loads(schema_path.read_text(encoding="utf-8"))
    au = data["properties"]["allowed_use"]["items"]["enum"]
    assert "core_judgment" in au
    assert "research" in au
    assert "training_feedback" in au


def test_harvester_exports_exist() -> None:
    """Data/harvester/exports/ must exist (Harvester is the evidence entry)."""
    exports = ROOT / "Data" / "harvester" / "exports"
    assert exports.exists(), "Data/harvester/exports/ missing — Harvester not configured"


def test_sample_release_validates() -> None:
    """A valid sample release must pass schema validation."""
    if not HAS_JSONSCHEMA:
        return
    schema_path = ROOT / "protocols" / "evidence_release.schema.json"
    if not schema_path.exists():
        return
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
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
