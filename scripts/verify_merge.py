#!/usr/bin/env python3
"""./sys verify --merge  (Phase C3)

The single canonical merge-gate command. Runs the full verification chain
and emits a SHA-bound verification manifest. No required job uses
continue-on-error or ``|| true``; focused tests are dev feedback only, not
merge proof.

Usage:
    ./sys verify --merge            # full merge gate
    python3 scripts/verify_merge.py --merge

Emits Output/verification/merge_gate_manifest.json bound to the current
commit SHA. A stale manifest (different SHA) is automatically invalid.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


MANIFEST_DIR = ROOT / "Output" / "verification"
MANIFEST_PATH = MANIFEST_DIR / "merge_gate_manifest.json"


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT,
            capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() if out.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _run_step(name: str, cmd: list[str], timeout: int = 600) -> dict:
    """Run a verification step. Returns {name, passed, returncode, duration_s}."""
    import time

    t0 = time.time()
    # Ensure subprocess steps can import scripts/ and workbench/ without each
    # command having to sys.path.insert (which the security audit forbids).
    env = {
        **os.environ,
        "PYTHONPATH": ".:packages/framework/src:packages/workbench/src:scripts",
    }
    try:
        out = subprocess.run(
            cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout, env=env,
        )
        passed = out.returncode == 0
        return {
            "name": name,
            "passed": passed,
            "returncode": out.returncode,
            "duration_s": round(time.time() - t0, 1),
            "stdout_tail": out.stdout[-500:] if out.stdout else "",
            "stderr_tail": out.stderr[-500:] if out.stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {
            "name": name, "passed": False, "returncode": -1,
            "duration_s": timeout, "error": "timeout",
        }
    except Exception as exc:
        return {
            "name": name, "passed": False, "returncode": -1,
            "duration_s": round(time.time() - t0, 1), "error": str(exc),
        }


def merge_gate_steps() -> list[tuple[str, list[str]]]:
    """The 10-item merge-gate chain. Each must pass; no continue-on-error."""
    py = sys.executable
    return [
        ("root_full_pytest", [py, "-m", "pytest", "tests/", "-q", "--tb=short"]),
        ("workbench_suite", [py, "-m", "pytest", "packages/workbench/tests/", "-q"]),
        ("harvester_suite", [py, "-m", "pytest", "packages/harvester/tests/", "-q"]),
        ("framework_suite", [py, "-m", "pytest", "packages/framework/tests/", "-q"]),
        ("learning_hub_suite", [py, "-m", "pytest", "packages/learning_hub/tests/", "-q"]),
        ("dag_compile_check", [py, "-c",
            "from _pipeline_dag import compile_dag; "
            "dag=compile_dag(); "
            "assert dag['valid'], dag; print('dag valid')"]),
        ("governance_freeze", [py, "scripts/check_governance_freeze.py"]),
        ("architecture_audit", [py, "scripts/commands/weekly/architecture_reality_audit.py"]),
        ("daily_run_dry_run", [py, "scripts/daily_run.py", "--dry-run"]),
        ("phase_a_incident_regression", [py, "-m", "pytest",
            "tests/test_phase_a_incident_regression.py", "-q"]),
    ]


def run_merge_gate() -> dict:
    """Run the full merge gate. Returns the verification manifest."""
    sha = _git_sha()
    steps = merge_gate_steps()
    results = []
    for name, cmd in steps:
        print(f"[merge-gate] {name}...", flush=True)
        r = _run_step(name, cmd)
        results.append(r)
        status = "PASS" if r["passed"] else "FAIL"
        print(f"  -> {status} ({r['duration_s']}s)", flush=True)
        if not r["passed"]:
            # Stop on first failure: a merge gate is all-green.
            print(f"  stderr: {r.get('stderr_tail','')[:300]}", flush=True)
            break

    passed_count = sum(1 for r in results if r["passed"])
    failed_count = sum(1 for r in results if not r["passed"])
    verdict = "PASS" if failed_count == 0 else "FAIL"

    manifest = {
        "schema_version": "system.merge_gate_manifest.v1",
        "commit": sha,
        "verdict": verdict,
        "ran_at": datetime.now(UTC).isoformat(),
        "steps_total": len(results),
        "steps_passed": passed_count,
        "steps_failed": failed_count,
        "bypasses": 0,
        "steps": [
            {"name": r["name"], "passed": r["passed"],
             "returncode": r["returncode"], "duration_s": r["duration_s"]}
            for r in results
        ],
    }
    return manifest


def write_manifest(manifest: dict) -> Path:
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return MANIFEST_PATH


def is_manifest_valid_for_sha(sha: str | None = None) -> tuple[bool, str]:
    """Check the existing manifest is valid for the given (or current) SHA."""
    if not MANIFEST_PATH.exists():
        return False, "no manifest"
    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"unparseable: {exc}"
    target = sha or _git_sha()
    if manifest.get("commit") != target:
        return False, f"stale: manifest={manifest.get('commit')} sha={target}"
    if manifest.get("verdict") != "PASS":
        return False, f"verdict={manifest.get('verdict')}"
    return True, "valid"


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge-gate verification.")
    parser.add_argument("--merge", action="store_true", help="Run the full merge gate.")
    parser.add_argument("--check", action="store_true",
                        help="Only check the existing manifest validity for this SHA.")
    args = parser.parse_args()

    if args.check:
        ok, reason = is_manifest_valid_for_sha()
        print(f"merge-gate manifest: {reason}")
        return 0 if ok else 1

    if not args.merge:
        parser.error("specify --merge or --check")

    manifest = run_merge_gate()
    path = write_manifest(manifest)
    print(f"\nmerge-gate verdict: {manifest['verdict']}")
    print(f"  steps: {manifest['steps_passed']}/{manifest['steps_total']} passed")
    print(f"  manifest: {path}")
    print(f"  commit: {manifest['commit']}")
    return 0 if manifest["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
