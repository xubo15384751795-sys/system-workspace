"""Atomic publish gate for Output/current artifacts.

During daily_run, scripts write to run_dir/current_candidate via CURRENT_OUTPUT_DIR.
After all steps succeed and freshness passes, candidate files are published to
Output/current/ and latest_run_id.txt is updated.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from scripts._constants import TIMEOUT_STANDARD
from scripts._runtime_io import (
    ROOT,
    compatibility_surface_dir,
    ensure_dir,
    load_yaml,
    surface_dir,
)

logger = logging.getLogger(__name__)

ROUTING_POLICY = ROOT / "governance" / "output_routing_policy.yaml"
LATEST_RUN_ID = compatibility_surface_dir("current") / "latest_run_id.txt"
PUBLISHED_CURRENT = compatibility_surface_dir("current")


def begin_candidate(run_dir: Path) -> Path:
    """Route current-writing scripts to the run's candidate directory."""
    candidate = surface_dir("current") if os.environ.get("SYSTEM_GENERATION_DIR") else run_dir / "current_candidate"
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
    """Atomically publish candidate artifacts into Output/current/.

    Phase B5: instead of a per-file copy2/symlink loop (which leaves a mix of
    new + stale artifacts visible to readers on a mid-loop crash), materialize
    all allowed artifacts into a staging directory adjacent to the target, then
    swap the whole directory atomically with os.replace (POSIX rename). The
    latest_run_id.txt pointer is written into staging so it swaps together.
    """
    generation_mode = os.environ.get("SYSTEM_GENERATION_MODE", "").strip().lower() in {"1", "true", "yes"}
    if generation_mode or (root / "Output" / "live").is_symlink():
        raise RuntimeError(
            "legacy current publisher is disabled in generation topology; use PublishTransaction.commit_generation"
        )
    target = root / "Output" / "current"
    ensure_dir(target.parent)
    staging = target.parent / f".current_staging.{os.getpid()}"
    if staging.exists():
        shutil.rmtree(staging)
    ensure_dir(staging)

    published: list[str] = []
    for name in candidate_artifact_names():
        src = candidate_dir / name
        if not src.exists():
            continue
        dest = staging / name
        if src.is_symlink():
            dest.symlink_to(src.resolve())
        else:
            shutil.copy2(src, dest)
        published.append(name)

    # Write the run_id pointer into staging so it swaps atomically with the
    # artifact files - consumers never see a pointer that names a run whose
    # artifacts are not yet visible.
    (staging / "latest_run_id.txt").write_text(run_id + "\n", encoding="utf-8")

    # Atomic swap: rename staging -> target. On POSIX, rename over an existing
    # directory is atomic only when target is empty; so rename the old target
    # aside first, then rename staging into place, then remove the old one.
    retired = target.parent / f".current_retired.{os.getpid()}"
    if target.exists():
        os.replace(target, retired)
    os.replace(staging, target)
    if retired.exists():
        shutil.rmtree(retired, ignore_errors=True)
    return {"published": published, "count": len(published)}


def run_freshness_check(
    root: Path = ROOT,
    *,
    gate: str = "publish",
) -> dict[str, Any]:
    """Run freshness_validator; return parsed JSON if available.

    ``gate=publish`` is the publish-boundary hard check (complete candidate).
    """
    script = root / "scripts" / "freshness_validator.py"
    if not script.exists():
        return {"status": "skipped", "reason": "freshness_validator missing"}
    env = os.environ.copy()
    env["FRESHNESS_GATE"] = gate
    result = subprocess.run(
        [sys.executable, str(script), "--json", "--gate", gate],
        capture_output=True,
        text=True,
        timeout=TIMEOUT_STANDARD,
        cwd=str(root),
        env=env,
    )
    if result.returncode != 0 and result.stdout.strip():
        try:
            payload = json.loads(result.stdout)
            payload["exit_code"] = result.returncode
            return payload
        except json.JSONDecodeError:
            logger.warning("Freshness validator failure output was not valid JSON")
    if result.stdout.strip():
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            logger.warning("Freshness validator output was not valid JSON")
    return {
        "status": "fail" if result.returncode != 0 else "pass",
        "exit_code": result.returncode,
        "stderr": (result.stderr or "")[-500:],
    }


def should_publish(run_status: str, freshness: dict[str, Any]) -> tuple[bool, str]:
    """Publish gate: only allow publication on explicit freshness PASS.

    The ``freshness_assumed_ok`` escape hatch has been removed (WP2).
    Unknown/missing freshness verdicts now BLOCK instead of allowing
    publication.
    """
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
    # Unknown/missing verdict: BLOCK (no more assumed_ok).
    return False, f"freshness_unknown_verdict={overall or 'missing'}"


def should_publish_with_provenance(
    run_status: str, freshness: dict[str, Any], artifact_index: list[dict] | None = None
) -> tuple[bool, str]:
    """Phase B3 publish gate: freshness + provenance validation_verdict.

    Extends should_publish: if any recorded artifact's provenance carries a
    ``validation_verdict`` of "fail" or "reject", publishing is blocked even
    when freshness passes. This closes the gap where a step produced a
    validation-failed artifact but the run status stayed "success".
    """
    ok, reason = should_publish(run_status, freshness)
    if not ok:
        return ok, reason
    if artifact_index:
        for entry in artifact_index:
            prov = entry.get("provenance") or {}
            verdict = str(prov.get("validation_verdict", "pass")).lower()
            if verdict in ("fail", "reject"):
                return False, f"validation_verdict={verdict}:{entry.get('path','?')}"
    return ok, reason
