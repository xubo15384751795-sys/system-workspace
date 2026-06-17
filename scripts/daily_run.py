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

import json
import logging
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "Output" / "runtime_events"
ALERT_DIR = ROOT / "Output" / "alerts"

# RunBundle integration — use auditable path management
from _workspace_imports import add_scripts
add_scripts()
from run_bundle import RunBundle

# Total steps in the pipeline
TOTAL_STEPS = 24


def run_step(name: str, cmd: list[str], env: dict | None = None) -> dict:
    """Run a subprocess and capture result."""
    start = time.time()
    merged_env = {**os.environ, **(env or {})}
    # Remove proxy vars for harvester
    for key in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"]:
        merged_env.pop(key, None)

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600,
            cwd=str(ROOT), env=merged_env,
        )
        duration = time.time() - start
        return {
            "step": name,
            "status": "success" if result.returncode == 0 else "failed",
            "returncode": result.returncode,
            "duration_s": round(duration, 1),
            "stdout_tail": result.stdout[-500:] if result.stdout else "",
            "stderr_tail": result.stderr[-500:] if result.stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {"step": name, "status": "timeout", "duration_s": 600}
    except Exception as e:
        return {"step": name, "status": "error", "error": str(e), "duration_s": 0}


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
                pass
    else:
        warnings.append("HARVESTER_MISSING: no latest release")

    return warnings


def write_runtime_event(event: dict, output_root: Path | None = None) -> None:
    """Append event to daily JSONL log."""
    runtime_dir = output_root / "runtime_events" if output_root else RUNTIME_DIR
    runtime_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    path = runtime_dir / f"{today}.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, default=str, ensure_ascii=False) + "\n")


def write_alert(warnings: list[str], steps: list[dict], output_root: Path | None = None) -> None:
    """Write alert files."""
    alert_dir = output_root / "alerts" if output_root else ALERT_DIR
    alert_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).isoformat()
    failed_steps = [s for s in steps if s.get("status") != "success"]

    alert = {
        "timestamp": now,
        "severity": "HIGH" if failed_steps else ("MEDIUM" if warnings else "LOW"),
        "warnings": warnings,
        "failed_steps": [s["step"] for s in failed_steps],
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


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Scheduled Batch Monitor")
    parser.add_argument("--skip-harvester", action="store_true")
    parser.add_argument("--skip-etf", action="store_true", help="Skip ETF panel refresh step")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--output-root", type=str, default=None,
        help="Redirect Output/ under this root (for test isolation). "
             "Sets DAILY_OUTPUT_ROOT env for child scripts.",
    )
    args = parser.parse_args()

    # Configure logging: process steps go to log, CLI summary stays as print
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # Resolve output root — default is ROOT/Output, override for test isolation
    output_root = Path(args.output_root) if args.output_root else ROOT / "Output"
    if args.output_root:
        output_root.mkdir(parents=True, exist_ok=True)
        os.environ["DAILY_OUTPUT_ROOT"] = str(output_root)

    start_time = datetime.now(UTC)
    logger.info("Daily Run — %s", start_time.strftime('%Y-%m-%d %H:%M'))

    # Start run bundle — atomic record of this execution
    # Always use ROOT for bundle location (bundles live in Output/runs/, not test output root)
    bundle = RunBundle.start(mode="daily_pipeline")
    logger.info("Run bundle: %s", bundle.run_id)

    if args.dry_run:
        print("DRY RUN — would execute:")
        steps = [
            "1. Harvester",
            "2. ETF refresh",
            "3. Paper world model sync",
            "4. Horizon event adapter",
            "5. Structural replay",
            "6. Bridge",
            "7. Quality validation",
            "8. HMM / HMM stability",
            "9. K/X gates",
            "10. CaseLab",
            "11. Judgment",
            "12. Promotion gate",
            "13. Probabilistic context",
            "14. Trade decision",
            "15. Risk gate",
            "16. Record trade decision",
            "17. Market feedback",
            "18. Learning comprehensive summary",
            "19. Operator registry audit",
            "20. Position sizing layer",
            "21. Build system index",
            "22. Build current README / NEXT_ACTIONS",
            "23. Freshness validator",
            "24. Architecture reality audit",
        ]
        for step in steps:
            print(f"  {step}")
        return

    steps = []

    def _record(step_result: dict) -> None:
        """Record step into both local list and run bundle."""
        steps.append(step_result)
        bundle.record_step(
            name=step_result["step"],
            status=step_result.get("status", "unknown"),
            duration_s=step_result.get("duration_s", 0),
            returncode=step_result.get("returncode", 0),
        )

    # Step 1: Harvester
    if not args.skip_harvester:
        logger.info("[%d/%d] Running Harvester...", 1, TOTAL_STEPS)
        _record(run_step("harvester", [sys.executable, "-m", "harvester", "daily-release"]))
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

    # Step 4: Horizon event adapter
    logger.info("[%d/%d] Running Horizon event adapter...", 4, TOTAL_STEPS)
    horizon_script = ROOT / "scripts" / "horizon_event_adapter.py"
    if horizon_script.exists():
        _record(run_step("horizon_events", [sys.executable, str(horizon_script), "--sample"]))

    # Step 5: Structural Replay
    logger.info("[%d/%d] Running Structural Replay...", 5, TOTAL_STEPS)
    latest = ROOT / "Data" / "harvester" / "exports" / "latest"
    catalog_path = latest / "catalog.json"
    release_id = "latest"
    if catalog_path.exists():
        try:
            cat = json.loads(catalog_path.read_text(encoding="utf-8"))
            release_id = cat.get("release_id", "latest")
        except Exception:
            pass

    bp_path = latest / "data" / "benchmark_panel.parquet"
    replay_cmd = [
        sys.executable, str(ROOT / "scripts" / "structural_replay_v2.py"),
        f"panel.release_id={release_id}",
        f"panel.path={bp_path}",
        f"run.tag=daily_{datetime.now(UTC).strftime('%Y%m%d')}",
    ]
    _record(run_step("structural_replay", replay_cmd))

    # Step 6: Bridge
    logger.info("[%d/%d] Running Bridge...", 6, TOTAL_STEPS)
    _record(run_step("bridge", [sys.executable, str(ROOT / "scripts" / "bridge_replay_to_current.py")]))

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
    if hmm_audit_script.exists():
        _record(run_step("hmm_stability_audit", [sys.executable, str(hmm_audit_script)]))

    # Step 9: K/X gates
    logger.info("[%d/%d] Running K/X measurement gates...", 9, TOTAL_STEPS)
    k_gate_script = ROOT / "scripts" / "k_measurement_gate.py"
    if k_gate_script.exists():
        _record(run_step("k_measurement_gate", [sys.executable, str(k_gate_script)]))
    x_gate_script = ROOT / "scripts" / "x_measurement_gate.py"
    if x_gate_script.exists():
        _record(run_step("x_measurement_gate", [sys.executable, str(x_gate_script)]))

    # Step 10: CaseLab
    logger.info("[%d/%d] Running CaseLab daily signal...", 10, TOTAL_STEPS)
    caselab_script = ROOT / "scripts" / "caselab_daily_signal.py"
    if caselab_script.exists():
        _record(run_step("caselab_signal", [sys.executable, str(caselab_script), "--json"]))

    # Step 11: Judgment
    logger.info("[%d/%d] Generating judgment card...", 11, TOTAL_STEPS)
    judgment_script = ROOT / "scripts" / "judgment_layer.py"
    if judgment_script.exists():
        _record(run_step("judgment_layer", [sys.executable, str(judgment_script)]))
    judgment_audit_script = ROOT / "scripts" / "judgment_replay_audit.py"
    if judgment_audit_script.exists():
        _record(run_step("judgment_replay_audit", [sys.executable, str(judgment_audit_script)]))

    # Step 12: Promotion gate
    logger.info("[%d/%d] Running judgment promotion gate...", 12, TOTAL_STEPS)
    promotion_script = ROOT / "scripts" / "judgment_promotion_gate.py"
    if promotion_script.exists():
        _record(run_step("judgment_promotion_gate", [sys.executable, str(promotion_script)]))

    # Step 13: Probabilistic context
    logger.info("[%d/%d] Generating probabilistic context...", 13, TOTAL_STEPS)
    prob_script = ROOT / "scripts" / "gluonts_probabilistic_context.py"
    if prob_script.exists():
        _record(run_step("probabilistic_context", [sys.executable, str(prob_script)]))

    # Step 14: Trade decision
    logger.info("[%d/%d] Generating trade decision...", 14, TOTAL_STEPS)
    trade_script = ROOT / "scripts" / "trade_decision_layer.py"
    if trade_script.exists():
        _record(run_step("trade_decision", [sys.executable, str(trade_script)]))

    # Step 15: Risk gate
    logger.info("[%d/%d] Running risk gate...", 15, TOTAL_STEPS)
    risk_script = ROOT / "scripts" / "trade_risk_gate.py"
    if risk_script.exists():
        _record(run_step("risk_gate", [sys.executable, str(risk_script)]))

    # Step 16: Record trade decision
    logger.info("[%d/%d] Recording trade decision...", 16, TOTAL_STEPS)
    record_script = ROOT / "scripts" / "record_trade_decision.py"
    if record_script.exists():
        _record(run_step("record_trade_decision", [sys.executable, str(record_script)]))

    # Step 17: Market feedback
    logger.info("[%d/%d] Generating market feedback...", 17, TOTAL_STEPS)
    feedback_script = ROOT / "scripts" / "market_feedback.py"
    if feedback_script.exists():
        _record(run_step("market_feedback", [sys.executable, str(feedback_script)]))

    # Step 18: Learning comprehensive summary
    logger.info("[%d/%d] Generating Learning Hub comprehensive summary...", 18, TOTAL_STEPS)
    learning_summary_script = ROOT / "scripts" / "learning_hub_comprehensive_summary.py"
    if learning_summary_script.exists():
        _record(run_step("learning_summary", [sys.executable, str(learning_summary_script)]))
    calibration_event_script = ROOT / "scripts" / "learning_hub_judgment_calibration.py"
    if calibration_event_script.exists():
        _record(run_step("judgment_calibration_event", [sys.executable, str(calibration_event_script)]))
    trade_calibration_script = ROOT / "scripts" / "learning_hub_trade_calibration.py"
    if trade_calibration_script.exists():
        _record(run_step("trade_calibration_event", [sys.executable, str(trade_calibration_script)]))

    # Step 19: Operator registry audit
    logger.info("[%d/%d] Running operator registry audit...", 19, TOTAL_STEPS)
    operator_audit_script = ROOT / "scripts" / "operator_registry_audit.py"
    if operator_audit_script.exists():
        _record(run_step("operator_registry_audit", [sys.executable, str(operator_audit_script)]))

    # Step 20: Position sizing layer
    logger.info("[%d/%d] Running position sizing layer...", 20, TOTAL_STEPS)
    position_script = ROOT / "scripts" / "position_sizing_layer.py"
    if position_script.exists():
        _record(run_step("position_sizing", [sys.executable, str(position_script)]))

    # Step 21: Build system index
    logger.info("[%d/%d] Building system index...", 21, TOTAL_STEPS)
    index_script = ROOT / "scripts" / "build_system_index.py"
    if index_script.exists():
        _record(run_step("system_index", [sys.executable, str(index_script)]))

    # Step 22: Build current README / NEXT_ACTIONS
    logger.info("[%d/%d] Generating README and next actions...", 22, TOTAL_STEPS)
    readme_script = ROOT / "scripts" / "build_readme_first.py"
    if readme_script.exists():
        _record(run_step("readme_first", [sys.executable, str(readme_script)]))
    next_actions_script = ROOT / "scripts" / "build_next_actions.py"
    if next_actions_script.exists():
        _record(run_step("next_actions", [sys.executable, str(next_actions_script)]))

    # Step 23: Freshness validator (after index/README to check their timestamps)
    logger.info("[%d/%d] Running freshness validator...", 23, TOTAL_STEPS)
    freshness_script = ROOT / "scripts" / "freshness_validator.py"
    if freshness_script.exists():
        _record(run_step("freshness_validator", [sys.executable, str(freshness_script)]))

    # Step 24: Architecture reality audit (non-strict daily sensor)
    logger.info("[%d/%d] Running architecture reality audit...", 24, TOTAL_STEPS)
    architecture_audit_script = ROOT / "scripts" / "architecture_reality_audit.py"
    if architecture_audit_script.exists():
        _record(run_step("architecture_reality_audit", [sys.executable, str(architecture_audit_script)]))

    # Capture decision + signal traces into bundle
    _capture_traces(bundle)

    # Auto-generate feedback pending for degenerate signals
    _collect_feedback_pending(bundle)

    # Record key artifacts into bundle
    for artifact_rel in [
        "Output/current/framework_output.json",
        "Output/current/work_brief.json",
        "Output/current/signal_card.json",
        "Output/current/data_gaps.json",
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

    # Finish run bundle
    bundle_dir = bundle.finish(status=run_status)
    logger.info("Run bundle saved: %s", bundle_dir)

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
    print(f"\n=== Summary ===")
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
            pass

    # Judgment confidence low
    judgment_path = ROOT / "Output" / "judgment" / "latest.json"
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
            pass


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
                pass

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
            pass

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
            pass


if __name__ == "__main__":
    main()
