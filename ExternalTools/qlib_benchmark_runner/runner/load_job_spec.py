"""Load and validate a qlib_job_spec.json file.

Part of the external Qlib runner — must not import main system code.
"""

from __future__ import annotations

import json
from pathlib import Path


def load_job_spec(job_spec_path: Path) -> dict:
    if not job_spec_path.exists():
        raise FileNotFoundError(f"Job spec not found: {job_spec_path}")
    return json.loads(job_spec_path.read_text(encoding="utf-8"))


def validate_job_spec(spec: dict) -> list[str]:
    errors = []
    required = ["job_id", "benchmark_id", "input_dir", "output_dir", "experiments"]
    for key in required:
        if key not in spec:
            errors.append(f"Missing required key: {key}")
    return errors
