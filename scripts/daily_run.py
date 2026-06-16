#!/usr/bin/env python3
"""Scheduled Batch Monitor — daily automated run.

Usage:
    python3 scripts/daily_run.py              # full run
    python3 scripts/daily_run.py --skip-harvester  # skip data fetch
    python3 scripts/daily_run.py --dry-run    # print plan, don't execute

Output:
    Output/runtime_events/YYYY-MM-DD.jsonl
    Output/alerts/latest_alert.md
    Output/alerts/latest_alert.json
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "Output" / "runtime_events"
ALERT_DIR = ROOT / "Output" / "alerts"

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


def write_runtime_event(event: dict) -> None:
    """Append event to daily JSONL log."""
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    path = RUNTIME_DIR / f"{today}.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, default=str, ensure_ascii=False) + "\n")


def write_alert(warnings: list[str], steps: list[dict]) -> None:
    """Write alert files."""
    ALERT_DIR.mkdir(parents=True, exist_ok=True)
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

    (ALERT_DIR / "latest_alert.json").write_text(
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

    (ALERT_DIR / "latest_alert.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Scheduled Batch Monitor")
    parser.add_argument("--skip-harvester", action="store_true")
    parser.add_argument("--skip-etf", action="store_true", help="Skip ETF panel refresh step")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    start_time = datetime.now(UTC)
    print(f"=== Daily Run — {start_time.strftime('%Y-%m-%d %H:%M')} ===")

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

    # Step 1: Harvester
    if not args.skip_harvester:
        print(f"[1/{TOTAL_STEPS}] Running Harvester...")
        steps.append(run_step("harvester", [sys.executable, "-m", "harvester", "daily-release"]))
    else:
        print(f"[1/{TOTAL_STEPS}] Skipping Harvester (--skip-harvester)")

    # Step 2: Refresh ETF panel
    if not args.skip_etf:
        print(f"[2/{TOTAL_STEPS}] Refreshing ETF panel...")
        etf_script = ROOT / "scripts" / "refresh_etf_panel.py"
        if etf_script.exists():
            steps.append(run_step("etf_refresh", [sys.executable, str(etf_script)]))
    else:
        print(f"[2/{TOTAL_STEPS}] Skipping ETF refresh (--skip-etf)")

    # Step 3: Paper world model sync
    print(f"[3/{TOTAL_STEPS}] Syncing Paper world model...")
    paper_sync_script = ROOT / "scripts" / "sync_paper_world_model.py"
    if paper_sync_script.exists():
        steps.append(run_step("paper_sync", [sys.executable, str(paper_sync_script)]))

    # Step 4: Horizon event adapter
    print(f"[4/{TOTAL_STEPS}] Running Horizon event adapter...")
    horizon_script = ROOT / "scripts" / "horizon_event_adapter.py"
    if horizon_script.exists():
        steps.append(run_step("horizon_events", [sys.executable, str(horizon_script), "--sample"]))

    # Step 5: Structural Replay
    print(f"[5/{TOTAL_STEPS}] Running Structural Replay...")
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
    steps.append(run_step("structural_replay", replay_cmd))

    # Step 6: Bridge
    print(f"[6/{TOTAL_STEPS}] Running Bridge...")
    steps.append(run_step("bridge", [sys.executable, str(ROOT / "scripts" / "bridge_replay_to_current.py")]))

    # Step 7: Quality validation
    print(f"[7/{TOTAL_STEPS}] Validating quality fields...")
    quality_script = ROOT / "scripts" / "quality_field_validator.py"
    if quality_script.exists():
        steps.append(run_step("quality_validation", [sys.executable, str(quality_script)]))

    # Step 8: HMM / HMM stability
    print(f"[8/{TOTAL_STEPS}] Running HMM regime detection + stability audit...")
    steps.append(run_step("regime_detection", [
        sys.executable, "-c",
        "from pathlib import Path; from ml.regime_detector import detect_regime; "
        "detect_regime(Path('Data/harvester/exports/latest/data/benchmark_panel.parquet'), "
        "source_release='daily', source_created_at='" + datetime.now(UTC).strftime("%Y-%m-%d") + "', write=True)",
    ], env={"PYTHONPATH": str(ROOT / "Workbench" / "src")}))
    hmm_audit_script = ROOT / "scripts" / "hmm_stability_audit.py"
    if hmm_audit_script.exists():
        steps.append(run_step("hmm_stability_audit", [sys.executable, str(hmm_audit_script)]))

    # Step 9: K/X gates
    print(f"[9/{TOTAL_STEPS}] Running K/X measurement gates...")
    k_gate_script = ROOT / "scripts" / "k_measurement_gate.py"
    if k_gate_script.exists():
        steps.append(run_step("k_measurement_gate", [sys.executable, str(k_gate_script)]))
    x_gate_script = ROOT / "scripts" / "x_measurement_gate.py"
    if x_gate_script.exists():
        steps.append(run_step("x_measurement_gate", [sys.executable, str(x_gate_script)]))

    # Step 10: CaseLab
    print(f"[10/{TOTAL_STEPS}] Running CaseLab daily signal...")
    caselab_script = ROOT / "scripts" / "caselab_daily_signal.py"
    if caselab_script.exists():
        steps.append(run_step("caselab_signal", [sys.executable, str(caselab_script), "--json"]))

    # Step 11: Judgment
    print(f"[11/{TOTAL_STEPS}] Generating judgment card...")
    judgment_script = ROOT / "scripts" / "judgment_layer.py"
    if judgment_script.exists():
        steps.append(run_step("judgment_layer", [sys.executable, str(judgment_script)]))
    judgment_audit_script = ROOT / "scripts" / "judgment_replay_audit.py"
    if judgment_audit_script.exists():
        steps.append(run_step("judgment_replay_audit", [sys.executable, str(judgment_audit_script)]))

    # Step 12: Promotion gate
    print(f"[12/{TOTAL_STEPS}] Running judgment promotion gate...")
    promotion_script = ROOT / "scripts" / "judgment_promotion_gate.py"
    if promotion_script.exists():
        steps.append(run_step("judgment_promotion_gate", [sys.executable, str(promotion_script)]))

    # Step 13: Probabilistic context
    print(f"[13/{TOTAL_STEPS}] Generating probabilistic context...")
    prob_script = ROOT / "scripts" / "gluonts_probabilistic_context.py"
    if prob_script.exists():
        steps.append(run_step("probabilistic_context", [sys.executable, str(prob_script)]))

    # Step 14: Trade decision
    print(f"[14/{TOTAL_STEPS}] Generating trade decision...")
    trade_script = ROOT / "scripts" / "trade_decision_layer.py"
    if trade_script.exists():
        steps.append(run_step("trade_decision", [sys.executable, str(trade_script)]))

    # Step 15: Risk gate
    print(f"[15/{TOTAL_STEPS}] Running risk gate...")
    risk_script = ROOT / "scripts" / "trade_risk_gate.py"
    if risk_script.exists():
        steps.append(run_step("risk_gate", [sys.executable, str(risk_script)]))

    # Step 16: Record trade decision
    print(f"[16/{TOTAL_STEPS}] Recording trade decision...")
    record_script = ROOT / "scripts" / "record_trade_decision.py"
    if record_script.exists():
        steps.append(run_step("record_trade_decision", [sys.executable, str(record_script)]))

    # Step 17: Market feedback
    print(f"[17/{TOTAL_STEPS}] Generating market feedback...")
    feedback_script = ROOT / "scripts" / "market_feedback.py"
    if feedback_script.exists():
        steps.append(run_step("market_feedback", [sys.executable, str(feedback_script)]))

    # Step 18: Learning comprehensive summary
    print(f"[18/{TOTAL_STEPS}] Generating Learning Hub comprehensive summary...")
    learning_summary_script = ROOT / "scripts" / "learning_hub_comprehensive_summary.py"
    if learning_summary_script.exists():
        steps.append(run_step("learning_summary", [sys.executable, str(learning_summary_script)]))
    calibration_event_script = ROOT / "scripts" / "learning_hub_judgment_calibration.py"
    if calibration_event_script.exists():
        steps.append(run_step("judgment_calibration_event", [sys.executable, str(calibration_event_script)]))
    trade_calibration_script = ROOT / "scripts" / "learning_hub_trade_calibration.py"
    if trade_calibration_script.exists():
        steps.append(run_step("trade_calibration_event", [sys.executable, str(trade_calibration_script)]))

    # Step 19: Operator registry audit
    print(f"[19/{TOTAL_STEPS}] Running operator registry audit...")
    operator_audit_script = ROOT / "scripts" / "operator_registry_audit.py"
    if operator_audit_script.exists():
        steps.append(run_step("operator_registry_audit", [sys.executable, str(operator_audit_script)]))

    # Step 20: Position sizing layer
    print(f"[20/{TOTAL_STEPS}] Running position sizing layer...")
    position_script = ROOT / "scripts" / "position_sizing_layer.py"
    if position_script.exists():
        steps.append(run_step("position_sizing", [sys.executable, str(position_script)]))

    # Step 21: Build system index
    print(f"[21/{TOTAL_STEPS}] Building system index...")
    index_script = ROOT / "scripts" / "build_system_index.py"
    if index_script.exists():
        steps.append(run_step("system_index", [sys.executable, str(index_script)]))

    # Step 22: Build current README / NEXT_ACTIONS
    print(f"[22/{TOTAL_STEPS}] Generating README and next actions...")
    readme_script = ROOT / "scripts" / "build_readme_first.py"
    if readme_script.exists():
        steps.append(run_step("readme_first", [sys.executable, str(readme_script)]))
    next_actions_script = ROOT / "scripts" / "build_next_actions.py"
    if next_actions_script.exists():
        steps.append(run_step("next_actions", [sys.executable, str(next_actions_script)]))

    # Step 23: Freshness validator (after index/README to check their timestamps)
    print(f"[23/{TOTAL_STEPS}] Running freshness validator...")
    freshness_script = ROOT / "scripts" / "freshness_validator.py"
    if freshness_script.exists():
        steps.append(run_step("freshness_validator", [sys.executable, str(freshness_script)]))

    # Step 24: Architecture reality audit (non-strict daily sensor)
    print(f"[24/{TOTAL_STEPS}] Running architecture reality audit...")
    architecture_audit_script = ROOT / "scripts" / "architecture_reality_audit.py"
    if architecture_audit_script.exists():
        steps.append(run_step("architecture_reality_audit", [sys.executable, str(architecture_audit_script)]))

    # Runtime event
    end_time = datetime.now(UTC)
    freshness = check_freshness()
    warnings = check_warnings()
    event = {
        "run_id": f"daily_{start_time.strftime('%Y%m%d_%H%M')}",
        "started_at": start_time.isoformat(),
        "finished_at": end_time.isoformat(),
        "duration_s": round((end_time - start_time).total_seconds(), 1),
        "status": "success" if all(s.get("status") == "success" for s in steps) else "partial_failure",
        "steps": steps,
        "warnings": warnings,
        "data_freshness": freshness,
    }
    write_runtime_event(event)
    write_alert(warnings, steps)

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


if __name__ == "__main__":
    main()
