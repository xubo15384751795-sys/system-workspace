"""Invoke the external Qlib runner via subprocess — never via import.

This is the ONLY bridge between the main system and Qlib. It uses subprocess
so Qlib failures cannot corrupt the main Python process.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from workbench.paths import workspace_root as _workspace_root
from typing import Optional

BENCHMARKS_ROOT = _workspace_root() / "Output" / "benchmarks" / "market_feedback"
QLIB_RUNNER_SCRIPT = Path("ExternalTools/qlib_benchmark_runner/run_qlib_benchmark.py")


def resolve_qlib_python() -> Path:
    """Find the Qlib sandbox Python interpreter."""
    candidates = [
        Path("ExternalTools/qlib_benchmark_runner/.venv/bin/python"),
        Path(".venvs/qlib-benchmark/bin/python"),
    ]
    for c in candidates:
        if c.exists():
            return c.resolve()
    return Path("python3").resolve()


def run_qlib_subprocess(
    job_spec_path: Path,
    qlib_python: Optional[Path] = None,
    timeout_seconds: int = 3600,
) -> dict:
    """Execute Qlib benchmark via subprocess. Returns {returncode, stdout, stderr, ...}."""
    qlib_python = qlib_python or resolve_qlib_python()

    cmd = [
        str(qlib_python),
        str(QLIB_RUNNER_SCRIPT),
        "--job-spec",
        str(job_spec_path.resolve()),
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )

    benchmark_dir = job_spec_path.parent
    log_dir = benchmark_dir / "qlib_output"
    log_dir.mkdir(parents=True, exist_ok=True)

    (log_dir / "stdout.log").write_text(result.stdout, encoding="utf-8")
    (log_dir / "stderr.log").write_text(result.stderr, encoding="utf-8")

    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "status": "completed" if result.returncode == 0 else "failed",
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }


def run_external_executor(benchmark_id: str) -> dict:
    """Full lifecycle: load job spec, run subprocess, return outcome."""
    job_spec_path = BENCHMARKS_ROOT / benchmark_id / "qlib_job_spec.json"

    if not job_spec_path.exists():
        return {
            "benchmark_id": benchmark_id,
            "status": "failed",
            "error": f"Job spec not found: {job_spec_path}",
        }

    json.loads(job_spec_path.read_text(encoding="utf-8"))

    # Check if Qlib runner script exists
    if not QLIB_RUNNER_SCRIPT.exists():
        _write_failure_marker(
            benchmark_id,
            "qlib_runner_not_found",
            f"Qlib runner script not found: {QLIB_RUNNER_SCRIPT}",
        )
        return {
            "benchmark_id": benchmark_id,
            "status": "failed",
            "error": f"Qlib runner not found: {QLIB_RUNNER_SCRIPT}",
        }

    qlib_python = resolve_qlib_python()
    result = run_qlib_subprocess(
        job_spec_path=job_spec_path,
        qlib_python=qlib_python,
    )

    if result["returncode"] != 0:
        _write_failure_marker(
            benchmark_id,
            "qlib_subprocess_failed",
            f"Qlib subprocess returned {result['returncode']}: {result['stderr'][:2000]}",
        )

    return {
        "benchmark_id": benchmark_id,
        "status": result["status"],
        "returncode": result["returncode"],
        "qlib_python": str(qlib_python),
    }


def _write_failure_marker(benchmark_id: str, error_type: str, message: str) -> None:
    """Write a failure marker so downstream collectors know the run failed cleanly."""
    benchmark_dir = BENCHMARKS_ROOT / benchmark_id
    output_dir = benchmark_dir / "qlib_output"
    output_dir.mkdir(parents=True, exist_ok=True)

    failure = {
        "benchmark_id": benchmark_id,
        "error_type": error_type,
        "message": message,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "benchmark_status": "failed",
    }
    (output_dir / "failure_marker.json").write_text(
        json.dumps(failure, indent=2, ensure_ascii=False), encoding="utf-8"
    )
