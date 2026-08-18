"""Isolation audit: verify that every benchmark run respects sandbox boundaries.

Runs after a benchmark completes. Produces isolation_audit.json which is
checked by benchmark_gate before allowing Learning Hub events.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from workbench.paths import workspace_root as _workspace_root

BENCHMARKS_ROOT = _workspace_root() / "Output" / "benchmarks" / "market_feedback"
MAIN_SRC_ROOT = _workspace_root() / "Workbench" / "src"

logger = logging.getLogger(__name__)

QLIB_IMPORT_RE = re.compile(r'^\s*(import\s+qlib\b|from\s+qlib\b)', re.MULTILINE)


def run_isolation_audit(benchmark_id: str) -> dict:
    """Run all isolation checks and produce audit report."""
    benchmark_dir = BENCHMARKS_ROOT / benchmark_id

    checks = []

    # Check 1: main system does not import qlib
    result = _check_no_qlib_imports()
    checks.append({"name": "no_src_qlib_import", "status": result["status"], "detail": result.get("detail")})

    # Check 2: input_dir is sandboxed
    result = _check_path_sandboxed(benchmark_dir, "sandbox_input")
    checks.append({"name": "input_dir_is_sandboxed", "status": result["status"], "detail": result.get("detail")})

    # Check 3: output_dir is sandboxed
    result = _check_path_sandboxed(benchmark_dir, "qlib_output")
    checks.append({"name": "output_dir_is_sandboxed", "status": result["status"], "detail": result.get("detail")})

    # Check 4: no forbidden paths in job spec
    result = _check_job_spec_forbidden(benchmark_dir)
    checks.append({"name": "no_forbidden_path_in_job_spec", "status": result["status"], "detail": result.get("detail")})

    # Check 5: learning event excludes raw qlib payload
    result = _check_learning_event_clean(benchmark_dir)
    checks.append({"name": "learning_event_excludes_raw_payload", "status": result["status"], "detail": result.get("detail")})

    # Check 6: no writes to Data/ or deformation_runs/
    result = _check_no_forbidden_writes(benchmark_dir)
    checks.append({"name": "no_write_to_data_or_deformation_outputs", "status": result["status"], "detail": result.get("detail")})

    passed = all(c["status"] == "passed" for c in checks)

    audit = {
        "benchmark_id": benchmark_id,
        "run_at": datetime.now(timezone.utc).isoformat(),
        "isolation_status": "passed" if passed else "failed",
        "checks": checks,
    }

    audit_path = benchmark_dir / "isolation_audit.json"
    audit_path.write_text(json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8")

    return audit


def _check_no_qlib_imports() -> dict:
    """Scan main system source for actual qlib import statements."""
    offenders = []
    if MAIN_SRC_ROOT.exists():
        for path in MAIN_SRC_ROOT.rglob("*.py"):
            try:
                text = path.read_text(encoding="utf-8")
                if QLIB_IMPORT_RE.search(text):
                    offenders.append(str(path))
            except Exception:
                logger.warning("Unable to inspect benchmark source for Qlib imports: %s", path, exc_info=True)

    if offenders:
        return {"status": "failed", "detail": f"Qlib imports found in: {offenders}"}
    return {"status": "passed"}


def _check_path_sandboxed(benchmark_dir: Path, subdir: str) -> dict:
    """Verify a subdirectory exists inside the benchmark directory."""
    path = benchmark_dir / subdir
    if not path.exists():
        return {"status": "skipped", "detail": f"{subdir} directory does not exist"}
    return {"status": "passed"}


def _check_job_spec_forbidden(benchmark_dir: Path) -> dict:
    """Check job spec paths for forbidden patterns."""
    forbidden = ["Data/", "packages/workbench/src", "Output/deformation_runs/", "Output/system_learning/"]
    spec_path = benchmark_dir / "qlib_job_spec.json"
    if not spec_path.exists():
        return {"status": "skipped", "detail": "qlib_job_spec.json not found"}

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    for key in ["input_dir", "workspace_dir", "output_dir"]:
        value = spec.get(key, "")
        for f in forbidden:
            if f in value:
                return {"status": "failed", "detail": f"{key}={value!r} contains forbidden {f!r}"}
    return {"status": "passed"}


def _check_learning_event_clean(benchmark_dir: Path) -> dict:
    """Verify benchmark event has no raw Qlib payload."""
    event_path = benchmark_dir / "events" / "benchmark_event.json"
    if not event_path.exists():
        return {"status": "skipped", "detail": "benchmark_event.json not yet generated"}

    event = json.loads(event_path.read_text(encoding="utf-8"))
    forbidden_keys = {"predictions", "raw_positions", "qlib_cache", "raw_model"}
    found = [k for k in forbidden_keys if k in event]
    if found:
        return {"status": "failed", "detail": f"Raw Qlib keys in event: {found}"}
    return {"status": "passed"}


def _check_no_forbidden_writes(benchmark_dir: Path) -> dict:
    """Check for output files written to forbidden locations."""
    root = _workspace_root()
    forbidden_dirs = [
        root / "Data",
        root / "Output" / "deformation_runs",
        root / "Output" / "system_learning",
    ]
    offenders = []
    for fd in forbidden_dirs:
        if fd.exists():
            for f in fd.rglob("*"):
                if f.is_file() and str(benchmark_dir.name) in str(f):
                    offenders.append(str(f))
    if offenders:
        return {"status": "failed", "detail": f"Files in forbidden dirs: {offenders}"}
    return {"status": "passed"}
