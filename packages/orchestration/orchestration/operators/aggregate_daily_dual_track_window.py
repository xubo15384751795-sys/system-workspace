#!/usr/bin/env python3
"""Aggregate isolated legacy/native parity reports into a one-week gate.

This command is read-only with respect to the two run tracks.  It reads the
reports produced by ``run_daily_dual_track.py`` and returns ``MATCH`` only
when every observation is a real execution, every parity dimension matches,
the observations cover consecutive UTC dates, and the window has at least
seven observations.  It never launches a runner and never enables promotion.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from verity.runtime.runtime_io import ROOT

SCHEMA_VERSION = "system.orchestration_dual_track_window.v1"
EXECUTION_SCHEMA_VERSION = "system.orchestration_dual_track_execution.v1"
PROMOTION_ALLOWED = False
DEFAULT_REPORT = ROOT / "Output" / "state" / "health" / "native_current_dual_track_window.json"
_DIMENSIONS = (
    "inputs",
    "identity",
    "steps",
    "canonical_lineage",
    "publication",
    "generation_surfaces",
)


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


def _observation_date(payload: dict[str, Any]) -> date | None:
    explicit_value = payload.get("observation_date")
    explicit_date: date | None = None
    if explicit_value is not None:
        if not isinstance(explicit_value, str) or not explicit_value:
            return None
        try:
            explicit_date = date.fromisoformat(explicit_value)
        except ValueError:
            return None

    observed_at_value = payload.get("observed_at")
    observed_at_date: date | None = None
    if observed_at_value is not None:
        if not isinstance(observed_at_value, str) or not observed_at_value:
            return None
        try:
            parsed_observed_at = datetime.fromisoformat(
                observed_at_value.replace("Z", "+00:00")
            )
        except ValueError:
            return None
        if parsed_observed_at.tzinfo is None:
            return None
        observed_at_date = parsed_observed_at.astimezone(UTC).date()

    if explicit_date is not None and observed_at_date is not None:
        if explicit_date != observed_at_date:
            return None
        return explicit_date
    if explicit_date is not None:
        return explicit_date
    if observed_at_date is not None:
        return observed_at_date
    return None


def _identity_signature(parity: dict[str, Any]) -> tuple[str, str, str] | None:
    identity = parity.get("identity_parity")
    if not isinstance(identity, dict):
        return None
    plan = identity.get("plan_digest")
    releases = identity.get("release_ids")
    vintages = identity.get("vintage_clocks")
    if not isinstance(plan, dict) or not isinstance(releases, dict) or not isinstance(vintages, dict):
        return None
    values: list[str] = []
    for value in (plan, releases, vintages):
        values.append(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return tuple(values)  # type: ignore[return-value]


def evaluate_window(
    report_paths: list[Path],
    *,
    minimum_observations: int = 7,
) -> dict[str, Any]:
    """Evaluate a consecutive, real-execution dual-track observation window."""
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
        observed_date = _observation_date(payload)
        parity = payload.get("parity")
        parity_status = parity.get("status") if isinstance(parity, dict) else None
        dimensions = parity.get("dimensions") if isinstance(parity, dict) else None
        dimensions_match = isinstance(dimensions, dict) and all(
            dimensions.get(name) == "MATCH" for name in _DIMENSIONS
        )
        signature = _identity_signature(parity) if isinstance(parity, dict) else None
        entry = {
            "path": str(path),
            "schema_version": payload.get("schema_version"),
            "observation_date": observed_date.isoformat() if observed_date else None,
            "status": str(payload.get("status") or ""),
            "parity_status": str(parity_status or ""),
            "execution_requested": bool(payload.get("execution_requested")),
            "writes_performed": bool(payload.get("writes_performed")),
            "authority": payload.get("authority"),
            "promotion_allowed": payload.get("promotion_allowed"),
            "dimensions_match": dimensions_match,
            "identity_signature": signature,
        }
        entries.append(entry)

    dates = sorted(
        date.fromisoformat(entry["observation_date"])
        for entry in entries
        if isinstance(entry.get("observation_date"), str)
    )
    duplicate_dates = sorted(
        {item.isoformat() for item in dates if dates.count(item) > 1}
    )
    missing_dates: list[str] = []
    if dates:
        expected = {
            dates[0] + timedelta(days=offset)
            for offset in range((dates[-1] - dates[0]).days + 1)
        }
        missing_dates = sorted(item.isoformat() for item in expected - set(dates))

    unsafe_entries = [
        entry["path"]
        for entry in entries
        if entry["schema_version"] != EXECUTION_SCHEMA_VERSION
        or entry["status"] != "MATCH"
        or entry["authority"] != "shadow_only"
        or entry["promotion_allowed"] is not False
        or not entry["execution_requested"]
        or not entry["writes_performed"]
        or not entry["observation_date"]
        or entry["parity_status"] != "MATCH"
        or not entry["dimensions_match"]
        or entry["identity_signature"] is None
    ]
    statuses = {entry["status"] for entry in entries}
    mismatch_present = "MISMATCH" in statuses or any(
        entry["parity_status"] == "MISMATCH" for entry in entries
    )
    signatures = {
        entry["identity_signature"]
        for entry in entries
        if entry["identity_signature"] is not None
    }

    if errors:
        status = "INCOMPLETE"
        reason = "invalid_observation_report"
    elif mismatch_present or len(signatures) > 1:
        status = "MISMATCH"
        reason = "parity_mismatch_or_identity_drift"
    elif unsafe_entries:
        status = "INCOMPLETE"
        reason = "observation_missing_real_execution_or_required_parity"
    elif len(dates) < minimum_observations:
        status = "INCOMPLETE"
        reason = "observation_window_short"
    elif duplicate_dates or missing_dates:
        status = "INCOMPLETE"
        reason = "observation_dates_not_consecutive"
    else:
        status = "MATCH"
        reason = "minimum_consecutive_window_complete"

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
        help="one JSON report produced by run_daily_dual_track.py; repeat per UTC day",
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
