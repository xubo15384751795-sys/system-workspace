from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from harvester.ingestion.dlt_observation import (
    CAPTURE_MANIFEST_SCHEMA,
    load_capture_manifest,
    new_capture_manifest,
    payload_sha256,
    verify_payload_digest,
    write_capture_manifest,
)


def _manifest() -> dict[str, object]:
    return {
        "schema_version": CAPTURE_MANIFEST_SCHEMA,
        "capture_id": "external-2026-08-25",
        "capture_kind": "daily_provider_capture",
        "provider": "external_indicators",
        "observation_date": "2026-08-25",
        "captured_at": "2026-08-25T07:30:00+00:00",
    }


def test_capture_manifest_is_validated_and_normalized(tmp_path: Path) -> None:
    path = tmp_path / "capture.json"
    path.write_text(json.dumps(_manifest()), encoding="utf-8")

    result = load_capture_manifest(path, expected_provider="external_indicators")

    assert result["capture_id"] == "external-2026-08-25"
    assert result["observation_date"] == "2026-08-25"


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", "old.v0"),
        ("capture_id", ""),
        ("observation_date", "not-a-date"),
        ("captured_at", "2026-08-25T07:30:00"),
    ],
)
def test_capture_manifest_rejects_invalid_fields(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    payload = _manifest()
    payload[field] = value
    path = tmp_path / "capture.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError):
        load_capture_manifest(path, expected_provider="external_indicators")


def test_capture_manifest_rejects_provider_or_utc_date_mismatch(tmp_path: Path) -> None:
    payload = _manifest()
    payload["provider"] = "cftc"
    path = tmp_path / "capture.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="provider mismatch"):
        load_capture_manifest(path, expected_provider="external_indicators")

    payload = _manifest()
    payload["captured_at"] = "2026-08-26T07:30:00+00:00"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="does not match"):
        load_capture_manifest(path, expected_provider="external_indicators")


def test_payload_digest_verification_binds_manifest_to_bytes(tmp_path: Path) -> None:
    payload = tmp_path / "capture.bin"
    payload.write_bytes(b"captured-provider-payload")

    assert verify_payload_digest(
        payload,
        "9fb9e56acf9b177a51f83d4d9ec789fe6ecbcb54df70c404f25dc70636c664c5",
    ) is True
    assert verify_payload_digest(
        payload,
        "8f3d9a1e3f4b0e8e44d9f168a2cc0d431840a306bb8ff2a6c4cc7d65f8b1a86b",
    ) is False
    assert verify_payload_digest(payload, "not-a-digest") is False
    assert verify_payload_digest(payload, None) is False


def test_capture_manifest_factory_and_writer_are_atomic(tmp_path: Path) -> None:
    payload = tmp_path / "payload.csv"
    payload.write_text("date,value\n2026-08-25,1\n", encoding="utf-8")
    manifest = new_capture_manifest(
        provider="external_indicators",
        captured_at=datetime(2026, 8, 25, 7, 30, tzinfo=UTC),
    )
    manifest["payload_digests"] = {"CISS": payload_sha256(payload)}
    path = tmp_path / "capture.json"
    write_capture_manifest(path, manifest)

    loaded = load_capture_manifest(path, expected_provider="external_indicators")
    assert loaded["capture_id"] == "external_indicators-20260825T073000Z"
    assert loaded["payload_digests"]["CISS"] == payload_sha256(payload)
    assert not list(tmp_path.glob(".capture.json.*.tmp"))
