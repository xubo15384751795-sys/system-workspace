#!/usr/bin/env python3
"""Verify the real default-path evidence window for data reliability.

This command is intentionally an evidence reader, not a synthetic run
generator.  Tests and manually invoked ``daily_run`` executions are excluded
unless their bundle explicitly records ``run_origin=launchd``.  A report is
therefore allowed to remain ``PENDING`` while launchd accumulates the required
observations; it can never be made complete by a unit-test count alone.

Examples::

    python3 scripts/verify_data_reliability_window.py
    python3 scripts/verify_data_reliability_window.py --output /tmp/window.json

Exit codes are 0 for COMPLETE, 1 for PENDING, and 2 for BLOCKED (malformed
evidence or an impossible window).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = "system.data_reliability_window.v1"
MINIMUM_DAYS = 14
DEFAULT_DEPLOYMENT_DATE = date(2026, 8, 19)
_RUN_ID_RE = re.compile(r"^daily_pipeline_")


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _walk_dicts(value: Any) -> Iterable[Mapping[str, Any]]:
    """Yield nested mappings without assuming one historical step shape."""
    if isinstance(value, Mapping):
        yield value
        for nested in value.values():
            yield from _walk_dicts(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_dicts(nested)


def _load_steps(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "steps.jsonl"
    if not path.is_file():
        return []
    steps: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            steps.append(value)
    return steps


def _provider_outcomes(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    outcomes: list[dict[str, Any]] = []
    for step in steps:
        for value in _walk_dicts(step):
            candidate = value.get("provider_outcome")
            if isinstance(candidate, Mapping):
                outcomes.append(dict(candidate))
            # Some older bundles put the provider outcome itself under the
            # step result.  Keep this compatibility read-only and conservative.
            if "provider_status" in value and (
                "failed_series" in value or "provider" in value or "route_policy" in value
            ):
                outcomes.append(dict(value))
    return outcomes


def _tag_text(record: Mapping[str, Any]) -> str:
    return " ".join(
        str(record.get(key) or "")
        for key in ("tag", "status", "provider_status", "operational_state", "reason")
    ).lower()


def _run_record(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    payload = _read_json(path)
    if payload is None:
        return None, f"invalid JSON: {path}"
    if payload.get("mode") != "daily_pipeline":
        return None, None
    # This is the critical boundary: historical/manual bundles with no origin
    # marker are not silently reclassified as scheduled evidence.
    if str(payload.get("run_origin") or "").strip().lower() != "launchd":
        return None, None
    run_id = str(payload.get("run_id") or path.parent.name)
    if not _RUN_ID_RE.match(run_id):
        return None, f"invalid daily run id: {path}"
    started = _timestamp(payload.get("started_at"))
    if started is None:
        return None, f"missing timezone-aware started_at: {path}"
    outcome = payload.get("outcome") if isinstance(payload.get("outcome"), Mapping) else {}
    steps = _load_steps(path.parent)
    provider_outcomes = _provider_outcomes(steps)
    all_outcomes = [dict(outcome), *provider_outcomes]
    statuses = {
        str(item.get("status") or item.get("provider_status") or "").lower()
        for item in all_outcomes
    }
    route_policies = [
        dict(item["route_policy"])
        for item in all_outcomes
        if isinstance(item.get("route_policy"), Mapping)
    ]
    return {
        "run_id": run_id,
        "path": str(path),
        "date": started.date().isoformat(),
        "started_at": started.isoformat().replace("+00:00", "Z"),
        "status": str(payload.get("status") or "unknown"),
        "tag": payload.get("tag"),
        "outcome": dict(outcome),
        "provider_statuses": sorted(statuses),
        "route_policies": route_policies,
        "provider_outcomes": provider_outcomes,
    }, None


def _iter_launchd_manifests(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    # Output/runs is the canonical run-bundle surface.  Data/system_learning
    # contains derived copies and must not count a run twice.
    for path in sorted((root / "Output" / "runs").glob("daily_pipeline_*/manifest.json")):
        record, error = _run_record(path)
        if error:
            errors.append(error)
        if record is not None:
            records.append(record)
    return records, errors


def _consecutive_days(days: set[date]) -> int:
    best = current = 0
    previous: date | None = None
    for day in sorted(days):
        if previous is not None and day == previous + timedelta(days=1):
            current += 1
        else:
            current = 1
        best = max(best, current)
        previous = day
    return best


def _has_provider_failure(record: Mapping[str, Any]) -> bool:
    outcome = record.get("outcome") if isinstance(record.get("outcome"), Mapping) else {}
    statuses = set(record.get("provider_statuses") or [])
    return bool(
        statuses
        & {
            "provider_failed_no_acceptable_fallback",
            "reused_after_provider_failure",
            "environmentally_blocked",
        }
        or outcome.get("execution_status") in {"FAILED", "FAILURE"}
    )


def _has_fallback(record: Mapping[str, Any]) -> bool:
    outcome = record.get("outcome") if isinstance(record.get("outcome"), Mapping) else {}
    if outcome.get("provider_status") in {
        "partial_provider_success",
        "reused_after_provider_failure",
        "reused_same_content",
    }:
        return True
    for item in record.get("provider_outcomes") or []:
        if item.get("fallback_used") or item.get("status") in {
            "partial_provider_success",
            "reused_after_provider_failure",
            "reused_same_content",
        }:
            return True
    return any("fallback" in _tag_text(record) or "carry" in _tag_text(record) for _ in [0])


def _has_stale_or_expiry(record: Mapping[str, Any]) -> bool:
    outcome = record.get("outcome") if isinstance(record.get("outcome"), Mapping) else {}
    if outcome.get("provider_cache_within_grace") is False:
        return True
    if outcome.get("operational_state") == "COMPLETED_BLOCKED":
        return True
    text = _tag_text(record)
    return any(token in text for token in ("stale", "cache_expir", "carry_forward"))


def _has_schema_or_parity(record: Mapping[str, Any], parity_reports: list[Path]) -> bool:
    text = _tag_text(record)
    if any(token in text for token in ("schema", "parity")):
        return True
    for path in parity_reports:
        payload = _read_json(path)
        if not payload:
            continue
        if payload.get("schema_version") == "system.provider_parity_report.v1":
            return True
    return False


def _has_recovery(records: list[Mapping[str, Any]], index: int) -> bool:
    if index <= 0:
        return False
    current = records[index]
    outcome = current.get("outcome") if isinstance(current.get("outcome"), Mapping) else {}
    current_ok = (
        str(current.get("status")) == "success"
        and outcome.get("execution_status") in {"SUCCESS", "DEGRADED"}
    )
    if not current_ok:
        return False
    previous = records[index - 1]
    previous_outcome = previous.get("outcome") if isinstance(previous.get("outcome"), Mapping) else {}
    return bool(
        str(previous.get("status")) != "success"
        or previous_outcome.get("execution_status") in {"FAILED", "FAILURE"}
        or previous_outcome.get("operational_state") in {"SYSTEM_FAILED", "COMPLETED_BLOCKED"}
    )


def build_window_report(
    root: Path | str,
    *,
    deployment_date: date = DEFAULT_DEPLOYMENT_DATE,
    minimum_days: int = MINIMUM_DAYS,
) -> dict[str, Any]:
    """Build a read-only report from explicitly marked launchd bundles."""
    workspace = Path(root).resolve()
    records, errors = _iter_launchd_manifests(workspace)
    records = [
        record
        for record in records
        if date.fromisoformat(str(record["date"])) >= deployment_date
    ]
    records.sort(key=lambda item: (item["started_at"], item["run_id"]))
    parity_reports = sorted((workspace / "Data" / "harvester" / "provider_parity").glob("*.json"))
    days = {date.fromisoformat(str(record["date"])) for record in records}
    scenario_by_run = {
        record["run_id"]: {
            "provider_failure": _has_provider_failure(record),
            "fallback_or_carry_forward": _has_fallback(record),
            "cache_expiry_or_stale": _has_stale_or_expiry(record),
            "schema_drift_or_parity": _has_schema_or_parity(record, parity_reports),
        }
        for record in records
    }
    for index, record in enumerate(records):
        scenario_by_run[record["run_id"]]["recovery"] = _has_recovery(records, index)
    scenarios = {
        name: any(values.get(name) for values in scenario_by_run.values())
        for name in (
            "provider_failure",
            "fallback_or_carry_forward",
            "cache_expiry_or_stale",
            "schema_drift_or_parity",
            "recovery",
        )
    }
    consecutive = _consecutive_days(days)
    blockers = list(errors)
    if errors:
        status = "BLOCKED"
    elif consecutive >= minimum_days and all(scenarios.values()):
        status = "COMPLETE"
    else:
        status = "PENDING"
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "authority": "default_launchd_evidence_only",
        "deployment_date": deployment_date.isoformat(),
        "minimum_days": minimum_days,
        "observed_runs": len(records),
        "observed_days": len(days),
        "consecutive_days": consecutive,
        "scenarios": scenarios,
        "scenario_by_run": scenario_by_run,
        "blockers": blockers,
        "runs": records,
        "parity_reports": [str(path) for path in parity_reports],
        "note": (
            "Tests, manual runs, and a single successful run do not satisfy this window. "
            "The report remains pending until the real launchd path supplies the evidence."
        ),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--since", type=date.fromisoformat, default=DEFAULT_DEPLOYMENT_DATE)
    parser.add_argument("--minimum-days", type=int, default=MINIMUM_DAYS)
    parser.add_argument("--output", type=Path, help="Optional JSON report path; default is read-only stdout")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.minimum_days < 1:
        print("--minimum-days must be positive", file=sys.stderr)
        return 2
    report = build_window_report(
        args.root,
        deployment_date=args.since,
        minimum_days=args.minimum_days,
    )
    serialized = json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
        print(args.output)
    else:
        print(serialized, end="")
    return {"COMPLETE": 0, "PENDING": 1, "BLOCKED": 2}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
