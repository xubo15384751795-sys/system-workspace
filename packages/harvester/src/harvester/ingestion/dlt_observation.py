"""Validation helpers for provider-capture metadata used by dlt shadows."""
from __future__ import annotations

import json
import hashlib
import os
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

CAPTURE_MANIFEST_SCHEMA = "system.harvester.provider_capture.v1"


def payload_sha256(path: Path) -> str | None:
    """Return a file's SHA-256 digest, or ``None`` when it cannot be read."""
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def verify_payload_digest(path: Path, expected_digest: Any) -> bool:
    """Verify a captured payload file against its manifest SHA-256 digest."""
    if not isinstance(expected_digest, str):
        return False
    normalized = expected_digest.strip().lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        return False
    return payload_sha256(path) == normalized


def new_capture_manifest(
    *,
    provider: str,
    captured_at: datetime | None = None,
) -> dict[str, Any]:
    """Create a capture context for a successful provider acquisition."""
    captured = captured_at or datetime.now(UTC)
    if captured.tzinfo is None:
        raise ValueError("captured_at must include a timezone")
    captured_utc = captured.astimezone(UTC)
    stamp = captured_utc.strftime("%Y%m%dT%H%M%SZ")
    return {
        "schema_version": CAPTURE_MANIFEST_SCHEMA,
        "capture_id": f"{provider}-{stamp}",
        "capture_kind": "daily_provider_capture",
        "provider": provider,
        "observation_date": captured_utc.date().isoformat(),
        "captured_at": captured_utc.isoformat().replace("+00:00", "Z"),
        "payload_digests": {},
    }


def write_capture_manifest(path: Path, manifest: dict[str, Any]) -> None:
    """Atomically persist a validated capture sidecar."""
    validated = dict(manifest)
    if validated.get("schema_version") != CAPTURE_MANIFEST_SCHEMA:
        raise ValueError("capture manifest has an unsupported schema_version")
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            mode="w",
            encoding="utf-8",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(validated, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _utc_date(value: str) -> date:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("capture manifest captured_at must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError("capture manifest captured_at must include a timezone")
    return parsed.astimezone(UTC).date()


def load_capture_manifest(
    path: Path,
    *,
    expected_provider: str | None = None,
) -> dict[str, Any]:
    """Load and validate a capture manifest without touching provider state."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"capture manifest cannot be read: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"capture manifest is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("capture manifest must be a JSON object")
    if payload.get("schema_version") != CAPTURE_MANIFEST_SCHEMA:
        raise ValueError("capture manifest has an unsupported schema_version")

    capture_id = payload.get("capture_id")
    capture_kind = payload.get("capture_kind")
    provider = payload.get("provider")
    observation_date = payload.get("observation_date")
    captured_at = payload.get("captured_at")
    if not isinstance(capture_id, str) or not capture_id.strip():
        raise ValueError("capture manifest requires a non-empty capture_id")
    if not isinstance(capture_kind, str) or not capture_kind.strip():
        raise ValueError("capture manifest requires a non-empty capture_kind")
    if expected_provider is not None and provider != expected_provider:
        raise ValueError(
            f"capture manifest provider mismatch: expected {expected_provider!r}, got {provider!r}"
        )
    if not isinstance(observation_date, str):
        raise ValueError("capture manifest requires observation_date")
    try:
        parsed_observation_date = date.fromisoformat(observation_date)
    except ValueError as exc:
        raise ValueError("capture manifest observation_date must be YYYY-MM-DD") from exc
    if not isinstance(captured_at, str):
        raise ValueError("capture manifest requires captured_at")
    if _utc_date(captured_at) != parsed_observation_date:
        raise ValueError("capture manifest captured_at does not match observation_date in UTC")

    normalized = dict(payload)
    normalized["capture_id"] = capture_id.strip()
    normalized["capture_kind"] = capture_kind.strip()
    normalized["observation_date"] = parsed_observation_date.isoformat()
    return normalized


__all__ = [
    "CAPTURE_MANIFEST_SCHEMA",
    "load_capture_manifest",
    "new_capture_manifest",
    "payload_sha256",
    "verify_payload_digest",
    "write_capture_manifest",
]
