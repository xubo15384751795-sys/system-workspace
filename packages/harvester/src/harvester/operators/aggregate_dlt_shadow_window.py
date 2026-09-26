#!/usr/bin/env python3
"""Aggregate real provider-capture dlt parity reports into a window gate.

This command is deliberately downstream of acquisition and dlt execution. It
does not fetch a provider, mutate a cache, or promote a source.  Reports made
from a local cache snapshot are accepted as useful shadow evidence elsewhere,
but fail this gate because they do not prove a real daily capture window.

The gate requires, for every observation:

* a supported dlt parity report schema and ``MATCH`` status;
* shadow-only authority and ``promotion_allowed: false``;
* a real provider-capture provenance record;
* matching UTC observation date and timestamp;
* a stable schema contract and series set;
* capture manifest SHA-256 matches the actual source bytes;
* persisted incremental state and an explicit idempotence check; and
* at least seven consecutive UTC dates.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from verity.runtime.runtime_io import ROOT

SCHEMA_VERSION = "system.harvester_dlt_shadow_window.v1"
PROMOTION_ALLOWED = False
DEFAULT_REPORT = ROOT / "Output" / "state" / "health" / "dlt_shadow_window.json"
_SUPPORTED_REPORT_SCHEMAS = frozenset(
    {
        "system.harvester_dlt_shadow_parity.v1",
        "system.harvester_dlt_series_shadow.v1",
    }
)
_REQUIRED_CAPTURE_KIND = "daily_provider_capture"
_CONTRACTS = frozenset({"evolve", "freeze", "discard", "discard_value"})
_CAPTURE_MANIFEST_SCHEMA = "system.harvester.provider_capture.v1"


def _read_report(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return None, f"read_error:{type(exc).__name__}"
    except json.JSONDecodeError:
        return None, "invalid_json"
    if not isinstance(payload, dict):
        return None, "not_object"
    return payload, None


def _parse_utc_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC).date()


def _observation_date(payload: dict[str, Any]) -> date | None:
    explicit = payload.get("observation_date")
    explicit_date: date | None = None
    if explicit is not None:
        if not isinstance(explicit, str) or not explicit:
            return None
        try:
            explicit_date = date.fromisoformat(explicit)
        except ValueError:
            return None

    observed_at_date = _parse_utc_date(payload.get("observed_at"))
    if payload.get("observed_at") is not None and observed_at_date is None:
        return None
    if explicit_date is not None and observed_at_date is not None:
        return explicit_date if explicit_date == observed_at_date else None
    return explicit_date or observed_at_date


def _capture_fields(payload: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    capture = payload.get("capture")
    if not isinstance(capture, dict):
        return None, None, None
    capture_id = capture.get("capture_id")
    capture_kind = capture.get("capture_kind")
    return (
        capture_id.strip() if isinstance(capture_id, str) and capture_id.strip() else None,
        capture_kind.strip() if isinstance(capture_kind, str) and capture_kind.strip() else None,
        capture.get("schema_version")
        if isinstance(capture.get("schema_version"), str)
        else None,
    )


def _series_signature(payload: dict[str, Any]) -> tuple[str, ...] | None:
    schema = payload.get("schema_version")
    if schema == "system.harvester_dlt_shadow_parity.v1":
        provider = payload.get("provider")
        series_id = payload.get("series_id")
        if not isinstance(provider, str) or not provider or not isinstance(series_id, str) or not series_id:
            return None
        if payload.get("execution_parity") != "MATCH":
            return None
        return (f"{provider}:{series_id}",)

    if schema == "system.harvester_dlt_series_shadow.v1":
        series = payload.get("series")
        if not isinstance(series, dict) or not series:
            return None
        if any(
            not isinstance(item, dict) or item.get("status") != "MATCH"
            for item in series.values()
        ):
            return None
        return tuple(sorted(str(series_id) for series_id in series))

    return None


def evaluate_window(
    report_paths: list[Path],
    *,
    minimum_observations: int = 7,
) -> dict[str, Any]:
    """Evaluate a consecutive real-capture dlt observation window."""
    if minimum_observations < 1:
        raise ValueError("minimum_observations must be positive")

    entries: list[dict[str, Any]] = []
    errors: list[str] = []
    for raw_path in report_paths:
        path = raw_path.expanduser().resolve()
        payload, error = _read_report(path)
        if error is not None or payload is None:
            errors.append(f"{path}:{error or 'invalid'}")
            continue

        capture_id, capture_kind, capture_schema = _capture_fields(payload)
        observation = _observation_date(payload)
        signature = _series_signature(payload)
        incremental = payload.get("incremental_state")
        if not isinstance(incremental, dict):
            incremental = {}
        entry = {
            "path": str(path),
            "schema_version": payload.get("schema_version"),
            "provider": payload.get("provider"),
            "status": str(payload.get("status") or ""),
            "authority": payload.get("authority"),
            "promotion_allowed": payload.get("promotion_allowed"),
            "observation_date": observation.isoformat() if observation else None,
            "capture_id": capture_id,
            "capture_kind": capture_kind,
            "capture_schema": capture_schema,
            "schema_contract": payload.get("schema_contract"),
            "payload_digest_verified": payload.get("payload_digest_verified") is True,
            "series_signature": signature,
            "state_persisted": incremental.get("state_persisted") is True,
            "idempotence_verified": incremental.get("idempotence_verified") is True,
        }
        entries.append(entry)

    dates = sorted(
        date.fromisoformat(entry["observation_date"])
        for entry in entries
        if isinstance(entry.get("observation_date"), str)
    )
    duplicate_dates = sorted({item.isoformat() for item in dates if dates.count(item) > 1})
    missing_dates: list[str] = []
    if dates:
        expected = {
            dates[0] + timedelta(days=offset)
            for offset in range((dates[-1] - dates[0]).days + 1)
        }
        missing_dates = sorted(item.isoformat() for item in expected - set(dates))

    capture_ids = [entry["capture_id"] for entry in entries if entry["capture_id"]]
    duplicate_capture_ids = sorted(
        {item for item in capture_ids if capture_ids.count(item) > 1}
    )
    unsafe_entries = [
        entry["path"]
        for entry in entries
        if entry["schema_version"] not in _SUPPORTED_REPORT_SCHEMAS
        or entry["status"] != "MATCH"
        or entry["authority"] != "shadow_only"
        or entry["promotion_allowed"] is not False
        or not entry["observation_date"]
        or entry["capture_kind"] != _REQUIRED_CAPTURE_KIND
        or entry["capture_schema"] != _CAPTURE_MANIFEST_SCHEMA
        or not entry["capture_id"]
        or entry["schema_contract"] not in _CONTRACTS
        or not entry["payload_digest_verified"]
        or entry["series_signature"] is None
        or not entry["state_persisted"]
        or not entry["idempotence_verified"]
    ]

    statuses = {entry["status"] for entry in entries}
    signatures = {
        (entry["schema_version"], entry["series_signature"])
        for entry in entries
        if entry["series_signature"] is not None
    }
    contracts = {
        entry["schema_contract"]
        for entry in entries
        if entry["schema_contract"] in _CONTRACTS
    }
    mismatch_present = "MISMATCH" in statuses or len(signatures) > 1 or len(contracts) > 1

    if errors:
        status = "INCOMPLETE"
        reason = "invalid_observation_report"
    elif mismatch_present:
        status = "MISMATCH"
        reason = "parity_mismatch_or_schema_identity_drift"
    elif unsafe_entries:
        status = "INCOMPLETE"
        reason = "observation_missing_real_capture_or_incremental_evidence"
    elif duplicate_capture_ids:
        status = "INCOMPLETE"
        reason = "duplicate_capture_ids"
    elif len(dates) < minimum_observations:
        status = "INCOMPLETE"
        reason = "observation_window_short"
    elif duplicate_dates or missing_dates:
        status = "INCOMPLETE"
        reason = "observation_dates_not_consecutive"
    else:
        status = "MATCH"
        reason = "minimum_consecutive_real_capture_window_complete"

    return {
        "schema_version": SCHEMA_VERSION,
        "authority": "shadow_only",
        "promotion_allowed": PROMOTION_ALLOWED,
        "status": status,
        "reason": reason,
        "minimum_observations": minimum_observations,
        "observation_count": len(entries),
        "window_start": dates[0].isoformat() if dates else None,
        "window_end": dates[-1].isoformat() if dates else None,
        "duplicate_dates": duplicate_dates,
        "missing_dates": missing_dates,
        "duplicate_capture_ids": duplicate_capture_ids,
        "unsafe_entries": unsafe_entries,
        "errors": errors,
        "observations": entries,
    }


def _write_json_atomically(path: Path, payload: dict[str, Any]) -> None:
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
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        temporary_path.replace(path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--observation-report",
        type=Path,
        action="append",
        required=True,
        help="one capture-backed dlt parity report; repeat once per UTC date",
    )
    parser.add_argument("--min-observations", type=int, default=7)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    result = evaluate_window(
        args.observation_report,
        minimum_observations=args.min_observations,
    )
    output_path = args.report if args.report.is_absolute() else ROOT / args.report
    _write_json_atomically(output_path, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "MATCH" else 2


if __name__ == "__main__":
    raise SystemExit(main())
