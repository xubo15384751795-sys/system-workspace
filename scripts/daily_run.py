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
import os
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path

# Ensure workspace + scripts/ are importable when launched via Dagster/CLI.
_ROOT_BOOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT_BOOT), str(_ROOT_BOOT / "scripts"), str(_ROOT_BOOT / "packages" / "orchestration")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from system_runtime.events import EventEnvelope, JsonlEventStore

logger = logging.getLogger(__name__)

from scripts._runtime_io import ROOT, current_dir, ensure_dir, load_json

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
from orchestration.runner import (
    DailyRunPayload,
    run_daily_sequence_via_dagster,
    use_legacy_daily_run,
)
from scripts._notify import notify_daily_run_result
from scripts._pipeline_runner import run_registry_step
from scripts._pipeline_runner import run_subprocess_step as _run_subprocess_step

# Numbered user-facing stages in the pipeline
TOTAL_STEPS = len(load_daily_run_sequence()) or 33
WEEKLY_STEPS = weekly_step_ids()


def _is_weekly(name: str) -> bool:
    """Check if a step is scheduled weekly."""
    return name in WEEKLY_STEPS


_PIPELINE_MODE = os.environ.get("DAILY_RUN_EXECUTION_MODE", "subprocess")


def set_pipeline_execution_mode(mode: str) -> None:
    global _PIPELINE_MODE
    _PIPELINE_MODE = mode


def _resolve_execution_mode(step_id: str) -> str:
    if _PIPELINE_MODE == "callable":
        return "callable"
    if _PIPELINE_MODE == "auto":
        from scripts._pipeline_runner import load_step_execution

        return load_step_execution(step_id).get("mode", "subprocess")
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
    fw_path = ROOT / "Output" / "current" / "neutral_pressure_snapshot.json"
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
    fw_path = ROOT / "Output" / "current" / "neutral_pressure_snapshot.json"
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

    # 3. Harvester release freshness
    latest = ROOT / "Data" / "harvester" / "exports" / "latest"
    if latest.exists():
        catalog = latest / "catalog.json"
        if catalog.exists():
            try:
                cat = json.loads(catalog.read_text(encoding="utf-8"))
                release_date = cat.get("finalized_at", "")[:10]
                if release_date:
                    age = (datetime.now(UTC).date() - datetime.fromisoformat(release_date).date()).days
                    if age > 2:
                        warnings.append(f"HARVESTER_STALE: release is {age} days old ({release_date})")
            except Exception:
                logger.debug("Failed to parse Harvester catalog for freshness check", exc_info=True)
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


def write_alert(warnings: list[str], steps: list[dict], output_root: Path | None = None) -> None:
    """Write alert files."""
    alert_dir = output_root / "alerts" if output_root else ALERT_DIR
    ensure_dir(alert_dir)
    now = datetime.now(UTC).isoformat()
    failed_steps = [s for s in steps if s.get("status") != "success"]

    alert = {
        "timestamp": now,
        "severity": "HIGH" if failed_steps else ("MEDIUM" if warnings else "LOW"),
        "warnings": warnings,
        "failed_steps": [
            {
                "step": s["step"],
                "error": (s.get("stdout_tail") or "")[-300:],
                "duration_s": s.get("duration_s", 0),
            }
            for s in failed_steps
        ],
        "summary": (
            f"{len(failed_steps)} steps failed, {len(warnings)} warnings"
            if failed_steps or warnings
            else "All steps succeeded, no warnings"
        ),
    }

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
            pass


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


def run_daily(args: argparse.Namespace) -> None:
    """Execute the full daily batch (called by CLI and Dagster daily_job)."""
    set_pipeline_execution_mode(args.execution_mode)

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

    # Phase 2.3: truncate launchd logs > 10MB on daily_run startup so the
    # Output/logs/launchd/ files don't grow unbounded.
    _truncate_launchd_logs()

    if args.dry_run:
        print("DRY RUN — would execute:")
        for step in dry_run_labels():
            print(f"  {step}")
        return

    # Start run bundle — atomic record of this execution.
    bundle = RunBundle.start(mode="daily_pipeline", tag=schedule_tag, update_pointer=False)
    logger.info("Run bundle: %s", bundle.run_id)
    candidate_dir = begin_candidate(bundle.run_dir)

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
            # Phase 0.1: surface subprocess stdout/stderr in the bundle so
            # nightly-run failures are diagnosable without re-running steps.
            stdout_tail=step_result.get("stdout_tail", ""),
            stderr_tail=step_result.get("stderr_tail", ""),
            full_stderr=step_result.get("full_stderr", step_result.get("stderr_tail", "")),
        )

    bp_path = ROOT / "Data" / "harvester" / "exports" / "latest" / "data" / "benchmark_panel.parquet"
    payload = DailyRunPayload(
        args=args,
        start_time=start_time,
        total_steps=TOTAL_STEPS,
        run_step_fn=run_step,
        record_fn=_record,
        benchmark_panel_path=bp_path,
        run_id=bundle.run_id,
    )
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

    # Runtime event
    end_time = datetime.now(UTC)
    freshness = check_freshness()
    warnings = check_warnings()
    run_status = "success" if all(s.get("status") == "success" for s in steps) else "partial_failure"
    freshness_report = load_json(ROOT / "Output" / "quality" / "freshness_report.json") or {}
    can_publish, publish_reason = should_publish(run_status, freshness_report)
    if run_status == "success" and not can_publish:
        warnings.append(f"PUBLISH_BLOCKED: {publish_reason}")
        run_status = "partial_failure"
    event = {
        "run_id": f"daily_{start_time.strftime('%Y%m%d_%H%M')}",
        "bundle_run_id": bundle.run_id,
        "schedule_tag": schedule_tag,
        "started_at": start_time.isoformat(),
        "finished_at": end_time.isoformat(),
        "duration_s": round((end_time - start_time).total_seconds(), 1),
        "status": run_status,
        "steps": steps,
        "warnings": warnings,
        "data_freshness": freshness,
    }
    write_runtime_event(event, output_root=output_root if args.output_root else None)
    write_alert(warnings, steps, output_root=output_root if args.output_root else None)

    failed_steps = [s["step"] for s in steps if s.get("status") != "success"]
    notify_daily_run_result(
        status=run_status,
        failed_steps=failed_steps,
        warnings=warnings,
    )

    # Finish run bundle
    bundle_dir = bundle.finish(status=run_status)
    logger.info("Run bundle saved: %s", bundle_dir)

    if can_publish:
        published = publish_candidate(candidate_dir, run_id=bundle.run_id)
        logger.info("Published %d current artifacts (%s)", published["count"], publish_reason)
    else:
        logger.warning("Skipped current publish: %s", publish_reason)
    clear_candidate_env()

    from ingest_daily_run_to_hub import ingest_daily_run_bundle

    # Phase B5: shadow two-phase publish. paper_portfolio wrote its NAV/state
    # into the shadow_candidate dir; promote atomically only when the run is
    # publishable. On a failed/blocked run the candidate is retained for audit
    # but the live shadow state / NAV ledger / latest pointer are untouched.
    from scripts._shadow_publish import (
        begin_shadow_candidate,
        clear_shadow_candidate_env,
        publish_shadow_candidate,
    )

    shadow_candidate = begin_shadow_candidate(bundle.run_dir)
    if can_publish:
        promoted = publish_shadow_candidate(shadow_candidate)
        logger.info("Promoted %d shadow artifacts", promoted["count"])
    else:
        logger.warning("Skipped shadow publish (run not publishable)")
    clear_shadow_candidate_env()

    ingest_daily_run_bundle(bundle_dir, run_status=run_status, steps=steps)

    # Close the Learning Hub default path on every run. Bundle ingestion alone
    # only snapshots run metadata; this second stage appends source events and
    # rematerializes the authoritative ledgers. A failure is intentionally
    # visible instead of allowing governance reports to refresh over a frozen
    # learning ledger.
    from scripts.run_learning_hub_ingest import main as run_learning_hub_ingest

    hub_exit = run_learning_hub_ingest()
    if hub_exit != 0:
        raise RuntimeError(f"Learning Hub ingest failed with exit code {hub_exit}")

    # Refresh governance status after the bundle has its final manifest.
    governance_status_script = ROOT / "scripts" / "commands" / "weekly" / "governance_status.py"
    if governance_status_script.exists():
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

    # Symlink decision_trace.json into Output/current/ for easy access
    dt_src = bundle_dir / "decision_trace.json"
    dt_dst = ROOT / "Output" / "current" / "decision_trace.json"
    if dt_src.exists():
        try:
            if dt_dst.is_symlink() or dt_dst.exists():
                dt_dst.unlink()
            dt_dst.symlink_to(dt_src.resolve())
        except OSError:
            pass

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
    judgment_path = ROOT / "Output" / "judgment" / "latest.json"
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
    for rel in [
        "Output/judgment/latest.json",
        "Output/trade_decision/latest.json",
        "Output/trade_decisions/latest.json",
    ]:
        p = ROOT / rel
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                bundle.capture_decision_trace({rel: data})
            except Exception:
                logger.debug("Failed to capture decision trace for %s", rel, exc_info=True)

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


def main(argv: list[str] | None = None) -> None:
    """CLI entry. Prefer ``python -m orchestration.cli daily`` for launchd."""
    args = parse_args(argv)
    # Optional outer Dagster entry when not already inside daily_job.
    if (
        os.environ.get("SYSTEM_ORCHESTRATOR", "").strip().lower() == "dagster"
        and os.environ.get("SYSTEM_INSIDE_DAGSTER_DAILY_JOB", "").strip() not in {"1", "true", "TRUE"}
        and not use_legacy_daily_run()
    ):
        from orchestration.cli import cmd_daily

        raise SystemExit(cmd_daily(list(argv) if argv is not None else sys.argv[1:]))
    run_daily(args)


if __name__ == "__main__":
    main()
