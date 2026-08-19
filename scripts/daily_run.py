#!/usr/bin/env python3
"""Scheduled Batch Monitor — daily automated run.

Usage:
    python3 scripts/daily_run.py              # full run
    python3 scripts/daily_run.py --skip-harvester  # skip data fetch
    python3 scripts/daily_run.py --dry-run    # print plan, don't execute
    python3 scripts/daily_run.py --output-root /tmp/test_run  # isolate output

Output:
    Output/runs/{run_id}/            — atomic run bundle (new)
    Output/runtime_events/YYYY-MM-DD.jsonl
    Output/alerts/latest_alert.md
    Output/alerts/latest_alert.json

Environment:
    DAILY_OUTPUT_ROOT  — alternative to --output-root; scripts that opt-in
                         use this to redirect their output directory.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from system_runtime.events import EventEnvelope, JsonlEventStore
from system_runtime.run_outcome import (
    ADMISSION_BLOCK,
    ADMISSION_PASS,
    EXECUTION_FAILED,
    EXECUTION_SUCCESS,
    EXIT_MANDATORY_SINK_FAILURE,
    PUBLISH_COMMITTED,
    PUBLISH_NOT_PUBLISHED,
    REASON_EARLY_RUN_FAILURE,
    REASON_MANDATORY_SINK_FAILED,
    REASON_PUBLISH_NOT_COMMITTED,
    REASON_RECOVERY_REQUIRED,
    REASON_REQUIRED_STEP_FAILED,
    REASON_SCHEDULE_SLOT_ALREADY_CLAIMED,
    REASON_STEP_BLOCKED,
    REASON_TRANSACTION_FAILED,
    REASON_TRANSACTION_ROLLED_BACK,
    SPEC_OK,
    RunOutcome,
)

logger = logging.getLogger(__name__)

from scripts._runtime_io import ROOT, current_dir, ensure_dir, load_json, surface_dir
from system_runtime.canonical_lineage import summarize_step_lineage
from system_runtime.minimum_monitoring import (
    evaluate_minimum_monitoring,
    notification_dedup_key,
    release_identity,
)
from system_runtime.paths import WorkspacePaths
from system_runtime.pipeline import load_pipeline
from system_runtime.provider_status import (
    ProviderStatusPolicyError,
    provider_status_policy,
)
from system_runtime.publish_admission import (
    AUTHORITY_ALLOW,
    AUTHORITY_BLOCK,
    AUTHORITY_DIAGNOSTIC_ONLY,
    PublishAdmission,
)
from system_runtime.publish_transaction import (
    CompatibilityMigrationRequired,
    PublishTransaction,
    TransactionState,
)
from system_runtime.schedule_slots import (
    ScheduledSlotStore,
    completed_session_slot_key,
)
from system_runtime.schedule_slots import (
    default_database as default_schedule_database,
)

RUNTIME_DIR = ROOT / "Output" / "runtime_events"
ALERT_DIR = ROOT / "Output" / "alerts"
from run_bundle import RunBundle

from scripts._constants import CASELAB_USABLE_THRESHOLD, TIMEOUT_STANDARD
from scripts._current_publish import (
    begin_candidate,
    clear_candidate_env,
    publish_candidate,
    should_publish,
)
from scripts._daily_run_sequence import (
    dry_run_labels,
    load_daily_run_sequence,
    weekly_step_ids,
)
from scripts._notify import notify_daily_run_result


def _diagnostic_route_policies(steps: list[dict[str, object]]) -> list[dict[str, object]]:
    """Return provider route policies that cannot carry decision authority."""
    policies: list[dict[str, object]] = []
    for step in steps:
        provider_outcome = step.get("provider_outcome")
        if not isinstance(provider_outcome, dict):
            continue
        route_policy = provider_outcome.get("route_policy")
        if isinstance(route_policy, dict) and bool(route_policy.get("diagnostic_only")):
            policies.append(dict(route_policy))
    return policies


def _transaction_failure_reasons(
    transaction: PublishTransaction | None,
    *,
    commit_attempted: bool,
) -> list[str]:
    """Map a failed generation commit to the authoritative typed reason."""

    if transaction is None or not commit_attempted or transaction.state == TransactionState.COMMITTED:
        return []
    if transaction.state == TransactionState.RECOVERY_REQUIRED:
        return [REASON_RECOVERY_REQUIRED]
    if transaction.state == TransactionState.ROLLED_BACK:
        return [REASON_TRANSACTION_ROLLED_BACK]
    return [REASON_TRANSACTION_FAILED]


def use_legacy_daily_run() -> bool:
    return os.environ.get("SYSTEM_USE_LEGACY_DAILY_RUN", "").strip() in {
        "1",
        "true",
        "TRUE",
        "yes",
        "YES",
    }


def use_generation_transaction() -> bool:
    """Enable the immutable-generation path only after compatibility migration."""
    return os.environ.get("SYSTEM_GENERATION_MODE", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def requested_authority_from_decision(decision_payload: dict[str, object] | None) -> str:
    """Map a decision artifact to explicit publication authority."""
    if not decision_payload:
        return AUTHORITY_BLOCK
    if decision_payload.get("decision") in {"WATCH", "WATCH_ONLY"}:
        return AUTHORITY_DIAGNOSTIC_ONLY
    try:
        effective_size = float(decision_payload.get("effective_size") or 0)
    except (TypeError, ValueError):
        return AUTHORITY_BLOCK
    if not math.isfinite(effective_size):
        return AUTHORITY_BLOCK
    return AUTHORITY_ALLOW if effective_size > 0 else AUTHORITY_DIAGNOSTIC_ONLY


def _candidate_identity_contracts(
    generation_dir: Path,
) -> tuple[dict[str, str], dict[str, str]]:
    """Collect explicit run/release identities emitted by candidate JSON.

    A candidate can contain a syntactically valid artifact copied from an old
    run.  The generation checksum alone cannot detect that semantic reuse, so
    admission also checks identities that producers explicitly stamp into JSON
    or provenance.  Missing optional identity fields remain the producer's
    responsibility; any identity that is present but disagrees is fatal.
    """
    run_ids: dict[str, str] = {}
    release_ids: dict[str, str] = {}

    def walk(value: object, relative: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                location = f"{relative}.{key}" if relative else str(key)
                if key in {"run_id", "bundle_run_id", "generation_id"}:
                    if isinstance(child, str) and child.strip():
                        run_ids[location] = child
                elif key in {"release_id", "source_release_id"}:
                    if isinstance(child, str) and child.strip():
                        release_ids[location] = child
                walk(child, location)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{relative}[{index}]")

    for path in sorted(generation_dir.rglob("*.json")):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        relative = str(path.relative_to(generation_dir))
        walk(payload, relative)
    return run_ids, release_ids


def _candidate_decision_lineage(generation_dir: Path) -> dict[str, object] | None:
    """Read the candidate Judgment chain for authority admission.

    The publish transaction still checks every candidate byte. This helper
    only selects the decision-facing lineage envelope; PublishAdmission is the
    validator and authority owner.
    """

    path = generation_dir / "judgment" / "latest.json"
    if not path.is_file() or path.is_symlink():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("canonical_chain"), dict):
        return None
    result: dict[str, object] = {"canonical_chain": payload["canonical_chain"]}
    if isinstance(payload.get("canonical_claim_chains"), list):
        result["canonical_claim_chains"] = payload["canonical_claim_chains"]
    return result


from scripts._pipeline_runner import run_registry_step
from scripts._pipeline_runner import run_subprocess_step as _run_subprocess_step

# Numbered user-facing stages in the pipeline
TOTAL_STEPS = len(load_daily_run_sequence()) or 33
WEEKLY_STEPS = weekly_step_ids()


def _is_weekly(name: str) -> bool:
    """Check if a step is scheduled weekly."""
    return name in WEEKLY_STEPS


def _weekly_cadence_due(start_time: datetime, args: argparse.Namespace) -> bool:
    """Return whether a weekly compatibility readout is due for this run."""
    return start_time.weekday() == 0 or bool(getattr(args, "force_weekly", False))


_PIPELINE_MODE = os.environ.get("DAILY_RUN_EXECUTION_MODE", "subprocess")


def set_pipeline_execution_mode(mode: str) -> None:
    global _PIPELINE_MODE
    _PIPELINE_MODE = mode


def _resolve_execution_mode(step_id: str) -> str:
    if _PIPELINE_MODE == "callable":
        return "callable"
    if _PIPELINE_MODE == "auto":
        from system_runtime.paths import WorkspacePaths
        from system_runtime.pipeline import load_pipeline

        # The compiled plan is the only production source of step execution
        # metadata.  The raw registry remains available only to the explicit
        # emergency/compatibility paths.
        plan = load_pipeline(WorkspacePaths(root=ROOT))
        return plan.step(step_id).execution_mode
    return "subprocess"


def run_step(name: str, cmd: list[str], env: dict | None = None, *, registry_step: str | None = None) -> dict:
    """Run a pipeline step via subprocess or registry callable mode."""
    mode = _resolve_execution_mode(registry_step or name)
    if mode == "callable":
        argv = cmd[2:] if len(cmd) > 2 and str(cmd[1]).endswith(".py") else cmd[1:]
        return run_registry_step(registry_step or name, mode="callable", argv=argv)
    return _run_subprocess_step(name, cmd, env)


def check_freshness() -> dict:
    """Check if the published neutral pressure snapshot is stale."""
    fw_path = surface_dir("current") / "neutral_pressure_snapshot.json"
    if not fw_path.exists():
        return {"status": "missing", "stale_hours": None}
    mtime = datetime.fromtimestamp(fw_path.stat().st_mtime, tz=UTC)
    age_hours = (datetime.now(UTC) - mtime).total_seconds() / 3600
    stale = age_hours > 24
    return {"status": "stale" if stale else "fresh", "stale_hours": round(age_hours, 1)}


def check_warnings() -> list[str]:
    """Check for warning conditions."""
    warnings = []

    # 1. Framework output freshness
    freshness = check_freshness()
    if freshness["status"] == "stale":
        warnings.append(f"STALE: framework_output is {freshness['stale_hours']}h old")
    elif freshness["status"] == "missing":
        warnings.append("MISSING: neutral_pressure_snapshot.json does not exist")

    # 2. Coverage status
    fw_path = surface_dir("current") / "neutral_pressure_snapshot.json"
    if fw_path.exists():
        try:
            fw = json.loads(fw_path.read_text(encoding="utf-8"))
            overall = fw.get("basic", {}).get("overall", "UNKNOWN")
            quality = fw.get("basic", {}).get("quality_status", "UNKNOWN")
            if overall != "ACTIVE_FULL":
                warnings.append(f"COVERAGE: overall={overall}")
            if "PROXY_REDUCED" in quality:
                warnings.append(f"QUALITY: {quality}")
        except Exception:
            warnings.append("PARSE_ERROR: cannot read neutral_pressure_snapshot.json")

    # 3. Harvester observation freshness.  Finalization time is not data
    # freshness: a repaired old release can be finalized today while its
    # observations remain stale.  Require both decision-facing panels to have
    # coverage and compare their oldest observation end date.
    latest = ROOT / "Data" / "harvester" / "exports" / "latest"
    if latest.exists():
        observation_ends: dict[str, date] = {}
        for dataset_id in ("benchmark_panel", "cross_asset_daily_panel"):
            manifest = latest / "manifests" / f"{dataset_id}.manifest.json"
            try:
                payload = json.loads(manifest.read_text(encoding="utf-8"))
                raw_end = str(payload.get("time_coverage", {}).get("end", ""))[:10]
                if raw_end:
                    observation_ends[dataset_id] = date.fromisoformat(raw_end)
                outcome = payload.get("provider_outcome")
                if isinstance(outcome, dict):
                    status = str(outcome.get("status") or "").strip()
                    if status in {
                        "reused_after_provider_failure",
                        "provider_failed_no_acceptable_fallback",
                        "environmentally_blocked",
                    }:
                        failed = outcome.get("failed_count")
                        requested = outcome.get("requested_count")
                        counts = (
                            f" failed={failed}/{requested}"
                            if failed is not None and requested is not None
                            else ""
                        )
                        warnings.append(
                            f"HARVESTER_PROVIDER_DEGRADED: {dataset_id} "
                            f"status={status}{counts}"
                        )
            except Exception:
                logger.debug("Failed to parse Harvester observation manifest", exc_info=True)
        if len(observation_ends) == 2:
            oldest = min(observation_ends.values())
            age = (datetime.now(UTC).date() - oldest).days
            if age > 3:
                detail = ", ".join(
                    f"{name}={value.isoformat()}" for name, value in sorted(observation_ends.items())
                )
                warnings.append(f"HARVESTER_STALE: observations are {age} days old ({detail})")
        else:
            missing = sorted({"benchmark_panel", "cross_asset_daily_panel"} - observation_ends.keys())
            warnings.append(f"HARVESTER_OBSERVATION_MISSING: {missing}")
    else:
        warnings.append("HARVESTER_MISSING: no latest release")

    return warnings


def write_runtime_event(event: dict, output_root: Path | None = None) -> None:
    """Append one versioned event to the runtime event store."""
    runtime_dir = output_root / "runtime_events" if output_root else RUNTIME_DIR
    ensure_dir(runtime_dir)
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    path = runtime_dir / f"{today}.jsonl"
    JsonlEventStore(path).append(
        EventEnvelope.create(
            event_type=str(event.get("type") or "daily_run_completed"),
            payload_schema=str(event.get("schema_version") or "run_event.v1"),
            payload=event,
            producer="daily_run",
            run_id=event.get("run_id") or os.environ.get("ZCODE_BUNDLE_RUN_ID"),
            occurred_at=str(event.get("timestamp") or "") or None,
        )
    )


def write_alert(
    warnings: list[str],
    steps: list[dict],
    output_root: Path | None = None,
    outcome: dict | None = None,
    provider_status: str | None = None,
) -> None:
    """Write alert files."""
    alert_dir = output_root / "alerts" if output_root else ALERT_DIR
    ensure_dir(alert_dir)
    now = datetime.now(UTC).isoformat()
    failed_steps = [s for s in steps if s.get("status") != "success"]
    run_id = str((outcome or {}).get("run_id") or os.environ.get("ZCODE_BUNDLE_RUN_ID") or "")
    release_id = str(
        (outcome or {}).get("release_id")
        or release_identity(ROOT).get("release_id")
        or ""
    )
    generation_id = (outcome or {}).get("generation_id")
    outcome_failed = bool(outcome and int(outcome.get("exit_code") or 0) != 0)
    outcome_degraded = bool(
        outcome
        and (
            outcome.get("status") == "degraded"
            or outcome.get("operational_state") == "COMPLETED_DEGRADED"
        )
    )
    alert_status = (
        "partial_failure"
        if failed_steps or (outcome_failed and not outcome_degraded)
        else "degraded"
        if outcome_degraded
        else "success"
    )
    failed_step_ids = [str(step.get("step", "")) for step in failed_steps]
    provider_status_value = str(
        provider_status
        or (outcome or {}).get("provider_status")
        or next(
            (
                item.get("provider_outcome", {}).get("status")
                for item in steps
                if isinstance(item.get("provider_outcome"), dict)
                and item.get("provider_outcome", {}).get("status")
            ),
            "",
        )
    ).strip().lower()
    provider_policy: dict[str, str] | None = None
    provider_policy_error: str | None = None
    if provider_status_value:
        try:
            provider_policy = provider_status_policy(provider_status_value, root=ROOT)
        except ProviderStatusPolicyError as exc:
            provider_policy_error = str(exc)

    severity = (
        "HIGH"
        if failed_steps or (outcome_failed and not outcome_degraded)
        else "MEDIUM"
        if warnings or outcome_degraded
        else "LOW"
    )
    if provider_policy:
        matrix_severity = {
            "INFO": "LOW",
            "NOTICE": "MEDIUM",
            "WARNING": "MEDIUM",
            "ERROR": "HIGH",
        }[provider_policy["alert"]]
        if outcome_degraded and not failed_steps:
            # The provider policy remains visible in the alert payload, but a
            # completed/degraded run is a warning channel event, not a new
            # system-crash notification.
            matrix_severity = min(
                (matrix_severity, "MEDIUM"),
                key={"LOW": 0, "MEDIUM": 1, "HIGH": 2}.get,
            )
        severity = max((severity, matrix_severity), key={"LOW": 0, "MEDIUM": 1, "HIGH": 2}.get)

    alert = {
        "timestamp": now,
        "status": alert_status,
        "run_id": run_id,
        "release_id": release_id or None,
        "generation_id": generation_id,
        "severity": severity,
        "warnings": warnings,
        "outcome": outcome,
        "provider_status": provider_status_value or None,
        "provider_alert_policy": provider_policy.get("alert") if provider_policy else None,
        "provider_alert_eligibility": (
            "ALLOWED" if provider_policy else "BLOCKED" if provider_status_value else "NOT_APPLICABLE"
        ),
        "failed_steps": [
            {
                "step": s["step"],
                "error": (s.get("stdout_tail") or "")[-300:],
                "duration_s": s.get("duration_s", 0),
            }
            for s in failed_steps
        ],
        # SYS-21 reader dual-read: canonical IDs are observable context only.
        # The alert's run/release/generation fields remain the notification
        # and authority lineage contract.
        "canonical_lineage": summarize_step_lineage(steps, run_id=run_id),
        "summary": (
            f"{len(failed_steps)} steps failed, {len(warnings)} warnings"
            if failed_steps or warnings
            else (
                f"Run completed in degraded mode; admission/publish remains blocked "
                f"(exit_code={outcome.get('exit_code')})"
                if outcome_degraded and outcome
                else f"RunOutcome failed with exit_code={outcome.get('exit_code')}"
                if outcome_failed and outcome
                else "All steps succeeded, no warnings"
            )
        ),
    }
    if provider_policy_error:
        alert["provider_alert_policy_error"] = provider_policy_error
    alert["notification_dedup_key"] = notification_dedup_key(
        run_id=run_id,
        status=alert_status,
        failed_steps=failed_step_ids,
        warnings=warnings,
        outcome=outcome,
        provider_status=provider_status_value or None,
    )

    (alert_dir / "latest_alert.json").write_text(
        json.dumps(alert, indent=2, default=str), encoding="utf-8"
    )

    # Markdown version
    lines = [
        f"# Daily Alert — {now[:10]}",
        "",
        f"**Severity:** {alert['severity']}",
        f"**Summary:** {alert['summary']}",
        "",
    ]
    if failed_steps:
        lines.append("## Failed Steps")
        for s in failed_steps:
            lines.append(f"- {s['step']}: {s.get('status', '?')}")
        lines.append("")
    if warnings:
        lines.append("## Warnings")
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")

    (alert_dir / "latest_alert.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _early_failure_run_id() -> str:
    now = datetime.now(UTC)
    return f"daily_pipeline_early_failure_{now.strftime('%Y%m%d_%H%M%S')}_{os.urandom(3).hex()}"


def _early_failure_bundle(args: argparse.Namespace) -> RunBundle | None:
    """Recover or create a bundle when execution fails before RunOutcome."""
    existing_dir = os.environ.get("SYSTEM_DAILY_BUNDLE_DIR", "").strip()
    existing_id = os.environ.get("SYSTEM_DAILY_BUNDLE_RUN_ID", "").strip()
    if existing_dir:
        run_dir = Path(existing_dir)
        if run_dir.is_dir():
            bundle = RunBundle(
                existing_id or run_dir.name,
                "daily_pipeline",
                run_dir,
                root=ROOT,
                tag=getattr(args, "tag", None),
            )
            bundle._step_file = run_dir / "steps.jsonl"
            return bundle

    output_root = Path(args.output_root) if getattr(args, "output_root", None) else None
    try:
        return RunBundle.start(
            mode="daily_pipeline",
            tag=getattr(args, "tag", None),
            update_pointer=False,
            output_root=output_root,
        )
    except Exception:
        logger.exception("Failed to create an early-failure run bundle")
        return None


def build_early_failure_outcome(
    args: argparse.Namespace,
    exc: Exception,
    *,
    stage: str = "daily_run_initialization",
) -> RunOutcome:
    """Materialize a typed failure when no normal outcome exists yet.

    This is deliberately a bounded fallback: it records the exception type,
    never the raw exception text, and emits the same run identity to the
    available bundle, alert, runtime-event, and notification consumers.
    """
    output_root = Path(args.output_root) if getattr(args, "output_root", None) else ROOT / "Output"
    if getattr(args, "output_root", None):
        ensure_dir(output_root)
        os.environ["DAILY_OUTPUT_ROOT"] = str(output_root)

    bundle = _early_failure_bundle(args)
    run_id = bundle.run_id if bundle is not None else _early_failure_run_id()
    try:
        release_id = release_identity(ROOT).get("release_id")
    except Exception:
        release_id = None
    outcome = RunOutcome(
        run_id=run_id,
        spec_status=SPEC_OK,
        execution_status=EXECUTION_FAILED,
        failed_steps=[stage],
        admission_verdict=ADMISSION_BLOCK,
        publish_status=PUBLISH_NOT_PUBLISHED,
        authority_mode="diagnostic",
        reason_codes=[REASON_EARLY_RUN_FAILURE],
        release_id=release_id,
    )
    outcome_dict = outcome.to_dict()
    warning = f"{REASON_EARLY_RUN_FAILURE}: {type(exc).__name__}"
    step = {
        "step": stage,
        "status": "failed",
        "returncode": outcome.exit_code,
        "duration_s": 0,
        "error_type": type(exc).__name__,
    }

    if bundle is not None:
        try:
            bundle.record_step(
                name=stage,
                status="failed",
                returncode=outcome.exit_code,
                detail=type(exc).__name__,
            )
            bundle.record_outcome(outcome_dict)
            bundle.finish(status=outcome.status)
        except Exception:
            logger.exception("Failed to finalize early-failure run bundle")

    started_at = datetime.now(UTC)
    event = {
        "type": "daily_run_early_failure",
        "run_id": outcome.run_id,
        "schedule_run_id": f"daily_{started_at.strftime('%Y%m%d_%H%M')}",
        "bundle_run_id": bundle.run_id if bundle is not None else None,
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "duration_s": 0,
        "status": outcome.status,
        "steps": [step],
        "warnings": [warning],
        "outcome": outcome_dict,
    }
    try:
        event["minimum_monitoring"] = evaluate_minimum_monitoring(
            ROOT,
            output_root=output_root if getattr(args, "output_root", None) else None,
            run_id=outcome.run_id,
        )
    except Exception:
        event["minimum_monitoring"] = {"status": "UNAVAILABLE", "reason_code": "EARLY_FAILURE_FALLBACK"}
    from system_runtime.operator_events import build_operator_events

    provider_check = (
        event["minimum_monitoring"].get("checks", {}).get("provider_failure", {})
        if isinstance(event["minimum_monitoring"], dict)
        else {}
    )
    canonical_lineage = summarize_step_lineage(event["steps"], run_id=outcome.run_id)
    event["operator_events"] = build_operator_events(
        run_id=outcome.run_id,
        release_id=outcome.release_id,
        generation_id=outcome.generation_id,
        provider_check=provider_check,
        publish_integrity_verdict="BLOCK",
        diagnostic_publish_verdict="BLOCK",
        decision_authority_verdict=AUTHORITY_BLOCK,
        publish_status=outcome.publish_status,
        canonical_lineage=canonical_lineage,
    )
    try:
        write_alert(
            [warning],
            [step],
            output_root=output_root if getattr(args, "output_root", None) else None,
            outcome=outcome_dict,
        )
        write_runtime_event(
            event,
            output_root=output_root if getattr(args, "output_root", None) else None,
        )
    except Exception:
        # The process must remain non-zero even if a secondary evidence sink
        # is unavailable; the typed early failure is still the authority.
        logger.exception("Failed to publish early-failure evidence")
    try:
        notify_daily_run_result(
            status=outcome.status,
            failed_steps=[stage],
            warnings=[warning],
            outcome=outcome_dict,
            canonical_lineage=canonical_lineage,
        )
    except Exception:
        logger.exception("Failed to notify early-failure outcome")

    os.environ["SYSTEM_DAILY_OUTCOME_READY"] = "1"
    os.environ["SYSTEM_DAILY_SINKS_COMPLETE"] = "1"
    os.environ["SYSTEM_DAILY_EXIT_CODE"] = str(outcome.exit_code)
    os.environ.pop("SYSTEM_DAILY_BUNDLE_DIR", None)
    os.environ.pop("SYSTEM_DAILY_BUNDLE_RUN_ID", None)
    return outcome


def _detect_schedule_slot(hour: int) -> str:
    """Auto-detect schedule slot from current UTC hour."""
    if hour < 10:
        return "overnight"
    elif hour < 17:
        return "mid_session"
    elif hour < 22:
        return "post_close"
    else:
        return "daily_summary"


def _truncate_launchd_logs(max_bytes: int = 10 * 1024 * 1024) -> None:
    """Phase 2.3: truncate launchd log files > max_bytes on startup.

    Keeps the tail (last max_bytes/2) so recent errors survive; the full history
    is in run bundles (steps.jsonl + step_logs/) anyway.
    """
    log_dir = ROOT / "Output" / "logs" / "launchd"
    if not log_dir.exists():
        return
    for log_file in log_dir.glob("*.log"):
        try:
            size = log_file.stat().st_size
            if size <= max_bytes:
                continue
            # Keep the last half of the budget (most recent errors).
            keep = max_bytes // 2
            data = log_file.read_bytes()[-keep:]
            log_file.write_bytes(data)
            logger.info("Truncated %s (%d -> %d bytes)", log_file.name, size, keep)
        except OSError:
            logger.warning("Failed to truncate launchd log: %s", log_file, exc_info=True)


def _raise_open_file_limit(target: int = 65536) -> None:
    """Raise soft RLIMIT_NOFILE — launchd often starts at 256 (EMFILE in harvester)."""
    try:
        import resource

        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        if hard == resource.RLIM_INFINITY:
            new_soft = max(soft, target)
        else:
            new_soft = min(max(soft, target), hard)
        if new_soft > soft:
            resource.setrlimit(resource.RLIMIT_NOFILE, (new_soft, hard))
            logger.info("Raised RLIMIT_NOFILE soft limit %s -> %s (hard=%s)", soft, new_soft, hard)
    except (ValueError, OSError) as exc:
        logger.warning("Could not raise RLIMIT_NOFILE: %s", exc)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scheduled Batch Monitor")
    parser.add_argument("--skip-harvester", action="store_true")
    parser.add_argument("--skip-etf", action="store_true", help="Skip ETF panel refresh step")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--output-root", type=str, default=None,
        help="Redirect Output/ under this root (for test isolation). "
             "Sets DAILY_OUTPUT_ROOT env for child scripts.",
    )
    parser.add_argument(
        "--tag", type=str, default=None,
        help="Run tag for this execution (e.g. overnight, mid_session, post_close, daily_summary). "
             "Auto-detected from UTC hour if not given.",
    )
    parser.add_argument(
        "--use-horizon-sample",
        action="store_true",
        help="Use sample Horizon events when real Horizon output is missing.",
    )
    parser.add_argument(
        "--force-weekly",
        action="store_true",
        help="Run weekly steps (mechanism_calibration, suggest_paper_updates) even when not Monday UTC.",
    )
    parser.add_argument(
        "--execution-mode",
        choices=["subprocess", "callable", "auto"],
        default=os.environ.get("DAILY_RUN_EXECUTION_MODE", "subprocess"),
        help="Pipeline step execution mode (subprocess default; callable uses registry future_callable).",
    )
    return parser.parse_args(argv)


def run_daily(args: argparse.Namespace) -> RunOutcome:
    """Execute the full daily batch (called by CLI and Dagster daily_job).

    Returns a :class:`RunOutcome` whose ``exit_code`` is the authoritative
    process exit code.  Callers (``main``, ``run_scheduled_daily``) must
    propagate this code rather than assuming success.
    """
    set_pipeline_execution_mode(args.execution_mode)
    os.environ.pop("SYSTEM_DAILY_OUTCOME_READY", None)
    os.environ.pop("SYSTEM_DAILY_SINKS_COMPLETE", None)
    os.environ.pop("SYSTEM_DAILY_BUNDLE_DIR", None)
    os.environ.pop("SYSTEM_DAILY_BUNDLE_RUN_ID", None)

    # Configure logging: process steps go to log, CLI summary stays as print
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    _raise_open_file_limit()

    # Resolve output root — default is ROOT/Output, override for test isolation
    output_root = Path(args.output_root) if args.output_root else ROOT / "Output"
    if args.output_root:
        ensure_dir(output_root)
        os.environ["DAILY_OUTPUT_ROOT"] = str(output_root)

    start_time = datetime.now(UTC)
    schedule_tag = args.tag or _detect_schedule_slot(start_time.hour)
    logger.info("Daily Run [%s] - %s", schedule_tag, start_time.strftime('%Y-%m-%d %H:%M'))

    # launchd calendar triggers are at-least-once. Claim the local calendar
    # slot before creating a run bundle so a duplicate wake-up cannot enter
    # the authoritative publisher a second time. Direct/manual invocations
    # do not set SYSTEM_SCHEDULE_LABEL and retain explicit-run semantics.
    schedule_store: ScheduledSlotStore | None = None
    schedule_slot_key: str | None = None
    schedule_owner_id: str | None = None
    schedule_label = os.environ.get("SYSTEM_SCHEDULE_LABEL", "").strip()
    if schedule_label and not args.dry_run:
        schedule_slot_key = completed_session_slot_key(
            label=schedule_label,
            now=start_time,
            calendar_name=os.environ.get("SYSTEM_SCHEDULE_CALENDAR", "XNYS").strip() or "XNYS",
        )
        schedule_owner_id = f"{schedule_slot_key}|pid={os.getpid()}|started={start_time.isoformat()}"
        schedule_store = ScheduledSlotStore(default_schedule_database(ROOT))
        claim = schedule_store.claim(schedule_slot_key, owner_id=schedule_owner_id)
        if not claim.acquired:
            logger.warning(
                "Scheduled slot already claimed; skipping duplicate wake-up: %s "
                "(owner=%s status=%s)",
                schedule_slot_key,
                claim.existing_owner_id,
                claim.existing_status,
            )
            return RunOutcome(
                run_id=f"scheduled_slot_skip_{schedule_slot_key.replace('|', '_')}",
                spec_status=SPEC_OK,
                execution_status=EXECUTION_SUCCESS,
                admission_verdict=ADMISSION_PASS,
                publish_status=PUBLISH_NOT_PUBLISHED,
                authority_mode="diagnostic",
                reason_codes=[REASON_SCHEDULE_SLOT_ALREADY_CLAIMED],
            )

    # Phase 2.3: truncate launchd logs > 10MB on daily_run startup so the
    # Output/logs/launchd/ files don't grow unbounded.
    _truncate_launchd_logs()

    if args.dry_run:
        print("DRY RUN - would execute:")
        for step in dry_run_labels():
            print(f"  {step}")
        return RunOutcome(
            run_id="dry_run",
            spec_status=SPEC_OK,
            execution_status=EXECUTION_SUCCESS,
            admission_verdict=ADMISSION_PASS,
            publish_status=PUBLISH_NOT_PUBLISHED,
            authority_mode="diagnostic",
            reason_codes=[],
        )

    # Start run bundle — atomic record of this execution.  The generation
    # transaction is prepared before any writer module is imported; the
    # compatibility path remains available only until the explicit migration
    # has been applied to this checkout.
    bundle = RunBundle.start(
        mode="daily_pipeline",
        tag=schedule_tag,
        update_pointer=False,
        output_root=output_root if args.output_root else None,
    )
    logger.info("Run bundle: %s", bundle.run_id)
    os.environ["SYSTEM_DAILY_BUNDLE_DIR"] = str(bundle.run_dir)
    os.environ["SYSTEM_DAILY_BUNDLE_RUN_ID"] = bundle.run_id
    compiled_plan = load_pipeline(WorkspacePaths(root=ROOT))
    compiled_plan_digest = compiled_plan.plan_digest
    bundle.set_contract_digests(plan_digest=compiled_plan_digest)
    transaction: PublishTransaction | None = None
    if use_generation_transaction():
        transaction = PublishTransaction(bundle.run_id, bundle.run_dir)
        transaction.prepare()
        transaction.activate()
        candidate_dir = transaction.candidate_dirs["current"]
        shadow_candidate_dir = transaction.candidate_dirs["position"]
    else:
        candidate_dir = begin_candidate(bundle.run_dir)

        # Compatibility path: establish the shadow candidate at run start so
        # paper_portfolio never falls back to live position during a run.
        from scripts._shadow_publish import begin_shadow_candidate

        shadow_candidate_dir = begin_shadow_candidate(bundle.run_dir)

    # Publish bundle run_id to the environment so subprocess/callable steps
    # (structural_replay, bridge, ...) can stamp provenance on their outputs
    # and consumers can reject stale/previous-run artifacts. Propagation uses
    # the subprocess env merge in _pipeline_runner.run_subprocess_step.
    os.environ["ZCODE_BUNDLE_RUN_ID"] = bundle.run_id

    steps = []

    def _record(step_result: dict, input_artifacts: list[str] | None = None) -> None:
        """Record step into both local list and run bundle."""
        steps.append(step_result)
        bundle.record_step(
            name=step_result["step"],
            status=step_result.get("status", "unknown"),
            duration_s=step_result.get("duration_s", 0),
            returncode=step_result.get("returncode", 0),
            input_artifacts=input_artifacts,
            blocked_by=step_result.get("blocked_by"),
            degraded=bool(step_result.get("degraded")),
            provider_outcome=step_result.get("provider_outcome"),
            step_outcome=step_result.get("step_outcome"),
            canonical_ids=step_result.get("canonical_ids"),
            canonical_chain=step_result.get("canonical_chain"),
            canonical_source_path=step_result.get("canonical_source_path"),
            # Phase 0.1: surface subprocess stdout/stderr in the bundle so
            # nightly-run failures are diagnosable without re-running steps.
            stdout_tail=step_result.get("stdout_tail", ""),
            stderr_tail=step_result.get("stderr_tail", ""),
            full_stderr=step_result.get("full_stderr", step_result.get("stderr_tail", "")),
        )

    bp_path = ROOT / "Data" / "harvester" / "exports" / "latest" / "data" / "benchmark_panel.parquet"
    if use_legacy_daily_run():
        logger.warning(
            "SYSTEM_USE_LEGACY_DAILY_RUN=1 — using archived legacy executor "
            "(Dagster default path bypassed)"
        )
        from scripts.archive._legacy_daily_run_executor import (
            DailyRunContext,
            execute_daily_sequence,
        )

        ctx = DailyRunContext(
            args=args,
            start_time=start_time,
            total_steps=TOTAL_STEPS,
            run_step_fn=run_step,
            record_fn=_record,
            benchmark_panel_path=bp_path,
            run_id=bundle.run_id,
        )
        execute_daily_sequence(ctx)
    else:
        from orchestration.runner import DailyRunPayload, run_daily_sequence_via_dagster

        payload = DailyRunPayload(
            args=args,
            start_time=start_time,
            total_steps=TOTAL_STEPS,
            run_step_fn=run_step,
            record_fn=_record,
            benchmark_panel_path=bp_path,
            run_id=bundle.run_id,
        )
        logger.info("Executing daily sequence via Dagster op (in-process)")
        run_daily_sequence_via_dagster(payload)

    _capture_traces(bundle)

    # Auto-generate feedback pending for degenerate signals
    _collect_feedback_pending(bundle)

    # Record key artifacts from candidate (pre-publish)
    from scripts._current_publish import candidate_artifact_names

    for name in candidate_artifact_names():
        artifact = candidate_dir / name
        if artifact.exists():
            bundle.record_artifact(artifact)

    # Publish current and position only after all step results and freshness
    # checks are known.  Generation mode uses one admission token and one
    # active-pointer commit; the compatibility branch remains explicit until
    # the checkout has undergone the recoverable surface migration.
    freshness = check_freshness()
    warnings = check_warnings()
    run_status = "success" if all(s.get("status") == "success" for s in steps) else "partial_failure"
    published_current = False
    published_shadow = False
    admission_token: PublishAdmission | None = None
    admission_payload: dict = {}
    authority_mode = "authoritative"
    transaction_failure_codes: list[str] = []

    if transaction is not None:
        freshness_report = load_json(surface_dir("quality") / "freshness_report.json") or (
            freshness if isinstance(freshness, dict) and "verdict" in freshness else {}
        )
        transaction.write_lineage()
        evidence_digest = bundle.evidence_digest(transaction.generation_dir)
        generation_digest = transaction.generation_digest
        if generation_digest is None:
            raise RuntimeError("generation lineage digest was not produced before admission")
        bundle.set_contract_digests(
            evidence_digest=evidence_digest,
            generation_digest=generation_digest,
        )
        transaction.bind_contract_digests(
            plan_digest=compiled_plan_digest,
            evidence_digest=evidence_digest,
        )
        candidate_run_ids, candidate_release_ids = _candidate_identity_contracts(
            transaction.generation_dir
        )
        expected_release_id = release_identity(ROOT).get("release_id") or ""
        generation_files = [
            str(path.relative_to(transaction.generation_dir))
            for path in transaction.generation_dir.rglob("*")
            if path.is_file()
        ]
        required_generation_files = [
            "lineage.json",
            "current/00_READ_ME_FIRST.md",
            "current/framework_output.json",
            "current/status.json",
            "current/quality_validation.json",
            "judgment/latest.json",
            "trade_decision/latest.json",
            "position/paper_portfolio.json",
        ]
        decision_path = transaction.candidate_dirs["trade_decision"] / "latest.json"
        decision_payload = load_json(decision_path) if decision_path.exists() else None
        requested_authority = requested_authority_from_decision(decision_payload)
        canonical_lineage = summarize_step_lineage(steps, run_id=bundle.run_id)
        decision_lineage = _candidate_decision_lineage(transaction.generation_dir)
        pre_publish_monitoring = evaluate_minimum_monitoring(
            ROOT,
            output_root=output_root if args.output_root else None,
            run_id=bundle.run_id,
        )
        pre_publish_provider = (
            pre_publish_monitoring.get("checks", {}).get("provider_failure", {})
            if isinstance(pre_publish_monitoring, dict)
            else {}
        )
        provider_decision = (
            pre_publish_provider.get("status_policy", {}) or {}
        ).get("decision")
        if provider_decision is None:
            provider_decision = {
                "PASS": "ALLOW",
                "WARN": "CONDITIONAL",
                "FAIL": "DENY",
                "BLOCKED": "DENY",
            }.get(str(pre_publish_provider.get("status") or "").upper())
        diagnostic_routes = _diagnostic_route_policies(steps)
        if diagnostic_routes:
            # The candidate itself is the authority for this run. Do not let
            # pre-publish monitoring of the previous finalized release hide a
            # diagnostic-only route selected by the current candidate.
            provider_decision = "DENY"
            warnings.append("ADMISSION_BLOCKED: DIAGNOSTIC_ONLY_PROVIDER_ROUTE")
        admission_token = PublishAdmission.evaluate(
            run_status=run_status,
            freshness_verdict=str(freshness_report.get("verdict", "UNKNOWN")),
            required_artifacts=required_generation_files,
            candidate_artifacts=generation_files,
            candidate_run_id=bundle.run_id,
            artifact_run_ids=candidate_run_ids,
            release_id=expected_release_id,
            artifact_release_ids=candidate_release_ids,
            provider_decision=provider_decision,
            authority_verdict=requested_authority,
            generation_id=bundle.run_id,
            plan_digest=compiled_plan_digest,
            evidence_digest=evidence_digest,
            generation_digest=generation_digest,
            canonical_lineage=canonical_lineage,
            decision_lineage=decision_lineage,
        )
        can_publish = transaction.admit(admission_token)
        admission_payload = load_json(transaction.generation_dir / "admission.json") or {}
        bundle.set_contract_digests(admission_digest=admission_payload.get("admission_digest"))
        authority_mode = (
            "diagnostic"
            if admission_token.is_diagnostic_only or admission_token.decision_authority_blocked
            else "authoritative"
        )
        publish_reason = ";".join(admission_token.reason_codes) or "admission_pass"
        if can_publish:
            try:
                # Trace/feedback evidence must be durable before the single
                # live-pointer swap.  RunBundle.finish() remains responsible
                # for the final outcome manifest after commit, but it must not
                # be the first writer of these evidence files post-publish.
                bundle.finalize_evidence()
                transaction.commit_generation(ROOT)
                published_current = True
                published_shadow = True
                logger.info(
                    "Committed generation %s (authority=%s)",
                    bundle.run_id,
                    admission_token.authority_verdict,
                )
            except CompatibilityMigrationRequired as exc:
                can_publish = False
                run_status = "partial_failure"
                publish_reason = f"compatibility_migration_required={exc}"
                transaction_failure_codes.extend(
                    _transaction_failure_reasons(transaction, commit_attempted=True)
                )
                warnings.append(f"PUBLISH_BLOCKED: {publish_reason}")
                logger.warning("Generation commit blocked: %s", exc)
            except Exception as exc:
                can_publish = False
                run_status = "partial_failure"
                publish_reason = f"generation_commit_failed={exc}"
                transaction_failure_codes.extend(
                    _transaction_failure_reasons(transaction, commit_attempted=True)
                )
                warnings.append(f"PUBLISH_COMMIT_FAILED: {exc}")
                logger.exception("Generation publication failed")
        else:
            logger.warning("Skipped generation publish: %s", publish_reason)
        transaction.deactivate()
        # The transaction owns the generation env only for candidate writers.
        # Post-run evidence ingestion is deliberately routed outside the
        # immutable generation, so do not leave generation mode enabled after
        # the pointer decision.
        os.environ["SYSTEM_GENERATION_MODE"] = "0"
    else:
        freshness_report = load_json(surface_dir("quality") / "freshness_report.json") or {}
        can_publish, publish_reason = should_publish(run_status, freshness_report)
        diagnostic_routes = _diagnostic_route_policies(steps)
        if diagnostic_routes:
            can_publish = False
            publish_reason = "diagnostic_provider_route"
            warnings.append("PUBLISH_BLOCKED: DIAGNOSTIC_ONLY_PROVIDER_ROUTE")
        if run_status == "success" and not can_publish:
            warnings.append(f"PUBLISH_BLOCKED: {publish_reason}")
            run_status = "partial_failure"

        if can_publish:
            try:
                published = publish_candidate(candidate_dir, run_id=bundle.run_id)
                published_current = True
                logger.info("Published %d current artifacts (%s)", published["count"], publish_reason)
            except Exception as exc:
                can_publish = False
                run_status = "partial_failure"
                publish_reason = f"publish_commit_failed={exc}"
                warnings.append(f"PUBLISH_COMMIT_FAILED: {exc}")
                logger.exception("Current publication failed")
        else:
            logger.warning("Skipped current publish: %s", publish_reason)
        clear_candidate_env()

        from scripts._shadow_publish import (
            clear_shadow_candidate_env,
            publish_shadow_candidate,
        )

        if can_publish:
            try:
                promoted = publish_shadow_candidate(shadow_candidate_dir)
                published_shadow = True
                logger.info("Promoted %d shadow artifacts", promoted["count"])
            except Exception as exc:
                can_publish = False
                run_status = "partial_failure"
                publish_reason = f"shadow_publish_failed={exc}"
                warnings.append(f"SHADOW_PUBLISH_FAILED: {exc}")
                logger.exception("Shadow publication failed")
        else:
            logger.warning("Skipped shadow publish (run not publishable)")
        clear_shadow_candidate_env()

    failed_step_ids = [s["step"] for s in steps if s.get("status") not in ("success",)]
    blocked_step_ids = [s["step"] for s in steps if s.get("status") == "blocked_upstream"]
    degraded_step_ids = [s["step"] for s in steps if s.get("degraded")]
    provider_statuses = [
        str(step.get("provider_outcome", {}).get("status"))
        for step in steps
        if isinstance(step.get("provider_outcome"), dict)
        and step.get("provider_outcome", {}).get("status")
    ]
    provider_status = next(
        (
            status
            for status in provider_statuses
            if status
            in {
                "provider_failed_no_acceptable_fallback",
                "reused_after_provider_failure",
                "environmentally_blocked",
                "partial_provider_success",
                "reused_same_content",
            }
        ),
        provider_statuses[0] if provider_statuses else None,
    )
    provider_cache_within_grace: bool | None = None
    for step in steps:
        provider_outcome = step.get("provider_outcome")
        if not isinstance(provider_outcome, dict):
            continue
        if "cache_within_grace" in provider_outcome:
            provider_cache_within_grace = bool(provider_outcome["cache_within_grace"])
            break
    exec_status = EXECUTION_SUCCESS if not failed_step_ids and not blocked_step_ids else EXECUTION_FAILED
    admission = ADMISSION_PASS if can_publish else ADMISSION_BLOCK
    pub_status = (
        PUBLISH_COMMITTED
        if published_current and published_shadow
        else PUBLISH_NOT_PUBLISHED
    )
    reason_codes: list[str] = []
    if failed_step_ids:
        reason_codes.append(REASON_REQUIRED_STEP_FAILED)
    if blocked_step_ids:
        reason_codes.append(REASON_STEP_BLOCKED)
    if not can_publish and not failed_step_ids and not blocked_step_ids:
        reason_codes.append("ADMISSION_REJECTED")
    reason_codes.extend(transaction_failure_codes)
    if not published_current or not published_shadow:
        reason_codes.append(REASON_PUBLISH_NOT_COMMITTED)

    outcome = RunOutcome(
        run_id=bundle.run_id,
        spec_status=SPEC_OK,
        execution_status=exec_status,
        failed_steps=failed_step_ids,
        blocked_steps=blocked_step_ids,
        degraded_steps=degraded_step_ids,
        admission_verdict=admission,
        publish_status=pub_status,
        authority_mode=authority_mode,
        reason_codes=reason_codes,
        generation_id=bundle.run_id if transaction is not None else None,
        release_id=release_identity(ROOT).get("release_id"),
        provider_status=provider_status,
        provider_cache_within_grace=provider_cache_within_grace,
    )
    # From this point onward every sink consumes the typed outcome status. The
    # pre-admission ``run_status`` above is still needed by PublishAdmission,
    # but cannot be used for the final bundle/event/alert after a late commit
    # or admission decision.
    run_status = outcome.status
    outcome_dict = outcome.to_dict()
    bundle.record_outcome(outcome_dict)
    os.environ["SYSTEM_DAILY_OUTCOME_READY"] = "1"
    os.environ["SYSTEM_DAILY_SINKS_COMPLETE"] = "0"

    # Persist the slot decision before post-publish evidence ingestion. A
    # later non-authoritative sink failure must not cause launchd to replay a
    # slot that has already made its publish decision.
    if schedule_store is not None and schedule_slot_key and schedule_owner_id:
        if not schedule_store.complete(
            schedule_slot_key,
            owner_id=schedule_owner_id,
            outcome=outcome_dict,
        ):
            raise RuntimeError(f"scheduled slot completion lost ownership: {schedule_slot_key}")

    # Runtime event
    end_time = datetime.now(UTC)
    event = {
        "run_id": outcome.run_id,
        "schedule_run_id": f"daily_{start_time.strftime('%Y%m%d_%H%M')}",
        "bundle_run_id": outcome.run_id,
        "schedule_tag": schedule_tag,
        "started_at": start_time.isoformat(),
        "finished_at": end_time.isoformat(),
        "duration_s": round((end_time - start_time).total_seconds(), 1),
        "status": outcome.status,
        "steps": steps,
        "warnings": warnings,
        "data_freshness": freshness,
        "outcome": outcome_dict,
    }
    minimum_monitoring = evaluate_minimum_monitoring(
        ROOT,
        output_root=output_root if args.output_root else None,
        run_id=bundle.run_id,
    )
    provider_check = (
        minimum_monitoring.get("checks", {}).get("provider_failure", {})
        if isinstance(minimum_monitoring, dict)
        else {}
    )
    publish_integrity_verdict = admission_payload.get(
        "publish_integrity_verdict",
        "PASS" if published_current and published_shadow else "BLOCK",
    )
    diagnostic_publish_verdict = admission_payload.get(
        "diagnostic_publish_verdict",
        "PASS" if published_current and published_shadow else "BLOCK",
    )
    decision_authority_verdict = admission_payload.get(
        "decision_authority_verdict",
        AUTHORITY_ALLOW if authority_mode == "authoritative" and can_publish else AUTHORITY_BLOCK,
    )
    from system_runtime.operator_events import build_operator_events

    canonical_lineage = summarize_step_lineage(steps, run_id=outcome.run_id)
    event["operator_events"] = build_operator_events(
        run_id=outcome.run_id,
        release_id=outcome.release_id,
        generation_id=outcome.generation_id,
        provider_check=provider_check,
        publish_integrity_verdict=str(publish_integrity_verdict),
        diagnostic_publish_verdict=str(diagnostic_publish_verdict),
        decision_authority_verdict=str(decision_authority_verdict),
        publish_status=outcome.publish_status,
        canonical_lineage=canonical_lineage,
    )
    write_alert(
        warnings,
        steps,
        output_root=output_root if args.output_root else None,
        outcome=outcome_dict,
    )
    event["minimum_monitoring"] = minimum_monitoring
    write_runtime_event(event, output_root=output_root if args.output_root else None)

    failed_steps = [s["step"] for s in steps if s.get("status") != "success"]
    notify_daily_run_result(
        status=run_status,
        failed_steps=failed_steps,
        warnings=warnings,
        outcome=outcome_dict,
        canonical_lineage=canonical_lineage,
    )

    # Finish run bundle
    bundle_dir = bundle.finish(status=run_status)
    logger.info("Run bundle saved: %s", bundle_dir)

    # WP2: shadow two-phase publish. paper_portfolio wrote its NAV/state
    # into the shadow_candidate dir (established at run start, not here);
    # promote atomically only when the run is publishable. On a failed/blocked
    # run the candidate is retained for audit but the live shadow state /
    # NAV ledger / latest pointer are untouched.
    if transaction is not None:
        # Learning Hub's canonical Data append is post-run evidence, but its
        # convenience summary must not mutate the already committed immutable
        # generation.  Put that summary beside the run bundle instead.
        os.environ["SYSTEM_POST_PUBLISH_AUDIT_DIR"] = str(bundle_dir / "post_publish")
    from ingest_daily_run_to_hub import ingest_daily_run_bundle

    try:
        ingest_daily_run_bundle(bundle_dir, run_status=run_status, steps=steps)
    finally:
        os.environ.pop("SYSTEM_POST_PUBLISH_AUDIT_DIR", None)

    # Close the Learning Hub default path on every run. Bundle ingestion alone
    # only snapshots run metadata; this second stage appends source events and
    # rematerializes the authoritative ledgers. A failure must replace the
    # previously optimistic outcome with a typed mandatory-sink failure.
    try:
        from scripts.run_learning_hub_ingest import main as run_learning_hub_ingest

        hub_exit = run_learning_hub_ingest()
        if hub_exit != 0:
            raise RuntimeError(f"Learning Hub ingest failed with exit code {hub_exit}")
    except Exception as exc:
        mandatory_outcome = RunOutcome(
            run_id=outcome.run_id,
            spec_status=outcome.spec_status,
            execution_status=outcome.execution_status,
            failed_steps=list(outcome.failed_steps),
            blocked_steps=list(outcome.blocked_steps),
            degraded_steps=list(outcome.degraded_steps),
            admission_verdict=outcome.admission_verdict,
            publish_status=outcome.publish_status,
            authority_mode=outcome.authority_mode,
            reason_codes=[*outcome.reason_codes, REASON_MANDATORY_SINK_FAILED],
            generation_id=outcome.generation_id,
            release_id=outcome.release_id,
        )
        mandatory_dict = mandatory_outcome.to_dict()
        try:
            bundle.record_outcome(mandatory_dict)
            bundle.finish(status=mandatory_outcome.status)
        except Exception:
            logger.exception("Failed to rewrite bundle after mandatory sink failure")
        event["status"] = mandatory_outcome.status
        event["outcome"] = mandatory_dict
        event["type"] = "daily_run_mandatory_sink_failed"
        try:
            write_alert(
                [f"MANDATORY_SINK_FAILED: {type(exc).__name__}"],
                steps,
                output_root=output_root if args.output_root else None,
                outcome=mandatory_dict,
            )
            write_runtime_event(event, output_root=output_root if args.output_root else None)
            notify_daily_run_result(
                status=mandatory_outcome.status,
                failed_steps=failed_steps,
                warnings=[f"MANDATORY_SINK_FAILED: {type(exc).__name__}"],
                outcome=mandatory_dict,
                canonical_lineage=summarize_step_lineage(steps, run_id=mandatory_outcome.run_id),
            )
        except Exception:
            logger.exception("Failed to publish mandatory sink failure evidence")
        os.environ["SYSTEM_DAILY_EXIT_CODE"] = str(EXIT_MANDATORY_SINK_FAILURE)
        os.environ["SYSTEM_DAILY_SINKS_COMPLETE"] = "0"
        logger.exception("Learning Hub mandatory sink failed")
        return mandatory_outcome

    # Refresh governance status after the bundle has its final manifest.
    governance_status_script = ROOT / "scripts" / "commands" / "weekly" / "governance_status.py"
    # The compatibility executor historically refreshed this weekly report
    # after every run. On non-Monday runs that made a valid prior-week cache
    # look like a current-run mismatch. The compiled Dagster path owns the
    # weekly step; this fallback may only refresh it on its weekly cadence.
    if (
        governance_status_script.exists()
        and transaction is None
        and _weekly_cadence_due(start_time, args)
    ):
        subprocess.run(
            [sys.executable, str(governance_status_script)],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_STANDARD,
            cwd=str(ROOT),
        )
        for artifact_rel in [
            "Output/system_learning/latest/governance_status.json",
            "Output/system_learning/latest/governance_status.md",
        ]:
            artifact = ROOT / artifact_rel
            if artifact.exists():
                bundle.record_artifact(artifact)

    # The generation path keeps decision traces in the immutable run bundle;
    # only the pre-generation compatibility branch may retain the historical
    # convenience symlink.  No post-publish write is allowed in generation mode.
    if transaction is None:
        dt_src = bundle_dir / "decision_trace.json"
        dt_dst = surface_dir("current") / "decision_trace.json"
        if dt_src.exists():
            try:
                if dt_dst.is_symlink() or dt_dst.exists():
                    dt_dst.unlink()
                dt_dst.symlink_to(dt_src.resolve())
            except OSError:
                logger.warning("Failed to publish decision trace symlink: %s", dt_dst, exc_info=True)

    # Summary
    print("\n=== Summary ===")
    print(f"Duration: {event['duration_s']}s")
    print(f"Status: {event['status']}")
    for s in steps:
        emoji = "✅" if s["status"] == "success" else "❌"
        print(f"  {emoji} {s['step']}: {s['status']} ({s['duration_s']}s)")
    if warnings:
        print(f"Warnings ({len(warnings)}):")
        for w in warnings:
            print(f"  ⚠️  {w}")
    else:
        print("No warnings.")

    # The typed outcome was constructed, persisted, and sent to notification
    # consumers before post-publish evidence ingestion.  Return that same
    # object; reconstructing a second outcome here would allow authority or
    # publish semantics to diverge between bundle, event, notification, and
    # Dagster/CLI exit handling.
    logger.info("RunOutcome: exit_code=%d reason_codes=%s", outcome.exit_code, outcome.reason_codes)
    os.environ["SYSTEM_DAILY_SINKS_COMPLETE"] = "1"
    return outcome


def _collect_feedback_pending(bundle: RunBundle) -> None:
    """Auto-generate feedback_pending items for degenerate or weak signals."""
    # HMM degeneracy
    hmm_path = ROOT / "Output" / "ml_signals" / "latest" / "regime_hmm.json"
    if hmm_path.exists():
        try:
            hmm = json.loads(hmm_path.read_text(encoding="utf-8"))
            degeneracy = hmm.get("degeneracy", {})
            if not degeneracy.get("usable_for_core_judgment", True):
                flags = degeneracy.get("flags", [])
                warnings = degeneracy.get("warnings", [])
                bundle.add_feedback_pending(
                    f"HMM signal degenerate: {', '.join(flags)}",
                    source="hmm_regime_signal",
                    validation_type="ml_signal_calibration",
                    priority="high",
                )
                for w in warnings:
                    bundle.add_feedback_pending(
                        w,
                        source="hmm_regime_signal",
                        validation_type="ml_signal_calibration",
                        priority="medium",
                    )
        except Exception:
            logger.debug("Failed to build HMM regime feedback item", exc_info=True)

    # Judgment confidence low
    judgment_path = surface_dir("judgment") / "latest.json"
    judgment = None
    if judgment_path.exists():
        try:
            judgment = json.loads(judgment_path.read_text(encoding="utf-8"))
            conf_level = (judgment.get("confidence") or {}).get("level", "")
            if conf_level == "low":
                reasons = (judgment.get("confidence") or {}).get("reasons", [])[:2]
                for r in reasons:
                    bundle.add_feedback_pending(
                        f"Low confidence: {r}",
                        source="judgment_layer",
                        validation_type="judgment_calibration",
                        priority="medium",
                    )
        except Exception:
            logger.debug("Failed to build judgment confidence feedback item", exc_info=True)

    # Claim ladder verification targets (structured)
    if judgment:
        try:
            ladder = judgment.get("claim_ladder", {})
            if ladder:
                tier = ladder.get("tier", 0)
                label = ladder.get("label", "unknown")
                claim = ladder.get("claim_statement", "")
                watch_conditions = ladder.get("watch_conditions", [])
                invalidation_conditions = ladder.get("invalidation_conditions", [])
                promo = ladder.get("promotion_conditions", {})
                demotion_risk = ladder.get("demotion_risk", "")

                # Compute CaseLab score gap from caselab output
                caselab_gap = 0.0
                _today_str = date.today().isoformat()
                caselab_path_today = ROOT / "Output" / "caselab" / f"{_today_str}.json"
                if caselab_path_today.exists():
                    try:
                        _cl = json.loads(caselab_path_today.read_text(encoding="utf-8"))
                        _mq = _cl.get("match_quality", {})
                        _ts = _mq.get("top_score", 0)
                        _ut = _mq.get("thresholds", {}).get("usable", CASELAB_USABLE_THRESHOLD)
                        caselab_gap = round(max(0, _ut - _ts), 3)
                    except Exception:
                        logger.debug("Failed to read caselab match quality for feedback", exc_info=True)

                # M/D persistence requirement from promotion conditions
                md_persist_req = promo.get("to_tier_2", "")

                # Structured claim ladder item with all 6 required fields
                bundle.add_feedback_pending(
                    f"Claim ladder: tier={tier} ({label}) — {claim[:150]}",
                    source="claim_ladder",
                    validation_type="claim_verification",
                    priority="high",
                    metadata={
                        "claim_tier": tier,
                        "claim_label": label,
                        "mechanism_hypothesis": claim,
                        "watch_conditions": watch_conditions,
                        "invalidation_conditions": invalidation_conditions,
                        "caselab_score_gap": caselab_gap,
                        "md_persistence_requirement": md_persist_req,
                        "demotion_risk": demotion_risk,
                        # Acceptance criteria: 4 questions answered
                        "what_to_verify": claim,
                        "what_to_watch_next": watch_conditions,
                        "upgrade_conditions": list(promo.values()),
                        "downgrade_conditions": invalidation_conditions + ([demotion_risk] if demotion_risk else []),
                    },
                )
        except Exception:
            logger.debug("Failed to build claim ladder feedback item", exc_info=True)

    # CaseLab match quality
    caselab_dir = ROOT / "Output" / "caselab"
    if caselab_dir.exists():
        try:
            today = date.today().isoformat()
            caselab_path = caselab_dir / f"{today}.json"
            if caselab_path.exists():
                caselab = json.loads(caselab_path.read_text(encoding="utf-8"))
                mq = caselab.get("match_quality", {})
                top_score = mq.get("top_score", 0)
                thresholds = mq.get("thresholds", {})
                usable_th = thresholds.get("usable", CASELAB_USABLE_THRESHOLD)
                gap = round(usable_th - top_score, 3) if top_score < usable_th else 0
                if gap > 0:
                    bundle.add_feedback_pending(
                        f"CaseLab gap: score={top_score}, usable≥{usable_th}, gap={gap}",
                        source="caselab",
                        validation_type="case_matching",
                        priority="medium",
                    )
                # Mechanism context — what's missing
                mc = caselab.get("mechanism_context", {})
                for mtype in mc.get("mechanism_types", []):
                    bundle.add_feedback_pending(
                        f"Mechanism to verify: {mtype}",
                        source="caselab",
                        validation_type="mechanism_verification",
                        priority="medium",
                    )
        except Exception:
            logger.debug("Failed to build CaseLab match quality feedback item", exc_info=True)

    # HMM calibration status
    hmm_audit_path = ROOT / "Output" / "hmm_stability" / "hmm_stability_audit.json"
    if hmm_audit_path.exists():
        try:
            audit = json.loads(hmm_audit_path.read_text(encoding="utf-8"))
            cal = audit.get("calibration", {})
            if not cal.get("calibration_passed", True):
                hist = cal.get("degradation_reasons", [])
                for reason in hist:
                    bundle.add_feedback_pending(
                        f"HMM calibration: {reason}",
                        source="hmm_calibration",
                        validation_type="ml_signal_calibration",
                        priority="medium",
                    )
                cap = cal.get("cap_applied", "")
                if cap:
                    bundle.add_feedback_pending(
                        f"HMM cap applied: {cap} — regime claims limited",
                        source="hmm_calibration",
                        validation_type="ml_signal_calibration",
                        priority="low",
                    )
        except Exception:
            logger.debug("Failed to build HMM calibration feedback item", exc_info=True)


def _capture_traces(bundle: RunBundle) -> None:
    """Capture decision and signal traces from current artifacts."""
    # Decision trace: judgment + trade
    for surface, name in [
        ("judgment", "latest.json"),
        ("trade_decision", "latest.json"),
    ]:
        p = surface_dir(surface) / name
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                bundle.capture_decision_trace({f"Output/{surface}/{name}": data})
            except Exception:
                logger.debug("Failed to capture decision trace for %s/%s", surface, name, exc_info=True)

    # Signal trace: framework output (sigma vector summary only)
    fw_path = current_dir() / "framework_output.json"
    if fw_path.exists():
        try:
            fw = json.loads(fw_path.read_text(encoding="utf-8"))
            sv = fw.get("advanced", {}).get("sigma_vector", {})
            bundle.capture_signal_trace({
                "source": "framework_output",
                "framework_status": fw.get("status"),
                "overall": fw.get("basic", {}).get("overall"),
                "quality_status": fw.get("basic", {}).get("quality_status"),
                "sigma_vector": sv,
                "primary_readout": fw.get("advanced", {}).get("primary_readout"),
            })
        except Exception:
            logger.debug("Failed to capture framework output trace", exc_info=True)

    # Signal trace: HMM regime signal with degeneracy info
    hmm_path = ROOT / "Output" / "ml_signals" / "latest" / "regime_hmm.json"
    if hmm_path.exists():
        try:
            hmm = json.loads(hmm_path.read_text(encoding="utf-8"))
            bundle.capture_signal_trace({
                "source": "hmm_regime_signal",
                "regime": hmm.get("regime", {}),
                "stability": hmm.get("stability", {}),
                "degeneracy": hmm.get("degeneracy", {}),
            })
        except Exception:
            logger.debug("Failed to capture HMM regime trace", exc_info=True)


def main(argv: list[str] | None = None) -> int:
    """CLI entry. Prefer ``python -m orchestration.cli daily`` for launchd.

    Returns the authoritative exit code from :class:`RunOutcome`.
    """
    try:
        from system_runtime.observability import init_sentry

        init_sentry()
    except Exception:
        logger.debug("Sentry initialization unavailable", exc_info=True)
    args = parse_args(argv)
    # Optional outer Dagster entry when not already inside daily_job.
    if (
        os.environ.get("SYSTEM_ORCHESTRATOR", "").strip().lower() == "dagster"
        and os.environ.get("SYSTEM_INSIDE_DAGSTER_DAILY_JOB", "").strip() not in {"1", "true", "TRUE"}
        and not use_legacy_daily_run()
    ):
        from orchestration.cli import cmd_daily

        return cmd_daily(list(argv) if argv is not None else sys.argv[1:])
    try:
        outcome = run_daily(args)
    except Exception:
        if (
            os.environ.get("SYSTEM_DAILY_OUTCOME_READY") == "1"
            and os.environ.get("SYSTEM_DAILY_SINKS_COMPLETE") != "1"
        ):
            os.environ["SYSTEM_DAILY_EXIT_CODE"] = str(EXIT_MANDATORY_SINK_FAILURE)
            logger.exception("Daily run failed after RunOutcome creation; mandatory sink failure")
            return EXIT_MANDATORY_SINK_FAILURE
        outcome = build_early_failure_outcome(args, sys.exc_info()[1] or RuntimeError("unknown failure"))
        logger.exception("Daily run failed before RunOutcome creation")
        return outcome.exit_code
    return outcome.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
