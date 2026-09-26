#!/usr/bin/env python3
"""Scheduled Batch Monitor — daily automated run.

Usage:
    python3 scripts/daily_run.py              # full run
    python3 scripts/daily_run.py --skip-harvester  # skip data fetch
    python3 scripts/daily_run.py --dry-run    # print plan, don't execute
    python3 scripts/daily_run.py --output-root /tmp/test_run  # isolate output

Output:
    Output/runs/{run_id}/            — atomic run bundle (new)
    <<KEEP_STATE_{name}>>_events/run_events_YYYY-MM-DD.jsonl
    Output/state/alerts/latest_alert.md
    Output/state/alerts/latest_alert.json

Environment:
    DAILY_OUTPUT_ROOT  — alternative to --output-root; scripts that opt-in
                         use this to redirect their output directory.
"""
from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from orchestration.daily_run_sequence import (
    dry_run_labels,
    load_daily_run_sequence,
    weekly_step_ids,
)

from system_runtime.canonical_lineage import summarize_step_lineage
from system_runtime.context import RuntimeContext
from system_runtime.minimum_monitoring import (
    evaluate_minimum_monitoring,
    release_identity,
)
from system_runtime.pipeline import compile_runtime_plan
from system_runtime.pipeline import load_pipeline as _load_pipeline
from system_runtime.publish_admission import (
    AUTHORITY_ALLOW,
    AUTHORITY_BLOCK,
    PublishAdmission,
)
from system_runtime.publish_transaction import (
    CompatibilityMigrationRequired,
    PublishTransaction,
)
from system_runtime.publish_transaction import (
    TransactionState as _TransactionState,
)
from system_runtime.run_outcome import (
    ADMISSION_BLOCK,
    ADMISSION_PASS,
    EXECUTION_FAILED,
    EXECUTION_SUCCESS,
    EXIT_MANDATORY_SINK_FAILURE,
    PUBLISH_COMMITTED,
    PUBLISH_NOT_PUBLISHED,
    REASON_EARLY_RUN_FAILURE,
    REASON_PUBLISH_NOT_COMMITTED,
    REASON_REQUIRED_STEP_FAILED,
    REASON_SCHEDULE_SLOT_ALREADY_CLAIMED,
    REASON_STEP_BLOCKED,
    SPEC_OK,
    RunOutcome,
)
from system_runtime.schedule_slots import (
    ScheduledSlotStore,
    completed_session_slot_key,
)
from system_runtime.schedule_slots import (
    default_database as default_schedule_database,
)
from verity.cli.host_adapter import (
    raise_open_file_limit as _raise_open_file_limit_impl,
)
from verity.cli.host_adapter import (
    truncate_launchd_logs as _truncate_launchd_logs_impl,
)
from verity.cli.post_run_sinks import (
    capture_traces as _capture_traces,
)
from verity.cli.post_run_sinks import (
    collect_feedback_pending as _collect_feedback_pending,
)
from verity.cli.post_run_sinks import (
    mandatory_sink_failure_outcome,
    write_alert,
    write_runtime_event,
)
from verity.runtime._constants import TIMEOUT_STANDARD
from verity.runtime._current_publish import (
    begin_candidate,
    clear_candidate_env,
    publish_candidate,
    run_freshness_check,
    should_publish,
)
from verity.runtime._daily_observability import publish_daily_run_observability
from verity.runtime._notify import notify_daily_run_result
from verity.runtime.daily_monitoring import (
    check_freshness as _runtime_check_freshness,
)
from verity.runtime.daily_monitoring import (
    check_warnings as _runtime_check_warnings,
)
from verity.runtime.run_bundle import RunBundle
from verity.runtime.runtime_io import ROOT, ensure_dir, load_json, surface_dir

logger = logging.getLogger(__name__)
# Compatibility re-export for legacy test/operator patch points. The default
# runtime path uses compile_runtime_plan as its sole plan compiler.
load_pipeline = _load_pipeline
# Compatibility re-export: older tests/operators import the transaction state
# enum from this module while the implementation now lives with publication
# coordination.
TransactionState = _TransactionState


from orchestration.pipeline_dag import (  # noqa: E402 — delayed to preserve pipeline import order
    classify_step_failures,
)

from verity.cli.publication_coordinator import (  # noqa: E402
    candidate_decision_lineage as _candidate_decision_lineage,
)
from verity.cli.publication_coordinator import (
    candidate_identity_contracts as _candidate_identity_contracts,
)
from verity.cli.publication_coordinator import (
    diagnostic_route_policies as _diagnostic_route_policies,
)
from verity.cli.publication_coordinator import (
    refresh_live_system_index as _refresh_live_system_index,
)
from verity.cli.publication_coordinator import (
    requested_authority_from_decision,
)
from verity.cli.publication_coordinator import (
    transaction_failure_reasons as _transaction_failure_reasons,
)
from verity.cli.run_coordinator import (  # noqa: E402
    run_step,
    set_pipeline_execution_mode,
)
from verity.cli.schedule_admission import (  # noqa: E402
    detect_schedule_slot as _detect_schedule_slot,
)
from verity.cli.schedule_admission import (
    generation_transaction_enabled as use_generation_transaction,
)
from verity.cli.schedule_admission import (
    legacy_daily_run_enabled as use_legacy_daily_run,
)
from verity.cli.schedule_admission import (
    weekly_cadence_due as _weekly_cadence_due,
)

# Numbered user-facing stages in the pipeline
TOTAL_STEPS = len(load_daily_run_sequence()) or 33
WEEKLY_STEPS = weekly_step_ids()


def _is_weekly(name: str) -> bool:
    """Check if a step is scheduled weekly."""
    return name in WEEKLY_STEPS


def check_freshness() -> dict:
    """Compatibility adapter for the runtime freshness service."""
    return _runtime_check_freshness(root=None, surface_dir_fn=surface_dir)


def check_warnings() -> list[str]:
    """Compatibility adapter for runtime freshness and warning monitoring."""
    return _runtime_check_warnings(
        root=ROOT,
        surface_dir_fn=surface_dir,
        freshness_fn=check_freshness,
    )


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
    publish_daily_run_observability(
        outcome_dict,
        output_root=output_root,
        source="daily_run_early_failure",
        failed_steps=[stage],
        warnings=[warning],
    )

    os.environ["SYSTEM_DAILY_OUTCOME_READY"] = "1"
    os.environ["SYSTEM_DAILY_SINKS_COMPLETE"] = "1"
    os.environ["SYSTEM_DAILY_EXIT_CODE"] = str(outcome.exit_code)
    os.environ.pop("SYSTEM_DAILY_BUNDLE_DIR", None)
    os.environ.pop("SYSTEM_DAILY_BUNDLE_RUN_ID", None)
    return outcome


def _truncate_launchd_logs(max_bytes: int = 10 * 1024 * 1024) -> None:
    """Compatibility adapter for the host-process log boundary."""
    _truncate_launchd_logs_impl(ROOT, max_bytes=max_bytes)


def _raise_open_file_limit(target: int = 65536) -> None:
    """Compatibility adapter for the host-process resource boundary."""
    _raise_open_file_limit_impl(target=target)


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
        default=os.environ.get("DAILY_RUN_EXECUTION_MODE", "auto"),
        help=(
            "Pipeline step execution mode (auto consumes the compiled runtime "
            "plan; subprocess/callable are explicit compatibility overrides)."
        ),
    )
    return parser.parse_args(argv)


def run_daily(
    args: argparse.Namespace,
    *,
    runtime_context: RuntimeContext | None = None,
) -> RunOutcome:
    """Execute the full daily batch from the canonical execution spine.

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
    # Run IDs and log timestamps are UTC even when the launchd trigger is a
    # machine-local calendar event.  This keeps cross-device evidence sortable.
    logging.Formatter.converter = time.gmtime
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)sZ [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    _raise_open_file_limit()

    # Resolve output root — default is ROOT/Output, override for test isolation
    runtime_context = runtime_context or RuntimeContext.current_context()
    output_root = Path(args.output_root) if args.output_root else runtime_context.output_root
    if args.output_root:
        ensure_dir(output_root)
        os.environ["DAILY_OUTPUT_ROOT"] = str(output_root)
        os.environ["SYSTEM_OUTPUT_ROOT"] = str(output_root)
        runtime_context = runtime_context.with_roots(output_root=output_root)

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
    # Output/state/logs/launchd/ files don't grow unbounded.
    _truncate_launchd_logs()

    if args.dry_run:
        # Dry-run is still a plan-validation path. Compile the same runtime
        # plan used by the scheduled execution spine, but do not create a
        # bundle, transaction, candidate, or publication side effect.
        compile_runtime_plan(runtime_context.paths, profile="daily")
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
        runtime_context=runtime_context,
        release_id=release_identity(ROOT).get("release_id"),
    )
    logger.info("Run bundle: %s", bundle.run_id)
    os.environ["SYSTEM_DAILY_BUNDLE_DIR"] = str(bundle.run_dir)
    os.environ["SYSTEM_DAILY_BUNDLE_RUN_ID"] = bundle.run_id
    compiled_runtime_plan = compile_runtime_plan(runtime_context.paths, profile="daily")
    compiled_plan = compiled_runtime_plan.compiled_plan
    compiled_plan_digest = compiled_plan.plan_digest
    runtime_plan_path = compiled_runtime_plan.write(bundle.run_dir / "compiled_runtime_plan.json")
    bundle.record_artifact(runtime_plan_path)
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
        from verity.runtime._shadow_publish import begin_shadow_candidate

        shadow_candidate_dir = begin_shadow_candidate(bundle.run_dir)

    # Publish bundle run_id to the environment so subprocess/callable steps
    # (structural_replay, bridge, ...) can stamp provenance on their outputs
    # and consumers can reject stale/previous-run artifacts. Propagation uses
    # the subprocess env merge in _pipeline_runner.run_subprocess_step.
    os.environ["ZCODE_BUNDLE_RUN_ID"] = bundle.run_id

    def _run_compiled_step(
        name: str,
        cmd: list[str],
        env: dict | None = None,
        *,
        registry_step: str | None = None,
    ) -> dict:
        """Run through the immutable plan compiled for this bundle."""
        return run_step(
            name,
            cmd,
            env,
            registry_step=registry_step,
            compiled_plan=compiled_plan,
        )

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

    bp_path = runtime_context.data_root / "harvester" / "exports" / "latest" / "data" / "benchmark_panel.parquet"
    if use_legacy_daily_run():
        logger.warning(
            "SYSTEM_USE_LEGACY_DAILY_RUN=1 — using archived emergency executor "
            "through the runtime compatibility adapter (Dagster default path bypassed)"
        )
        from verity.runtime._legacy_daily_run_executor import (
            DailyRunContext,
            execute_daily_sequence,
        )

        ctx = DailyRunContext(
            args=args,
            start_time=start_time,
            total_steps=TOTAL_STEPS,
            run_step_fn=_run_compiled_step,
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
            run_step_fn=_run_compiled_step,
            record_fn=_record,
            benchmark_panel_path=bp_path,
            run_id=bundle.run_id,
            plan=compiled_plan,
            runtime_plan=compiled_runtime_plan,
            runtime_context=runtime_context,
        )
        logger.info(
            "Executing compiled runtime plan via the single generated-plan Dagster job"
        )
        run_daily_sequence_via_dagster(payload)

    _capture_traces(bundle)

    # Auto-generate feedback pending for degenerate signals
    _collect_feedback_pending(bundle)

    # Record key artifacts from candidate (pre-publish)
    from verity.runtime._current_publish import candidate_artifact_names

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
    hard_failures, soft_failures = classify_step_failures(steps)
    for step in soft_failures:
        warnings.append(f"soft_fail:{step.get('step')}")
    run_status = "success" if not hard_failures else "partial_failure"
    freshness_report = run_freshness_check(gate="publish")
    if not freshness_report.get("verdict"):
        freshness_report = load_json(surface_dir("quality") / "freshness_report.json") or {}
    published_current = False
    published_shadow = False
    admission_token: PublishAdmission | None = None
    admission_payload: dict = {}
    authority_mode = "authoritative"
    transaction_failure_codes: list[str] = []

    if transaction is not None:
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
                transaction.commit_generation(
                    ROOT,
                    output_root=output_root if args.output_root else None,
                )
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

        from verity.runtime._shadow_publish import (
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

    try:
        _refresh_live_system_index(isolated_output=bool(args.output_root))
    except Exception:
        logger.exception("Failed to refresh live system index after pointer decision")
        warnings.append("SYSTEM_INDEX_REFRESH_FAILED")

    failed_step_ids = [str(s.get("step")) for s in hard_failures]
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
    if "harvester" in failed_step_ids or "harvester" in blocked_step_ids:
        try:
            from harvester.core.concurrent_policy import disable_concurrent

            disable_concurrent("HARVESTER_NOT_COMMITTED")
        except Exception:
            logger.exception("failed to disable SYSTEM_HARVESTER_CONCURRENT")
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
    content_stale = [
        f"{item.get('name')} max={item.get('max_date')} behind={item.get('trading_days_behind')}d"
        for item in freshness_report.get("content_freshness") or []
        if item.get("status") == "STALE"
    ]
    publish_blocked: str | None = None if can_publish else publish_reason
    if publish_blocked and not any(
        str(w).startswith(("PUBLISH_BLOCKED:", "PUBLISH_COMMIT_FAILED:", "SHADOW_PUBLISH_FAILED:"))
        for w in warnings
    ):
        warnings.append(f"PUBLISH_BLOCKED: {publish_blocked}")
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

    notification_kwargs: dict[str, object] = {
        "status": run_status,
        "failed_steps": [str(s.get("step")) for s in hard_failures],
        "warnings": warnings,
        "outcome": outcome_dict,
        "canonical_lineage": canonical_lineage,
    }
    # Keep older legacy executors and test doubles source-compatible: the new
    # hard-notification fields are only passed when they carry evidence.
    if content_stale:
        notification_kwargs["content_stale"] = content_stale
    if publish_blocked:
        notification_kwargs["publish_blocked"] = publish_blocked
    notify_daily_run_result(**notification_kwargs)

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
    try:
        # Keep the bundle ingestion and ledger closeout in one mandatory-sink
        # boundary.  The bundle has already made its execution/publication
        # decision, so either post-outcome sink failure must rewrite the same
        # run identity instead of escaping as an untyped Dagster exception.
        try:
            from system_learning.operators.ingest_daily_run_to_hub import (
                ingest_daily_run_bundle,
            )

            ingest_daily_run_bundle(bundle_dir, run_status=run_status, steps=steps)
        finally:
            os.environ.pop("SYSTEM_POST_PUBLISH_AUDIT_DIR", None)

        # Close the Learning Hub default path on every run. Bundle ingestion
        # alone only snapshots run metadata; this second stage appends source
        # events and rematerializes the authoritative ledgers. A failure must
        # replace the previously optimistic outcome with a typed mandatory-
        # sink failure.
        from system_learning.operators.run_learning_hub_ingest import (
            main as run_learning_hub_ingest,
        )

        hub_exit = run_learning_hub_ingest()
        if hub_exit != 0:
            raise RuntimeError(f"Learning Hub ingest failed with exit code {hub_exit}")
    except Exception as exc:
        mandatory_outcome = mandatory_sink_failure_outcome(outcome)
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
                failed_steps=failed_step_ids,
                warnings=[f"MANDATORY_SINK_FAILED: {type(exc).__name__}"],
                outcome=mandatory_dict,
                canonical_lineage=summarize_step_lineage(steps, run_id=mandatory_outcome.run_id),
            )
        except Exception:
            logger.exception("Failed to publish mandatory sink failure evidence")
        publish_daily_run_observability(
            mandatory_dict,
            output_root=output_root if args.output_root else None,
            source="daily_run_mandatory_sink_failure",
            failed_steps=failed_step_ids,
            warnings=[f"MANDATORY_SINK_FAILED: {type(exc).__name__}"],
        )
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
    publish_daily_run_observability(
        outcome_dict,
        output_root=output_root if args.output_root else None,
        source=os.environ.get("SYSTEM_RUN_ORIGIN", "daily_run"),
        failed_steps=[str(s.get("step")) for s in hard_failures],
        warnings=warnings,
    )
    os.environ["SYSTEM_DAILY_SINKS_COMPLETE"] = "1"
    return outcome


def main(argv: list[str] | None = None) -> int:
    """CLI entry. Prefer ``python -m orchestration.cli daily`` for launchd.

    Returns the authoritative exit code from :class:`RunOutcome`.
    """
    try:
        from system_runtime.observability import init_sentry
        from system_runtime.runtime_secrets import load_runtime_secrets

        load_runtime_secrets()
        init_sentry()
    except Exception:
        logger.debug("Sentry initialization unavailable", exc_info=True)
    args = parse_args(argv)
    # CLI compatibility: the orchestration command is an adapter to the same
    # Python entrypoint, never an outer Dagster execution boundary.
    if (
        os.environ.get("SYSTEM_ORCHESTRATOR", "").strip().lower() == "dagster"
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
