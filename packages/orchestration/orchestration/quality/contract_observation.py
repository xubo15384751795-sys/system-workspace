"""Count consecutive launchd days with a clean structural contract.

This module records evidence for the existing shadow observation window.  It
never writes ``configs/provider_release_policy.yaml`` and never flips
``data_contract_mode`` to enforce.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

SCHEMA_VERSION = "system.data_contract_observation.v1"
REQUIRED_CLEAN_DAYS = 3
CLEAN_STATUSES = frozenset({"PASS", "WARN"})
STATE_FILENAME = "data_contract_observation.json"
QUALITY_REPORT_RELATIVE = Path(
    "Data/harvester/exports/latest/quality_reports/cross_asset_daily_panel.quality.json"
)


def observation_state_path(output_root: Path) -> Path:
    return output_root / "health" / STATE_FILENAME


def _parse_utc_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).date()


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def empty_observation_state() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "shadow",
        "policy_mode": "shadow",
        "consecutive_clean_days": 0,
        "required_clean_days": REQUIRED_CLEAN_DAYS,
        "last_counted_date": None,
        "ready_for_enforce_review": False,
        "enforce_changed": False,
        "reset_reason": None,
        "last_event": "uninitialized",
        "contract_status": None,
        "source": None,
        "run_id": None,
    }


def read_observation_state(output_root: Path) -> dict[str, Any]:
    path = observation_state_path(output_root)
    if not path.is_file():
        return empty_observation_state()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        state = empty_observation_state()
        state["last_event"] = "previous_state_unreadable"
        return state
    if not isinstance(payload, dict):
        state = empty_observation_state()
        state["last_event"] = "previous_state_invalid"
        return state
    state = empty_observation_state()
    state.update(payload)
    state["schema_version"] = SCHEMA_VERSION
    state["mode"] = "shadow"
    state["enforce_changed"] = False
    state["required_clean_days"] = REQUIRED_CLEAN_DAYS
    try:
        state["consecutive_clean_days"] = int(state.get("consecutive_clean_days") or 0)
    except (TypeError, ValueError):
        state["consecutive_clean_days"] = 0
    return state


def write_observation_state(state: Mapping[str, Any], *, output_root: Path) -> Path:
    path = observation_state_path(output_root)
    payload = dict(state)
    payload["schema_version"] = SCHEMA_VERSION
    payload["mode"] = "shadow"
    payload["enforce_changed"] = False
    _atomic_write_json(path, payload)
    return path


def load_latest_contract_snapshot(workspace_root: Path) -> dict[str, Any]:
    path = workspace_root / QUALITY_REPORT_RELATIVE
    if not path.is_file():
        return {
            "report_missing": True,
            "status": None,
            "mode": None,
            "generated_at": None,
            "enforced": False,
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "report_missing": True,
            "status": None,
            "mode": None,
            "generated_at": None,
            "enforced": False,
        }
    contract = payload.get("data_contract") if isinstance(payload, dict) else None
    if not isinstance(contract, dict):
        contract = {}
    return {
        "report_missing": False,
        "status": contract.get("status"),
        "mode": contract.get("mode"),
        "generated_at": payload.get("generated_at") if isinstance(payload, dict) else None,
        "enforced": bool(contract.get("enforced")),
    }


def advance_observation_window(
    previous: Mapping[str, Any] | None,
    *,
    day: date,
    source: str,
    exit_code: int,
    contract_status: str | None,
    report_missing: bool,
    report_day: date | None,
    run_id: str | None = None,
    policy_mode: str | None = None,
) -> dict[str, Any]:
    """Return the next shadow observation state. Never enables enforce."""
    state = empty_observation_state()
    if previous:
        state.update(dict(previous))
    state["schema_version"] = SCHEMA_VERSION
    state["mode"] = "shadow"
    state["enforce_changed"] = False
    state["required_clean_days"] = REQUIRED_CLEAN_DAYS
    state["run_id"] = run_id
    state["source"] = source
    state["contract_status"] = contract_status
    state["policy_mode"] = str(policy_mode or state.get("policy_mode") or "shadow")
    previous_days = int(state.get("consecutive_clean_days") or 0)
    previous_date = _parse_utc_date(state.get("last_counted_date"))

    if source != "launchd":
        state["last_event"] = "ignored_non_launchd"
        state["reset_reason"] = None
        state["ready_for_enforce_review"] = previous_days >= REQUIRED_CLEAN_DAYS
        return state

    if report_missing:
        return _reset(state, reason="missing_report")
    if report_day != day:
        return _reset(state, reason="report_not_from_run_day")
    if exit_code != 0:
        return _reset(state, reason="launchd_path_failure")
    status = str(contract_status or "").upper()
    if status == "BLOCK":
        return _reset(state, reason="contract_block")
    if status not in CLEAN_STATUSES:
        return _reset(state, reason="contract_status_unusable")

    if previous_date == day:
        consecutive = previous_days or 1
        event = "same_day_rerun"
    elif previous_date == day - timedelta(days=1):
        consecutive = previous_days + 1
        event = "consecutive_clean_day"
    else:
        consecutive = 1
        event = "clean_day_start"

    state["consecutive_clean_days"] = consecutive
    state["last_counted_date"] = day.isoformat()
    state["ready_for_enforce_review"] = consecutive >= REQUIRED_CLEAN_DAYS
    state["reset_reason"] = None
    state["last_event"] = event
    return state


def _reset(state: dict[str, Any], *, reason: str) -> dict[str, Any]:
    state["consecutive_clean_days"] = 0
    state["last_counted_date"] = None
    state["ready_for_enforce_review"] = False
    state["reset_reason"] = reason
    state["last_event"] = "reset"
    return state


def record_launchd_observation(
    *,
    workspace_root: Path,
    output_root: Path,
    outcome: Mapping[str, Any],
    source: str | None,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    """Advance and persist the window. Failures must be handled by the caller."""
    timestamp = observed_at or datetime.now(UTC)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    timestamp = timestamp.astimezone(UTC)
    snapshot = load_latest_contract_snapshot(workspace_root)
    previous = read_observation_state(output_root)
    state = advance_observation_window(
        previous,
        day=timestamp.date(),
        source=source or os.environ.get("SYSTEM_RUN_ORIGIN", "manual"),
        exit_code=int(outcome.get("exit_code") or 0),
        contract_status=None if snapshot["status"] is None else str(snapshot["status"]),
        report_missing=bool(snapshot["report_missing"]),
        report_day=_parse_utc_date(snapshot.get("generated_at")),
        run_id=str(outcome.get("run_id") or "") or None,
        policy_mode=None if snapshot["mode"] is None else str(snapshot["mode"]),
    )
    write_observation_state(state, output_root=output_root)
    return state


__all__ = [
    "REQUIRED_CLEAN_DAYS",
    "SCHEMA_VERSION",
    "advance_observation_window",
    "empty_observation_state",
    "load_latest_contract_snapshot",
    "observation_state_path",
    "read_observation_state",
    "record_launchd_observation",
    "write_observation_state",
]
