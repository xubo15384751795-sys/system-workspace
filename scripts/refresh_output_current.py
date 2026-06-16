#!/usr/bin/env python3
"""Refresh Output/current — unified authority entry point.

This is the ONLY script that should refresh Output/current/.
It runs the new judgment chain, not the old Workbench fallback.

Chain:
    1. bridge_replay_to_current.py
    2. judgment_layer.py
    3. judgment_promotion_gate.py
    4. build_readme_first.py

Usage:
    python3 scripts/refresh_output_current.py
    python3 scripts/refresh_output_current.py --skip-bridge
    python3 scripts/refresh_output_current.py --dry-run

Output:
    Output/current/framework_output.json
    Output/current/00_READ_ME_FIRST.md
    Output/judgment/latest.json
    Output/judgment/latest.md
    Output/judgment/promotion_gate.json
    Output/judgment/promotion_gate.md
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CURRENT = ROOT / "Output" / "current"
JUDGMENT = ROOT / "Output" / "judgment"


def run_step(name: str, cmd: list[str]) -> dict:
    """Run a subprocess and capture result."""
    start = time.time()
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120,
            cwd=str(ROOT),
        )
        duration = time.time() - start
        return {
            "step": name,
            "status": "success" if result.returncode == 0 else "failed",
            "returncode": result.returncode,
            "duration_s": round(duration, 1),
            "stdout_tail": result.stdout[-300:] if result.stdout else "",
            "stderr_tail": result.stderr[-300:] if result.stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {"step": name, "status": "timeout", "duration_s": 120}
    except Exception as e:
        return {"step": name, "status": "error", "error": str(e), "duration_s": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh Output/current with new judgment chain.")
    parser.add_argument("--skip-bridge", action="store_true", help="Skip bridge step.")
    parser.add_argument("--dry-run", action="store_true", help="Print plan, don't execute.")
    args = parser.parse_args()

    start_time = datetime.now(UTC)

    if args.dry_run:
        print("DRY RUN — would execute:")
        if not args.skip_bridge:
            print("  1. bridge_replay_to_current.py")
        print("  2. judgment_layer.py")
        print("  3. judgment_promotion_gate.py")
        print("  4. build_readme_first.py")
        return 0

    steps = []

    # Step 1: Bridge (unless skipped)
    if not args.skip_bridge:
        print("[1/4] Running bridge...")
        steps.append(run_step("bridge", [sys.executable, str(ROOT / "scripts" / "bridge_replay_to_current.py")]))
    else:
        print("[1/4] Skipping bridge (--skip-bridge)")

    # Step 2: Judgment Layer
    print("[2/4] Generating judgment card...")
    steps.append(run_step("judgment_layer", [sys.executable, str(ROOT / "scripts" / "judgment_layer.py")]))

    # Step 3: Promotion Gate
    print("[3/4] Running promotion gate...")
    steps.append(run_step("promotion_gate", [sys.executable, str(ROOT / "scripts" / "judgment_promotion_gate.py")]))

    # Step 4: Build README
    print("[4/4] Building 00_READ_ME_FIRST.md...")
    steps.append(run_step("readme_first", [sys.executable, str(ROOT / "scripts" / "build_readme_first.py")]))

    # Summary
    end_time = datetime.now(UTC)
    duration = (end_time - start_time).total_seconds()
    failed = [s for s in steps if s["status"] != "success"]

    print(f"\n=== Refresh Complete ({duration:.1f}s) ===")
    for s in steps:
        icon = "✅" if s["status"] == "success" else "❌"
        print(f"  {icon} {s['step']}: {s['status']} ({s['duration_s']}s)")

    if failed:
        print(f"\n{len(failed)} step(s) failed.")
        return 1

    # Verify outputs exist
    required = [
        CURRENT / "framework_output.json",
        CURRENT / "00_READ_ME_FIRST.md",
        JUDGMENT / "latest.json",
        JUDGMENT / "latest.md",
        JUDGMENT / "promotion_gate.json",
        JUDGMENT / "promotion_gate.md",
    ]
    missing = [p for p in required if not p.exists()]
    if missing:
        print(f"\nWARNING: Missing outputs: {[str(p) for p in missing]}")
        return 1

    print("\nAll outputs verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
