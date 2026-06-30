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

logger = logging.getLogger(__name__)

# RunBundle integration — use auditable path management
from _workspace_imports import add_scripts

add_scripts()
from _runtime_io import ROOT, ensure_dir

RUNTIME_DIR = ROOT / "Output" / "runtime_events"
ALERT_DIR = ROOT / "Output" / "alerts"
from _constants import CASELAB_USABLE_THRESHOLD, TIMEOUT_STANDARD
from _daily_run_sequence import dry_run_labels, load_daily_run_sequence, weekly_step_ids
from _notify import notify_daily_run_result
from _pipeline_runner import run_registry_step
from _pipeline_runner import run_subprocess_step as _run_subprocess_step
from run_bundle import RunBundle

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
        from _pipeline_runner import load_step_execution

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
    """Check if framework_output is stale."""
    fw_path = ROOT / "Output" / "current" / "framework_output.json"
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
        warnings.append("MISSING: framework_output.json does not exist")

    # 2. Coverage status
    fw_path = ROOT / "Output" / "current" / "framework_output.json"
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
            warnings.append("PARSE_ERROR: cannot read framework_output.json")

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
    """Append event to daily JSONL log."""
    runtime_dir = output_root / "runtime_events" if output_root else RUNTIME_DIR
    ensure_dir(runtime_dir)
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    path = runtime_dir / f"{today}.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, default=str, ensure_ascii=False) + "\n")


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


def main() -> None:
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
    args = parser.parse_args()
    set_pipeline_execution_mode(args.execution_mode)

    # Configure logging: process steps go to log, CLI summary stays as print
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # Resolve output root — default is ROOT/Output, override for test isolation
    output_root = Path(args.output_root) if args.output_root else ROOT / "Output"
    if args.output_root:
        ensure_dir(output_root)
        os.environ["DAILY_OUTPUT_ROOT"] = str(output_root)

    start_time = datetime.now(UTC)
    schedule_tag = args.tag or _detect_schedule_slot(start_time.hour)
    logger.info("Daily Run [%s] — %s", schedule_tag, start_time.strftime('%Y-%m-%d %H:%M'))

    if args.dry_run:
        print("DRY RUN — would execute:")
        for step in dry_run_labels():
            print(f"  {step}")
        return

    # Start run bundle — atomic record of this execution.
    # Always use ROOT for bundle location (bundles live in Output/runs/, not test output root).
    bundle = RunBundle.start(mode="daily_pipeline", tag=schedule_tag)
    logger.info("Run bundle: %s", bundle.run_id)

    steps = []

    def _record(step_result: dict, input_artifacts: list[str] | None = None) -> None:
        """Record step into both local list and run bundle.

        Args:
            step_result: Output from run_step().
            input_artifacts: Optional list of paths this step consumed.
                Fingerprinted (sha256) for per-step input provenance.
        """
        steps.append(step_result)
        bundle.record_step(
            name=step_result["step"],
            status=step_result.get("status", "unknown"),
            duration_s=step_result.get("duration_s", 0),
            returncode=step_result.get("returncode", 0),
            input_artifacts=input_artifacts,
        )

    # Step 1: Harvester
    if not args.skip_harvester:
        logger.info("[%d/%d] Running Harvester...", 1, TOTAL_STEPS)
        harvester_env = {
            "PYTHONPATH": str(ROOT / "structural-risk-harvester" / "src"),
        }
        _record(
            run_step(
                "harvester",
                [
                    sys.executable,
                    "-m",
                    "harvester",
                    "--exports-root",
                    str(ROOT / "Data" / "harvester" / "exports"),
                    "daily-release",
                ],
                env=harvester_env,
            )
        )
    else:
        logger.info("[%d/%d] Skipping Harvester (--skip-harvester)", 1, TOTAL_STEPS)

    # Step 2: Refresh ETF panel
    if not args.skip_etf:
        logger.info("[%d/%d] Refreshing ETF panel...", 2, TOTAL_STEPS)
        etf_script = ROOT / "scripts" / "refresh_etf_panel.py"
        if etf_script.exists():
            _record(run_step("etf_refresh", [sys.executable, str(etf_script)]))
    else:
        logger.info("[%d/%d] Skipping ETF refresh (--skip-etf)", 2, TOTAL_STEPS)

    # Step 3: Paper world model sync
    logger.info("[%d/%d] Syncing Paper world model...", 3, TOTAL_STEPS)
    paper_sync_script = ROOT / "scripts" / "sync_paper_world_model.py"
    if paper_sync_script.exists():
        _record(run_step("paper_sync", [sys.executable, str(paper_sync_script)]))

    # Step 4: CaseLab index (when Paper hash changes)
    logger.info("[%d/%d] Syncing CaseLab Paper index...", 4, TOTAL_STEPS)
    caselab_index_script = ROOT / "scripts" / "sync_caselab_index.py"
    if caselab_index_script.exists():
        _record(run_step("caselab_index", [sys.executable, str(caselab_index_script)]))

    # Step 4.5: Build agent policy from Paper rules
    build_policy_script = ROOT / "caselab_runtime" / "policies" / "build_policy_from_paper.py"
    if build_policy_script.exists():
        _record(run_step("build_policy_from_paper", [sys.executable, str(build_policy_script)],
                         env={"PYTHONPATH": f"{ROOT}:{ROOT / 'Workbench' / 'src'}:{ROOT / 'scripts'}"}))

    # Step 5: Horizon event adapter — ARCHIVED (no data source, Horizon dormant since 2026-06-02)
    # horizon_event_adapter.py moved to scripts/archive/governance_cut_2026_06_19/

    # Step 6: Structural Replay — builds current M/D/K/X from Harvester panel.
    # Despite the name "replay", this runs on TODAY's data to produce current
    # measurement.  Historical crisis replay is a separate on-demand use case.
    logger.info("[%d/%d] Running Structural Replay (current M/D/K/X measurement)...", 6, TOTAL_STEPS)
    latest = ROOT / "Data" / "harvester" / "exports" / "latest"
    catalog_path = latest / "catalog.json"
    release_id = "latest"
    if catalog_path.exists():
        try:
            cat = json.loads(catalog_path.read_text(encoding="utf-8"))
            release_id = cat.get("release_id", "latest")
        except Exception:
            logger.debug("Failed to read catalog release_id, using 'latest'", exc_info=True)

    bp_path = latest / "data" / "benchmark_panel.parquet"
    replay_cmd = [
        sys.executable, str(ROOT / "scripts" / "structural_replay_v2.py"),
        f"panel.release_id={release_id}",
        f"panel.path={bp_path}",
        f"run.tag=daily_{datetime.now(UTC).strftime('%Y%m%d')}",
        f"run.as_of_date={datetime.now(UTC).strftime('%Y-%m-%d')}",
    ]
    _record(run_step("structural_replay", replay_cmd), input_artifacts=[str(bp_path)])

    # Step 6: Bridge
    logger.info("[%d/%d] Running Bridge...", 6, TOTAL_STEPS)
    _record(
        run_step("bridge", [sys.executable, str(ROOT / "scripts" / "bridge_replay_to_current.py")]),
        input_artifacts=[str(ROOT / "Output" / "sandbox" / "structural_replay_v2" / "framework_output.json")],
    )

    # Step 7: Quality validation
    logger.info("[%d/%d] Validating quality fields...", 7, TOTAL_STEPS)
    quality_script = ROOT / "scripts" / "quality_field_validator.py"
    if quality_script.exists():
        _record(run_step("quality_validation", [sys.executable, str(quality_script)]))

    # Step 8: HMM / HMM stability
    logger.info("[%d/%d] Running HMM regime detection + stability audit...", 8, TOTAL_STEPS)
    today_str = datetime.now(UTC).strftime("%Y-%m-%d")
    _record(run_step("regime_detection", [
        sys.executable, "-c",
        "from pathlib import Path; from ml.regime_detector import detect_regime; "
        "import json; "
        "result = detect_regime(Path('Data/harvester/exports/latest/data/benchmark_panel.parquet'), "
        f"source_release='daily', source_created_at='{today_str}', train_window=756, write=True); "
        "print(json.dumps({'regime': result['regime']['current'], "
        "'usable': result['degeneracy']['usable_for_core_judgment'], "
        "'warnings': result['degeneracy']['warnings']}, indent=2))",
    ], env={"PYTHONPATH": str(ROOT / "Workbench" / "src")}))
    hmm_audit_script = ROOT / "scripts" / "hmm_stability_audit.py"
    if hmm_audit_script.exists() and (not _is_weekly("hmm_stability_audit") or args.force_weekly or start_time.weekday() == 0):
        _record(run_step("hmm_stability_audit", [sys.executable, str(hmm_audit_script)]))

    # Step 9: K/X gates
    logger.info("[%d/%d] Running K/X measurement gates...", 9, TOTAL_STEPS)
    k_gate_script = ROOT / "scripts" / "k_measurement_gate.py"
    if k_gate_script.exists():
        _record(run_step("k_measurement_gate", [sys.executable, str(k_gate_script)]))
    x_gate_script = ROOT / "scripts" / "x_measurement_gate.py"
    if x_gate_script.exists():
        _record(run_step("x_measurement_gate", [sys.executable, str(x_gate_script)]))
    mq_script = ROOT / "scripts" / "build_measurement_quality_report.py"
    if mq_script.exists():
        _record(run_step("measurement_quality_report", [sys.executable, str(mq_script)]))

    # Step 10: CaseLab
    logger.info("[%d/%d] Running CaseLab daily signal...", 10, TOTAL_STEPS)
    caselab_script = ROOT / "scripts" / "caselab_daily_signal.py"
    if caselab_script.exists():
        _record(run_step("caselab_signal", [sys.executable, str(caselab_script), "--json"]))

    # Archive daily snapshots for backfill (weekly — maintenance, not signal)
    if start_time.weekday() == 0 or args.force_weekly:
        archive_script = ROOT / "scripts" / "archive_daily_snapshots.py"
        if archive_script.exists():
            _record(run_step("archive_daily_snapshots", [sys.executable, str(archive_script)]))

        backfill_script = ROOT / "scripts" / "backfill_judgment_calibration.py"
        if backfill_script.exists():
            _record(run_step("backfill_judgment_calibration", [sys.executable, str(backfill_script)]))

    # Step 11: Judgment
    logger.info("[%d/%d] Generating judgment card...", 11, TOTAL_STEPS)
    judgment_script = ROOT / "scripts" / "judgment_layer.py"
    if judgment_script.exists():
        _record(
            run_step("judgment_layer", [sys.executable, str(judgment_script)]),
            input_artifacts=[
                str(ROOT / "Output" / "current" / "framework_output.json"),
                str(ROOT / "Output" / "k_measurement" / "k_measurement_gate.json"),
                str(ROOT / "Output" / "x_measurement" / "x_measurement_gate.json"),
                str(ROOT / "Output" / "hmm_stability" / "hmm_stability_audit.json"),
            ],
        )
    # Judgment replay audit (weekly — validation, not signal-blocking)
    if start_time.weekday() == 0 or args.force_weekly:
        judgment_audit_script = ROOT / "scripts" / "judgment_replay_audit.py"
        if judgment_audit_script.exists():
            _record(run_step("judgment_replay_audit", [sys.executable, str(judgment_audit_script)]))

    # Step 12: Promotion gate
    logger.info("[%d/%d] Running judgment promotion gate...", 12, TOTAL_STEPS)
    promotion_script = ROOT / "scripts" / "judgment_promotion_gate.py"
    if promotion_script.exists():
        _record(run_step("judgment_promotion_gate", [sys.executable, str(promotion_script)]))

    # Step 13: Probabilistic context — ARCHIVED (misnamed, was historical quantile calculator, not GluonTS)
    # gluonts_probabilistic_context.py moved to scripts/archive/governance_cut_2026_06_19/

    # Step 13.5: Signal monitor — weekly tracking of M+K prediction accuracy (moved from daily 2026-06-20)
    if start_time.weekday() == 0 or args.force_weekly:
        signal_monitor_script = ROOT / "scripts" / "signal_monitor.py"
        if signal_monitor_script.exists():
            _record(run_step("signal_monitor", [sys.executable, str(signal_monitor_script), "--json"]))

    # Step 14: Trade decision
    logger.info("[%d/%d] Generating trade decision...", 14, TOTAL_STEPS)
    trade_script = ROOT / "scripts" / "trade_decision_layer.py"
    if trade_script.exists():
        _record(
            run_step("trade_decision", [sys.executable, str(trade_script)]),
            input_artifacts=[
                str(ROOT / "Output" / "judgment" / "latest.json"),
                str(ROOT / "Output" / "judgment" / "promotion_gate.json"),
                str(ROOT / "Output" / "k_measurement" / "k_measurement_gate.json"),
                str(ROOT / "Output" / "x_measurement" / "x_measurement_gate.json"),
                str(ROOT / "Output" / "hmm_stability" / "hmm_stability_audit.json"),
            ],
        )

    # Step 15: Risk gate + record to ledger (merged — record is lightweight)
    logger.info("[%d/%d] Running risk gate + recording decision...", 15, TOTAL_STEPS)
    risk_script = ROOT / "scripts" / "trade_risk_gate.py"
    if risk_script.exists():
        _record(run_step("risk_gate", [sys.executable, str(risk_script)]))
    record_script = ROOT / "scripts" / "record_trade_decision.py"
    if record_script.exists():
        _record(run_step("record_trade_decision", [sys.executable, str(record_script)]))

    # Step 16.5: Trade decision replay (weekly — calibration, not signal-blocking)
    if start_time.weekday() == 0 or args.force_weekly:
        replay_script = ROOT / "scripts" / "trade_decision_replay.py"
        if replay_script.exists():
            _record(run_step("trade_decision_replay", [sys.executable, str(replay_script)]))

    # Step 17: Market feedback
    logger.info("[%d/%d] Generating market feedback...", 17, TOTAL_STEPS)
    feedback_script = ROOT / "scripts" / "market_feedback.py"
    if feedback_script.exists():
        _record(run_step("market_feedback", [sys.executable, str(feedback_script)]))

    # Claim evaluation + ladder + Learning Hub feedback (weekly — batch validation)
    if start_time.weekday() == 0 or args.force_weekly:
        claim_eval_script = ROOT / "scripts" / "claim_evaluator.py"
        if claim_eval_script.exists():
            _record(run_step("claim_evaluator", [sys.executable, str(claim_eval_script)]))

        claim_tracker_script = ROOT / "scripts" / "claim_ladder_tracker.py"
        if claim_tracker_script.exists():
            _record(run_step("claim_ladder_tracker", [sys.executable, str(claim_tracker_script)]))

        lh_feedback_script = ROOT / "scripts" / "build_learning_hub_feedback.py"
        if lh_feedback_script.exists():
            _record(run_step("learning_hub_feedback", [sys.executable, str(lh_feedback_script)]))

    # Step 17.8: Proxy quality report (weekly) — proxy_lifecycle archived 2026-06-20 (dead output)
    if not _is_weekly("proxy_quality_report") or args.force_weekly or start_time.weekday() == 0:
        proxy_quality_script = ROOT / "scripts" / "build_proxy_quality_report.py"
        if proxy_quality_script.exists():
            _record(run_step("proxy_quality_report", [sys.executable, str(proxy_quality_script)]))

    # Weekly mechanism causal calibration (Monday UTC, or --force-weekly)
    if start_time.weekday() == 0 or args.force_weekly:
        mechanism_cal_script = ROOT / "scripts" / "run_mechanism_calibration.py"
        if mechanism_cal_script.exists():
            _record(run_step("mechanism_calibration", [sys.executable, str(mechanism_cal_script)]))
        suggest_script = ROOT / "scripts" / "suggest_paper_updates.py"
        if suggest_script.exists():
            _record(run_step("suggest_paper_updates", [sys.executable, str(suggest_script)]))

    # Step 18: Learning comprehensive summary (weekly)
    if not _is_weekly("learning_summary") or args.force_weekly or start_time.weekday() == 0:
        logger.info("[%d/%d] Generating Learning Hub comprehensive summary...", 18, TOTAL_STEPS)
        learning_summary_script = ROOT / "scripts" / "learning_hub_comprehensive_summary.py"
        if learning_summary_script.exists():
            _record(run_step("learning_summary", [sys.executable, str(learning_summary_script)]))
    # Calibration events (weekly — review, not signal)
    if start_time.weekday() == 0 or args.force_weekly:
        calibration_event_script = ROOT / "scripts" / "learning_hub_judgment_calibration.py"
        if calibration_event_script.exists():
            _record(run_step("judgment_calibration_event", [sys.executable, str(calibration_event_script)]))
        trade_calibration_script = ROOT / "scripts" / "learning_hub_trade_calibration.py"
        if trade_calibration_script.exists():
            _record(run_step("trade_calibration_event", [sys.executable, str(trade_calibration_script)]))

    # Export feedback + promote paper inbox (weekly)
    if not _is_weekly("export_feedback") or args.force_weekly or start_time.weekday() == 0:
        export_feedback_script = ROOT / "scripts" / "export_feedback_to_paper.py"
        if export_feedback_script.exists():
            _record(run_step("export_feedback", [sys.executable, str(export_feedback_script)]))
        promote_script = ROOT / "scripts" / "promote_paper_inbox.py"
        if promote_script.exists():
            _record(run_step("promote_paper_inbox", [sys.executable, str(promote_script)]))
        collect_reviews_script = ROOT / "caselab_runtime" / "feedback" / "collect_reviews.py"
        if collect_reviews_script.exists():
            _record(run_step(
                "collect_reviews",
                [sys.executable, "-m", "caselab_runtime.feedback.collect_reviews", "--json"],
            ))

    # Refresh cross-asset panel before evaluation (ensures latest market data)
    panel_refresh_script = ROOT / "scripts" / "refresh_cross_asset_panel.py"
    if panel_refresh_script.exists():
        _record(run_step("refresh_cross_asset_panel", [sys.executable, str(panel_refresh_script)]))

    # Daily pending evaluation (forward-outcome checks for judgment/trade claims)
    evaluate_script = ROOT / "scripts" / "evaluate_pending.py"
    if evaluate_script.exists():
        eval_cmd = [sys.executable, str(evaluate_script)]
        # Lightweight daily: only 1d window; full evaluation on Monday or --force-weekly
        if start_time.weekday() != 0 and not args.force_weekly:
            eval_cmd.append("--daily-only")
        _record(run_step("evaluate_pending", eval_cmd))

    # Judgment accuracy report (aggregate calibration data)
    accuracy_script = ROOT / "scripts" / "judgment_accuracy_report.py"
    if accuracy_script.exists():
        _record(run_step("judgment_accuracy_report", [sys.executable, str(accuracy_script)]))

    # Step 19: Operator registry audit (weekly)
    if not _is_weekly("operator_registry_audit") or args.force_weekly or start_time.weekday() == 0:
        logger.info("[%d/%d] Running operator registry audit...", 19, TOTAL_STEPS)
        operator_audit_script = ROOT / "scripts" / "operator_registry_audit.py"
        if operator_audit_script.exists():
            _record(run_step("operator_registry_audit", [sys.executable, str(operator_audit_script)]))

    # Step 21: Build system index
    logger.info("[%d/%d] Building system index...", 21, TOTAL_STEPS)
    index_script = ROOT / "scripts" / "build_system_index.py"
    if index_script.exists():
        _record(run_step("system_index", [sys.executable, str(index_script)]))

    # Step 22: Build current README / NEXT_ACTIONS (weekly — documentation, not signal)
    if start_time.weekday() == 0 or args.force_weekly:
        logger.info("[%d/%d] Generating README and next actions...", 22, TOTAL_STEPS)
        readme_script = ROOT / "scripts" / "build_readme_first.py"
        if readme_script.exists():
            _record(run_step("readme_first", [sys.executable, str(readme_script)]))
        next_actions_script = ROOT / "scripts" / "build_next_actions.py"
        if next_actions_script.exists():
            _record(run_step("next_actions", [sys.executable, str(next_actions_script)]))

    # Step 23: Build signal card (BEFORE freshness — freshness must validate it)
    logger.info("[%d/%d] Building signal card...", 23, TOTAL_STEPS)
    signal_card_script = ROOT / "scripts" / "build_signal_card.py"
    if signal_card_script.exists():
        _record(run_step("signal_card", [sys.executable, str(signal_card_script)]))

    # Step 24: Build signal consensus (AFTER signal card — reads its output)
    logger.info("[%d/%d] Building signal consensus...", 24, TOTAL_STEPS)
    consensus_script = ROOT / "scripts" / "signal_consensus.py"
    if consensus_script.exists():
        _record(run_step("signal_consensus", [sys.executable, str(consensus_script)]))

    # Step 25: Strategy Lab shadow card (weekly — research-only, not signal)
    if start_time.weekday() == 0 or args.force_weekly:
        logger.info("[%d/%d] Generating Strategy Lab shadow card...", 25, TOTAL_STEPS)
        shadow_card_script = ROOT / "scripts" / "strategy_lab" / "run_backtest.py"
        if shadow_card_script.exists():
            _record(run_step("strategy_lab_shadow", [sys.executable, str(shadow_card_script), "--shadow-card"]))

    # Step 26: Build work brief (BEFORE freshness — freshness must validate it)
    logger.info("[%d/%d] Building work brief...", 26, TOTAL_STEPS)
    work_brief_script = ROOT / "scripts" / "build_work_brief.py"
    if work_brief_script.exists():
        _record(run_step("work_brief", [sys.executable, str(work_brief_script)]))

    # Step 26: Freshness validator (AFTER all current outputs are built)
    logger.info("[%d/%d] Running freshness validator...", 27, TOTAL_STEPS)
    freshness_script = ROOT / "scripts" / "freshness_validator.py"
    if freshness_script.exists():
        _record(run_step("freshness_validator", [sys.executable, str(freshness_script)]))

    # Step 27: Architecture reality audit (weekly)
    if not _is_weekly("architecture_reality_audit") or args.force_weekly or start_time.weekday() == 0:
        logger.info("[%d/%d] Running architecture reality audit...", 28, TOTAL_STEPS)
        architecture_audit_script = ROOT / "scripts" / "architecture_reality_audit.py"
        if architecture_audit_script.exists():
            _record(run_step("architecture_reality_audit", [sys.executable, str(architecture_audit_script)]))

    # Step 28: Governance status (weekly)
    if not _is_weekly("governance_status") or args.force_weekly or start_time.weekday() == 0:
        logger.info("[%d/%d] Building governance status...", 29, TOTAL_STEPS)
        governance_status_script = ROOT / "scripts" / "governance_status.py"
        if governance_status_script.exists():
            _record(run_step("governance_status", [sys.executable, str(governance_status_script)]))

    # ML validation hardening (weekly, review-only)
    if start_time.weekday() == 0 or args.force_weekly:
        asof_script = ROOT / "scripts" / "asof_integrity_checker.py"
        if asof_script.exists():
            _record(run_step("asof_integrity_check", [sys.executable, str(asof_script)]))
        baseline_script = ROOT / "scripts" / "baseline_comparison.py"
        if baseline_script.exists():
            _record(run_step("baseline_comparison", [sys.executable, str(baseline_script)]))
        walkforward_script = ROOT / "scripts" / "weekly_walk_forward_validation.py"
        if walkforward_script.exists():
            _record(run_step("walk_forward_validation", [sys.executable, str(walkforward_script)]))
        threshold_bridge_script = ROOT / "scripts" / "threshold_review_bridge.py"
        if threshold_bridge_script.exists():
            _record(run_step("threshold_review_bridge", [sys.executable, str(threshold_bridge_script)]))

    # Step 29: Change analysis (weekly — trend/anomaly, not signal-blocking)
    if start_time.weekday() == 0 or args.force_weekly:
        logger.info("[%d/%d] Building change analysis...", 30, TOTAL_STEPS)
        change_analysis_script = ROOT / "scripts" / "build_change_analysis.py"
        if change_analysis_script.exists():
            _record(run_step("change_analysis", [sys.executable, str(change_analysis_script)]))

    # Capture decision + signal traces into bundle
    _capture_traces(bundle)

    # Auto-generate feedback pending for degenerate signals
    _collect_feedback_pending(bundle)

    # Record key artifacts into bundle
    for artifact_rel in [
        "Output/current/framework_output.json",
        "Output/current/work_brief.json",
        "Output/strategy_lab/shadow_cards/latest.json",
        "Output/current/signal_card.json",
        "Output/current/signal_consensus.json",
        "Output/current/data_gaps.json",
        "Output/current/change_analysis.json",
    ]:
        artifact = ROOT / artifact_rel
        if artifact.exists():
            bundle.record_artifact(artifact)

    # Runtime event
    end_time = datetime.now(UTC)
    freshness = check_freshness()
    warnings = check_warnings()
    run_status = "success" if all(s.get("status") == "success" for s in steps) else "partial_failure"
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

    # Refresh governance status after the bundle has its final manifest.
    governance_status_script = ROOT / "scripts" / "governance_status.py"
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
    fw_path = ROOT / "Output" / "current" / "framework_output.json"
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


if __name__ == "__main__":
    main()
