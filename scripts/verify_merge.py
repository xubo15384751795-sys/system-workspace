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
REMOTE_ENFORCEMENT_STATUS = "COMPENSATING_CONTROL_ONLY"


def _load_stateful_root_tests() -> tuple[str, ...]:
    """Expose the classification inventory without duplicating it in code."""
    classification = ROOT / "tests" / "stateful_test_classification.yaml"
    try:
        import yaml

        payload = yaml.safe_load(classification.read_text(encoding="utf-8")) or {}
        return tuple(
            str(item["path"])
            for item in payload.get("items", [])
            if isinstance(item, dict) and item.get("class") == "operator_workspace"
        )
    except (OSError, KeyError, TypeError, ValueError):
        return ()


# Compatibility export used by the classification contract test. The actual
# merge gate delegates selection to the root pyproject.toml and does not maintain a second
# ignore list.
STATEFUL_ROOT_TESTS = _load_stateful_root_tests()

def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT,
            capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() if out.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _run_step(
    name: str,
    cmd: list[str],
    *,
    cwd: Path = ROOT,
    timeout: int = 600,
) -> dict:
    """Run a verification step. Returns {name, passed, returncode, duration_s}."""
    import time

    t0 = time.time()
    # Ensure subprocess steps can import scripts/ and workbench/ without each
    # command having to sys.path.insert (which the security audit forbids).
    pythonpath_entries = [
        str(cwd),
        *([str(cwd / "src")] if (cwd / "src").is_dir() else []),
        str(ROOT),
        str(ROOT / "packages" / "framework" / "src"),
        str(ROOT / "packages" / "workbench" / "src"),
        str(ROOT / "packages" / "harvester" / "src"),
        str(ROOT / "packages" / "learning_hub" / "src"),
        str(ROOT / "packages" / "orchestration"),
        str(ROOT / "scripts"),
    ]
    inherited_pythonpath = os.environ.get("PYTHONPATH", "").strip()
    if inherited_pythonpath:
        pythonpath_entries.append(inherited_pythonpath)
    env = {
        **os.environ,
        # Use absolute entries because package-suite steps run with a package
        # directory as cwd; relative ``packages/workbench/src`` then points
        # at a non-existent nested path.
        "PYTHONPATH": os.pathsep.join(pythonpath_entries),
    }
    try:
        out = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env,
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


def merge_gate_steps() -> list[tuple[str, list[str], Path]]:
    """The 10-item merge-gate chain. Each must pass; no continue-on-error."""
    py = sys.executable
    # The root pyproject.toml is the single classification authority. It excludes
    # operator/network/external_repo/slow suites for clean-checkout evidence;
    # this gate must not maintain a second hand-written ignore list.
    root_clean_checkout = [py, "-m", "pytest", "tests/", "-q", "--tb=short"]
    return [
        ("root_clean_checkout_pytest", root_clean_checkout, ROOT),
        ("workbench_suite", [py, "-m", "pytest", "tests/", "-q"], ROOT / "packages" / "workbench"),
        ("harvester_suite", [py, "-m", "pytest", "tests/", "-q"], ROOT / "packages" / "harvester"),
        ("framework_suite", [py, "-m", "pytest", "tests/", "-q"], ROOT / "packages" / "framework"),
        ("learning_hub_suite", [py, "-m", "pytest", "tests/", "-q"], ROOT / "packages" / "learning_hub"),
        ("dag_compile_check", [py, "-c",
            "from _pipeline_dag import compile_dag; "
            "dag=compile_dag(); "
            "assert dag['valid'], dag; print('dag valid')"], ROOT),
        ("governance_freeze", [py, "-m", "scripts.check_governance_freeze"], ROOT),
        ("architecture_audit", [py, "scripts/commands/weekly/architecture_reality_audit.py"], ROOT),
        ("daily_run_dry_run", [py, "scripts/daily_run.py", "--dry-run"], ROOT),
        ("phase_a_incident_regression", [py, "-m", "pytest",
            "tests/test_phase_a_incident_regression.py", "-q"], ROOT),
    ]


def run_merge_gate() -> dict:
    """Run the full merge gate. Returns the verification manifest."""
    sha = _git_sha()
    steps = merge_gate_steps()
    results = []
    for name, cmd, cwd in steps:
        print(f"[merge-gate] {name}...", flush=True)
        r = _run_step(name, cmd, cwd=cwd)
        results.append(r)
        status = "PASS" if r["passed"] else "FAIL"
        print(f"  -> {status} ({r['duration_s']}s)", flush=True)
        if not r["passed"]:
            # Stop on first failure: a merge gate is all-green.
            if r.get("stdout_tail"):
                print(f"  stdout tail:\n{r['stdout_tail']}", flush=True)
            if r.get("stderr_tail"):
                print(f"  stderr tail:\n{r['stderr_tail']}", flush=True)
            break

    passed_count = sum(1 for r in results if r["passed"])
    failed_count = sum(1 for r in results if not r["passed"])
    verdict = "PASS" if failed_count == 0 else "FAIL"

    manifest = {
        "schema_version": "system.merge_gate_manifest.v1",
        "commit": sha,
        "verdict": verdict,
        "ran_at": datetime.now(UTC).isoformat(),
        # Private GitHub plans cannot enable classic branch protection.
        # merge-gate + SHA-bound manifest is the substitute required control.
        # See governance/routing_decisions/2026-07-27-ci-enforcement-private-repo.yaml
        "enforcement_mode": "private_repo_substitute",
        "remote_enforcement_status": REMOTE_ENFORCEMENT_STATUS,
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
    mode = manifest.get("enforcement_mode")
    if mode not in (None, "private_repo_substitute"):
        return False, f"unexpected enforcement_mode={mode}"
    remote_status = manifest.get("remote_enforcement_status")
    if remote_status not in (None, REMOTE_ENFORCEMENT_STATUS):
        return False, f"unexpected remote_enforcement_status={remote_status}"
    if mode == "private_repo_substitute" and remote_status != REMOTE_ENFORCEMENT_STATUS:
        return False, "missing remote_enforcement_status=COMPENSATING_CONTROL_ONLY"
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
