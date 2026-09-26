#!/usr/bin/env python3
"""Verify the real scheduled-path evidence window for data reliability.

This command is intentionally an evidence reader, not a synthetic run
generator. Tests and manually invoked ``daily_run`` executions are excluded
unless their bundle explicitly records the scheduler-neutral identity
``trigger_kind=scheduled``, an accepted ``scheduler_id``, and the accepted
``release_id``. The legacy ``run_origin`` field is never used for
qualification.

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

SCHEMA_VERSION = "system.data_reliability_window.v2"
MINIMUM_DAYS = 14
# Stage 0–4 were all in place when the repaired release was accepted on
# 2026-08-22.  The manual repair itself is setup evidence; the first real
# scheduled run with an accepted scheduler/release identity on/after this
# date is the first eligible observation.
DEFAULT_DEPLOYMENT_DATE = date(2026, 8, 22)
_RUN_ID_RE = re.compile(r"^daily_pipeline_")
DEFAULT_ACCEPTED_SCHEDULERS = frozenset({"com.system.daily-run"})
RELIABILITY_CONTRACT = "governance/reliability_window_contract.yaml"

_PROVIDER_FAILURE_STATUSES = frozenset(
    {
        "provider_failed_no_acceptable_fallback",
        "reused_after_provider_failure",
        "environmentally_blocked",
    }
)
_FALLBACK_STATUSES = frozenset(
    {
        "partial_provider_success",
        "reused_after_provider_failure",
        "reused_same_content",
    }
)
_COMPLETED_STEP_STATUSES = frozenset(
    {"success", "degraded", "completed", "committed", "finalized", "reused"}
)


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


def _run_record(
    path: Path,
    *,
    accepted_schedulers: frozenset[str],
    accepted_release: str | None,
) -> tuple[dict[str, Any] | None, str | None]:
    payload = _read_json(path)
    if payload is None:
        return None, f"invalid JSON: {path}"
    if payload.get("mode") != "daily_pipeline":
        return None, None
    identity = payload.get("execution_identity")
    if not isinstance(identity, Mapping):
        identity = {}
    identity = {**payload, **dict(identity)}
    trigger_kind = str(identity.get("trigger_kind") or "").strip().lower()
    scheduler_id = str(identity.get("scheduler_id") or "").strip()
    release_id = str(identity.get("release_id") or "").strip()
    # This is the critical boundary: historical/manual bundles without the
    # explicit identity are not silently reclassified as scheduled evidence.
    if trigger_kind != "scheduled":
        return None, None
    if scheduler_id not in accepted_schedulers:
        return None, None
    if not accepted_release or release_id != accepted_release:
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
    step_statuses = {
        str(step.get("step") or ""): str(step.get("status") or "").lower()
        for step in steps
        if step.get("step")
    }
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
        "trigger_kind": trigger_kind,
        "scheduler_kind": str(identity.get("scheduler_kind") or "").strip().lower(),
        "scheduler_id": scheduler_id,
        "schedule_id": str(identity.get("schedule_id") or "").strip(),
        "trigger_id": str(identity.get("trigger_id") or "").strip(),
        "host_id": str(identity.get("host_id") or "").strip(),
        "release_id": release_id,
        "outcome": dict(outcome),
        "provider_statuses": sorted(statuses),
        "route_policies": route_policies,
        "provider_outcomes": provider_outcomes,
        "step_statuses": step_statuses,
    }, None


def _iter_scheduled_manifests(
    root: Path,
    *,
    accepted_schedulers: frozenset[str],
    accepted_release: str | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    # Output/runs is the canonical run-bundle surface.  Data/system_learning
    # contains derived copies and must not count a run twice.
    for path in sorted((root / "Output" / "runs").glob("daily_pipeline_*/manifest.json")):
        record, error = _run_record(
            path,
            accepted_schedulers=accepted_schedulers,
            accepted_release=accepted_release,
        )
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


def _has_failed_provider_attempt(record: Mapping[str, Any]) -> bool:
    """Detect a failed provider attempt even when a later fallback succeeds.

    The run-level provider status intentionally remains ``refreshed`` when a
    chain recovers the requested series.  The attempt-level record is still
    required scenario evidence, but it must not affect whether the committed
    core run qualifies for the continuity window.
    """
    for provider_outcome in record.get("provider_outcomes") or []:
        if not isinstance(provider_outcome, Mapping):
            continue
        series_attempts = provider_outcome.get("series_attempts")
        if not isinstance(series_attempts, Mapping):
            continue
        for attempts in series_attempts.values():
            if not isinstance(attempts, list):
                continue
            for attempt in attempts:
                if not isinstance(attempt, Mapping):
                    continue
                outcome = str(attempt.get("outcome") or "").strip().lower()
                failure_class = str(attempt.get("failure_class") or "").strip().upper()
                error = str(attempt.get("error") or "").strip()
                if outcome in {"failed", "failure", "error"}:
                    return True
                if not outcome or outcome not in {"success", "ok"}:
                    if error or (failure_class and failure_class != "NONE"):
                        return True
    return False


def _has_provider_failure(record: Mapping[str, Any]) -> bool:
    outcome = record.get("outcome") if isinstance(record.get("outcome"), Mapping) else {}
    statuses = {str(status).lower() for status in record.get("provider_statuses") or []}
    provider_status = str(outcome.get("provider_status") or "").lower()
    if statuses & _PROVIDER_FAILURE_STATUSES or provider_status in _PROVIDER_FAILURE_STATUSES:
        return True

    # A series can fail and recover through a later provider without leaving a
    # failed_series value at the aggregate level.  Preserve explicit failed
    # series as scenario evidence when present.
    for provider_outcome in [outcome, *(record.get("provider_outcomes") or [])]:
        if isinstance(provider_outcome, Mapping) and provider_outcome.get("failed_series"):
            return True
    return _has_failed_provider_attempt(record)


def _has_fallback(record: Mapping[str, Any]) -> bool:
    outcome = record.get("outcome") if isinstance(record.get("outcome"), Mapping) else {}
    if str(outcome.get("provider_status") or "").lower() in _FALLBACK_STATUSES:
        return True
    for item in record.get("provider_outcomes") or []:
        if item.get("fallback_used") or str(item.get("status") or "").lower() in _FALLBACK_STATUSES:
            return True
    return any("fallback" in _tag_text(record) or "carry" in _tag_text(record) for _ in [0])


def _has_stale_or_expiry(record: Mapping[str, Any]) -> bool:
    outcome = record.get("outcome") if isinstance(record.get("outcome"), Mapping) else {}
    if outcome.get("provider_cache_within_grace") is False:
        return True
    if outcome.get("operational_state") == "COMPLETED_BLOCKED":
        return True

    # Newer bundles keep cache and availability facts on the provider outcome,
    # rather than duplicating them into RunOutcome.  Read those fields here as
    # scenario evidence only; this function never changes qualification.
    for provider_outcome in record.get("provider_outcomes") or []:
        if not isinstance(provider_outcome, Mapping):
            continue
        if provider_outcome.get("cache_within_grace") is False:
            return True
        availability = provider_outcome.get("availability")
        if isinstance(availability, Mapping):
            state = str(availability.get("state") or "").strip().upper()
            if state in {"STALE", "EXPIRED", "CACHE_EXPIRED"}:
                return True
        provider_status = str(provider_outcome.get("status") or "").strip().lower()
        if provider_status in {
            "reused_after_provider_failure",
            "reused_same_content",
            "environmentally_blocked",
        }:
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


def _harvester_committed(record: Mapping[str, Any]) -> bool:
    """Return the typed evidence that the Harvester publication committed.

    ``publish_status`` is the runtime's commit authority.  Requiring the
    explicit harvester step as well prevents a manifest-only or truncated
    bundle from being counted as a real scheduled observation.
    """
    outcome = record.get("outcome") if isinstance(record.get("outcome"), Mapping) else {}
    publish_status = str(outcome.get("publish_status") or "").upper()
    harvester_status = str((record.get("step_statuses") or {}).get("harvester") or "").lower()
    return publish_status == "COMMITTED" and harvester_status in _COMPLETED_STEP_STATUSES


def _generation_admission(root: Path, record: Mapping[str, Any]) -> dict[str, Any] | None:
    """Read the committed generation admission for strict target proof."""
    outcome = record.get("outcome") if isinstance(record.get("outcome"), Mapping) else {}
    generation_id = str(outcome.get("generation_id") or record.get("run_id") or "").strip()
    if not generation_id:
        return None
    path = root / "Output" / "generations" / generation_id / "admission.json"
    return _read_json(path) if path.is_file() else None


def _strict_formal_requirements(root: Path, record: Mapping[str, Any]) -> dict[str, bool]:
    """Evaluate the authority-bearing requirements for a target proof day.

    The ordinary evidence reader remains intentionally compatible with older
    scheduled bundles.  Formal target proof is stricter: it must observe the
    generation admission and cannot count a diagnostic or merely committed
    but provider-conditional run.
    """
    outcome = record.get("outcome") if isinstance(record.get("outcome"), Mapping) else {}
    admission = _generation_admission(root, record) or {}
    provider_decision = str(
        admission.get("provider_decision")
        or outcome.get("provider_decision")
        or ""
    ).strip().upper()
    freshness = str(
        admission.get("freshness_verdict")
        or outcome.get("freshness_verdict")
        or ""
    ).strip().upper()
    authority = str(
        admission.get("authority_verdict")
        or admission.get("decision_authority_verdict")
        or ""
    ).strip().upper()
    outcome_authority = str(outcome.get("authority_mode") or "").strip().lower()
    generation_id = str(outcome.get("generation_id") or "").strip()
    generation_manifest = (
        root / "Output" / "generations" / generation_id / "manifest.json"
        if generation_id
        else None
    )
    return {
        "provider_decision_usable": provider_decision == "ALLOW",
        "freshness_usable": freshness == "PASS",
        "committed_generation": bool(
            generation_manifest
            and generation_manifest.is_file()
            and admission.get("generation_id") == generation_id
            and admission.get("can_publish") is True
        ),
        "authority_not_diagnostic_only": authority == "ALLOW"
        and outcome_authority == "authoritative"
        and admission.get("allows_decision_consumers") is True,
    }


def _core_chain_complete(record: Mapping[str, Any]) -> bool:
    """Use RunOutcome's fail-closed core-chain completion signal.

    The runtime marks a core chain complete only when execution succeeded and
    no required step failed or was blocked.  This intentionally does not
    infer completion from provider scenarios: a provider fallback is valid
    only when the runtime still records a complete core chain.
    """
    outcome = record.get("outcome") if isinstance(record.get("outcome"), Mapping) else {}
    explicit = str(outcome.get("core_chain_status") or "").upper()
    if outcome.get("failed_steps") or outcome.get("blocked_steps"):
        return False
    if explicit:
        return explicit in {"COMPLETE", "COMPLETED", "SUCCESS"}
    return bool(
        str(outcome.get("execution_status") or "").upper() == "SUCCESS"
        and not outcome.get("failed_steps")
        and not outcome.get("blocked_steps")
        and str(record.get("status") or "").lower() != "partial_failure"
    )


def _qualification(
    record: Mapping[str, Any],
    *,
    root: Path | None = None,
    formal_target: bool = False,
) -> dict[str, Any]:
    """Classify one run, optionally applying the strict target-proof gate."""
    harvester_committed = _harvester_committed(record)
    core_chain_complete = _core_chain_complete(record)
    provider_failure = _has_provider_failure(record)
    fallback = _has_fallback(record)
    reasons: list[str] = []
    if not harvester_committed:
        reasons.append("HARVESTER_NOT_COMMITTED")
    if not core_chain_complete:
        reasons.append("CORE_CHAIN_INCOMPLETE")
    formal_requirements = {
        "provider_decision_usable": True,
        "freshness_usable": True,
        "committed_generation": True,
        "authority_not_diagnostic_only": True,
    }
    if formal_target:
        formal_requirements = _strict_formal_requirements(root or Path.cwd(), record)
        for name, passed in formal_requirements.items():
            if not passed:
                reasons.append(name.upper())
    return {
        "qualified": harvester_committed
        and core_chain_complete
        and all(formal_requirements.values()),
        "harvester_committed": harvester_committed,
        "core_chain_complete": core_chain_complete,
        "formal_target": formal_target,
        "formal_requirements": formal_requirements,
        "provider_failure": provider_failure,
        "fallback_or_carry_forward": fallback,
        "provider_failure_with_fallback_qualified": bool(
            provider_failure and fallback and harvester_committed and core_chain_complete
        ),
        "reasons": reasons,
    }


def _workspace_carry_forward_is_stale(root: Path) -> bool:
    try:
        from workbench.measurement.freshness_validator import (
            evaluate_harvester_carry_forward,
        )
    except ImportError:
        from freshness_validator import evaluate_harvester_carry_forward

    result = evaluate_harvester_carry_forward(root=root, now=datetime.now(UTC))
    return bool(result.get("exceeds"))


def _read_reliability_contract(root: Path) -> dict[str, Any]:
    """Read the explicit scheduler/release qualification contract."""
    path = root / RELIABILITY_CONTRACT
    if not path.is_file():
        return {}
    try:
        import yaml
    except ImportError:
        return {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _has_recovery(
    records: list[Mapping[str, Any]],
    index: int,
    qualification_by_run: Mapping[str, Mapping[str, Any]] | None = None,
) -> bool:
    if index <= 0:
        return False
    current = records[index]
    previous = records[index - 1]
    current_qualification = (
        qualification_by_run.get(str(current["run_id"]))
        if qualification_by_run is not None
        else _qualification(current)
    )
    previous_qualification = (
        qualification_by_run.get(str(previous["run_id"]))
        if qualification_by_run is not None
        else _qualification(previous)
    )
    if not current_qualification or not current_qualification["qualified"]:
        return False
    return not previous_qualification["qualified"] if previous_qualification else False


def build_window_report(
    root: Path | str,
    *,
    deployment_date: date = DEFAULT_DEPLOYMENT_DATE,
    minimum_days: int = MINIMUM_DAYS,
    accepted_schedulers: Iterable[str] | None = None,
    accepted_release: str | None = None,
    formal_target: bool = False,
) -> dict[str, Any]:
    """Build a read-only report from explicitly identified scheduled bundles."""
    workspace = Path(root).resolve()
    contract = _read_reliability_contract(workspace)
    scheduler_set = frozenset(
        str(item).strip()
        for item in (
            accepted_schedulers
            if accepted_schedulers is not None
            else contract.get("accepted_schedulers", DEFAULT_ACCEPTED_SCHEDULERS)
        )
        if str(item).strip()
    )
    resolved_release = str(
        accepted_release
        if accepted_release is not None
        else contract.get("accepted_release") or ""
    ).strip() or None
    records, errors = _iter_scheduled_manifests(
        workspace,
        accepted_schedulers=scheduler_set or DEFAULT_ACCEPTED_SCHEDULERS,
        accepted_release=resolved_release,
    )
    records = [
        record
        for record in records
        if date.fromisoformat(str(record["date"])) >= deployment_date
    ]
    records.sort(key=lambda item: (item["started_at"], item["run_id"]))
    parity_reports = sorted((workspace / "Data" / "harvester" / "provider_parity").glob("*.json"))
    qualification_by_run = {
        record["run_id"]: _qualification(
            record,
            root=workspace,
            formal_target=formal_target,
        )
        for record in records
    }
    scenario_by_run = {
        record["run_id"]: {
            "provider_failure": _has_provider_failure(record),
            "fallback_or_carry_forward": _has_fallback(record),
            "cache_expiry_or_stale": _has_stale_or_expiry(record),
            "schema_drift_or_parity": _has_schema_or_parity(record, parity_reports),
            "qualified_run": qualification_by_run[record["run_id"]]["qualified"],
            "provider_failure_with_fallback_qualified": qualification_by_run[record["run_id"]][
                "provider_failure_with_fallback_qualified"
            ],
        }
        for record in records
    }
    for index, record in enumerate(records):
        scenario_by_run[record["run_id"]]["recovery"] = _has_recovery(
            records,
            index,
            qualification_by_run,
        )
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
    # Latest Harvester carry-forward lag is WARN evidence for the stale
    # scenario. It must not change qualification or BLOCK the window.
    if _workspace_carry_forward_is_stale(workspace):
        scenarios["cache_expiry_or_stale"] = True
    qualified_records = [
        record for record in records if qualification_by_run[record["run_id"]]["qualified"]
    ]
    qualified_days = {
        date.fromisoformat(str(record["date"])) for record in qualified_records
    }
    observed_days = {
        date.fromisoformat(str(record["date"])) for record in records
    }
    consecutive = _consecutive_days(qualified_days)
    non_qualified_runs = [
        {
            "run_id": record["run_id"],
            "date": record["date"],
            "reasons": qualification_by_run[record["run_id"]]["reasons"],
        }
        for record in records
        if not qualification_by_run[record["run_id"]]["qualified"]
    ]
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
        "authority": "scheduled_identity_evidence_only",
        "qualification_contract": {
            "trigger_kind": "scheduled",
            "accepted_schedulers": sorted(scheduler_set or DEFAULT_ACCEPTED_SCHEDULERS),
            "accepted_release": resolved_release,
            "legacy_run_origin_used": False,
            "formal_target": formal_target,
            "formal_requirements": [
                "provider_decision_usable",
                "freshness_usable",
                "committed_generation",
                "authority_not_diagnostic_only",
            ]
            if formal_target
            else [],
        },
        "deployment_date": deployment_date.isoformat(),
        "minimum_days": minimum_days,
        "observed_runs": len(records),
        "observed_days": len(observed_days),
        "qualified_runs": len(qualified_records),
        "qualified_days": len(qualified_days),
        "consecutive_days": consecutive,
        "scenarios": scenarios,
        "qualification_by_run": qualification_by_run,
        "scenario_by_run": scenario_by_run,
        "non_qualified_runs": non_qualified_runs,
        "blockers": blockers,
        "runs": records,
        "parity_reports": [str(path) for path in parity_reports],
        "evidence_period": {
            "human_action": "review_daily_run_summary_only",
            "automatic_failure_evidence": [
                "Data/harvester/exports/.failures/*.json",
                "<<KEEP_STATE_{name}>>_events/run_events_YYYY-MM-DD.jsonl",
                "Output/state/alerts/latest_alert.json",
            ],
            "manual_repair_or_replay_counts": False,
        },
        "note": (
            "A qualified day requires trigger_kind=scheduled, an accepted scheduler_id, "
            "the accepted release_id, Harvester publish_status=COMMITTED, and a complete "
            "core chain. A provider failure with a committed acceptable fallback is a "
            "valid required window event, not a terminator; an uncommitted/incomplete "
            "run is retained as evidence and does not count as a qualified day. "
            "Tests, manual runs, and a single successful run do not satisfy this window."
            + (
                " Formal target mode additionally requires usable provider decision, "
                "usable freshness, an admitted committed generation, and non-diagnostic "
                "authority with decision-consumer permission."
                if formal_target
                else ""
            )
        ),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--since", type=date.fromisoformat, default=DEFAULT_DEPLOYMENT_DATE)
    parser.add_argument("--minimum-days", type=int, default=MINIMUM_DAYS)
    parser.add_argument(
        "--accepted-scheduler",
        action="append",
        dest="accepted_schedulers",
        help="Accepted scheduler_id; repeat for multiple schedulers (default: governance contract)",
    )
    parser.add_argument(
        "--accepted-release",
        help="Accepted release_id (default: governance contract)",
    )
    parser.add_argument(
        "--formal-target",
        action="store_true",
        help="Apply strict target-environment proof requirements; Mac/legacy bundles do not qualify",
    )
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
        accepted_schedulers=args.accepted_schedulers,
        accepted_release=args.accepted_release,
        formal_target=args.formal_target,
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
