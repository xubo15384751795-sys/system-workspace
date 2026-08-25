"""Read-only parity records for the native-asset migration batches."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

_EPHEMERAL_FIELDS = frozenset({"generated_at"})


def _canonicalize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _canonicalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key) not in _EPHEMERAL_FIELDS
        }
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    return value


def _digest(value: Any) -> str:
    encoded = json.dumps(
        _canonicalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def compare_native_report(
    *,
    step_id: str,
    native_report: Mapping[str, Any] | None,
    legacy_report: Any,
) -> dict[str, Any]:
    """Compare one native report with its existing registry artifact.

    The comparison ignores only ``generated_at``. Missing or unreadable
    legacy artifacts are explicit non-green states, never empty success.
    """
    if native_report is None:
        return {
            "step_id": step_id,
            "status": "NATIVE_MISSING",
            "promotion_allowed": False,
        }
    if legacy_report is None:
        return {
            "step_id": step_id,
            "status": "LEGACY_MISSING",
            "promotion_allowed": False,
            "native_digest": _digest(native_report),
        }

    native_digest = _digest(native_report)
    legacy_digest = _digest(legacy_report)
    result: dict[str, Any] = {
        "step_id": step_id,
        "status": "MATCH" if native_digest == legacy_digest else "MISMATCH",
        "promotion_allowed": False,
        "native_digest": native_digest,
        "legacy_digest": legacy_digest,
        "ignored_fields": sorted(_EPHEMERAL_FIELDS),
    }
    if result["status"] == "MISMATCH":
        result["native_report"] = _canonicalize(native_report)
        result["legacy_report"] = _canonicalize(legacy_report)
    return result


def build_native_parity_report(
    comparisons: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Build the non-authoritative aggregate report for an operator run."""
    statuses = [str(item.get("status") or "UNKNOWN") for item in comparisons.values()]
    if not statuses:
        overall = "NO_NATIVE_ASSETS"
    elif any(status == "MISMATCH" for status in statuses):
        overall = "MISMATCH"
    elif any(status in {"LEGACY_MISSING", "NATIVE_MISSING"} for status in statuses):
        overall = "INCOMPLETE"
    elif all(status == "MATCH" for status in statuses):
        overall = "MATCH"
    else:
        overall = "INCOMPLETE"
    return {
        "schema_version": "system.orchestration_native_shadow_parity.v1",
        "authority": "shadow_only",
        "promotion_allowed": False,
        "status": overall,
        "asset_count": len(comparisons),
        "assets": dict(comparisons),
    }


__all__ = [
    "build_native_parity_report",
    "compare_native_report",
]
