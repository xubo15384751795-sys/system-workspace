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
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    start_time = datetime.now(UTC)
    print(f"=== Daily Run — {start_time.strftime('%Y-%m-%d %H:%M')} ===")

    if args.dry_run:
        print("DRY RUN — would execute:")
        if not args.skip_harvester:
            print("  1. Harvester (python3 -m harvester daily-release)")
        print("  2. Structural Replay (python3 scripts/structural_replay_v2.py ...)")
        print("  3. Bridge (python3 scripts/bridge_replay_to_current.py)")
        print("  4. Warnings check")
        print("  5. Research Posture + Practicality Trial Daily Note")
        print("  6. Learning Hub Governance Audit")
        print("  7. Runtime event logging")
        return

    steps = []

    # Step 1: Harvester
    if not args.skip_harvester:
        print("[1/6] Running Harvester...")
        steps.append(run_step("harvester", [sys.executable, "-m", "harvester", "daily-release"]))
    else:
        print("[1/6] Skipping Harvester (--skip-harvester)")

    # Step 2: Structural Replay
    print("[2/6] Running Structural Replay...")
    # Find latest harvester release
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

    # Step 3: Bridge
    print("[3/6] Running Bridge...")
    steps.append(run_step("bridge", [sys.executable, str(ROOT / "scripts" / "bridge_replay_to_current.py")]))

    # Step 4: Warnings + Alerts
    print("[4/6] Checking warnings...")
    freshness = check_freshness()
    warnings = check_warnings()

    # Step 5: Research posture digest (Hub) → Practicality Trial Daily Note.
    # Posture must run first so the note consumes a fresh research_posture.json.
    print("[5/6] Generating research posture + practicality note...")
    hub_src = ROOT / "system-learning-hub" / "src"
    steps.append(run_step(
        "research_posture",
        [sys.executable, "-m", "system_learning", "research-posture"],
        env={"PYTHONPATH": str(hub_src)},
    ))
    today_str = datetime.now(UTC).strftime("%Y-%m-%d")
    practicality_script = ROOT / "scripts" / "practicality_daily_note.py"
    if practicality_script.exists():
        steps.append(run_step("practicality_note", [sys.executable, str(practicality_script), f"--date={today_str}"]))

    # Step 6.5: CaseLab daily signal
    print("[6.5/7] Running CaseLab daily signal...")
    caselab_script = ROOT / "scripts" / "caselab_daily_signal.py"
    if caselab_script.exists():
        steps.append(run_step("caselab_signal", [sys.executable, str(caselab_script), "--json"]))

    # Step 7: Learning Hub Governance Audit (blocks reuse of contaminated/frozen/
    # missing-artifact entities on the live daily surface; non-fatal to the run).
    print("[6/6] Running Learning Hub governance audit...")
    hub_src = ROOT / "system-learning-hub" / "src"
    steps.append(run_step(
        "governance_audit",
        [sys.executable, "-m", "system_learning", "governance-audit", "--raise-on-block"],
        env={"PYTHONPATH": str(hub_src)},
    ))

    # Runtime event
    end_time = datetime.now(UTC)
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
