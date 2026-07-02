"""Atomic publish gate for Output/current artifacts.

During daily_run, scripts write to run_dir/current_candidate via CURRENT_OUTPUT_DIR.
After all steps succeed and freshness passes, candidate files are published to
Output/current/ and latest_run_id.txt is updated.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from _constants import TIMEOUT_STANDARD
from _runtime_io import ROOT, ensure_dir, load_yaml

ROUTING_POLICY = ROOT / "governance" / "output_routing_policy.yaml"
LATEST_RUN_ID = ROOT / "Output" / "current" / "latest_run_id.txt"
PUBLISHED_CURRENT = ROOT / "Output" / "current"


def begin_candidate(run_dir: Path) -> Path:
    """Route current-writing scripts to the run's candidate directory."""
    candidate = run_dir / "current_candidate"
    ensure_dir(candidate)
    os.environ["CURRENT_OUTPUT_DIR"] = str(candidate)
    return candidate


def clear_candidate_env() -> None:
    os.environ.pop("CURRENT_OUTPUT_DIR", None)


def candidate_artifact_names() -> list[str]:
    """Filenames allowed in groups.current (routing policy)."""
    policy = load_yaml(ROUTING_POLICY)
    allowed = policy.get("groups", {}).get("current", {}).get("allowed_artifacts", [])
    return [str(name) for name in allowed if isinstance(name, str)]


def publish_candidate(candidate_dir: Path, *, run_id: str, root: Path = ROOT) -> dict[str, Any]:
    """Copy candidate artifacts into Output/current/ and update latest_run_id.txt."""
    target = root / "Output" / "current"
    ensure_dir(target)
    published: list[str] = []
    for name in candidate_artifact_names():
        src = candidate_dir / name
        if not src.exists():
            continue
        dest = target / name
        if src.is_symlink():
            if dest.exists() or dest.is_symlink():
                dest.unlink()
            dest.symlink_to(src.resolve())
        else:
            shutil.copy2(src, dest)
        published.append(name)

    ensure_dir(LATEST_RUN_ID.parent)
    LATEST_RUN_ID.write_text(run_id + "\n", encoding="utf-8")
    return {"published": published, "count": len(published)}


def run_freshness_check(root: Path = ROOT) -> dict[str, Any]:
    """Run freshness_validator; return parsed JSON if available."""
    script = root / "scripts" / "freshness_validator.py"
    if not script.exists():
        return {"status": "skipped", "reason": "freshness_validator missing"}
    result = subprocess.run(
        [sys.executable, str(script), "--json"],
        capture_output=True,
        text=True,
        timeout=TIMEOUT_STANDARD,
        cwd=str(root),
    )
    if result.returncode != 0 and result.stdout.strip():
        try:
            payload = json.loads(result.stdout)
            payload["exit_code"] = result.returncode
            return payload
        except json.JSONDecodeError:
            pass
    if result.stdout.strip():
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            pass
    return {
        "status": "fail" if result.returncode != 0 else "pass",
        "exit_code": result.returncode,
        "stderr": (result.stderr or "")[-500:],
    }


def should_publish(run_status: str, freshness: dict[str, Any]) -> tuple[bool, str]:
    if run_status != "success":
        return False, f"run_status={run_status}"
    overall = str(freshness.get("verdict", freshness.get("overall_status", freshness.get("status", "")))).upper()
    if overall == "PASS":
        return True, "freshness_pass"
    stale = freshness.get("stale_artifacts") or []
    if stale:
        return False, f"stale_artifacts={len(stale)}"
    if freshness.get("exit_code", 0) not in (0, None):
        return False, "freshness_validator_failed"
    if overall in {"FAIL", "STALE", "VIOLATION"}:
        return False, f"freshness_{overall.lower()}"
    return True, "freshness_assumed_ok"
