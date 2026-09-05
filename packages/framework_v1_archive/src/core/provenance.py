from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from typing import Any


def build_provenance(config: dict[str, Any], run_date: str) -> dict[str, Any]:
    try:
        git_hash = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        git_hash = "unknown"
    config_string = json.dumps(config, sort_keys=True, default=str)
    data_version = str(config.get("data", {}).get("version", "unknown"))
    run_timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "run_date": run_date,
        "data_version": data_version,
        "code_version": git_hash,
        "config_version": hashlib.sha256(config_string.encode("utf-8")).hexdigest(),
        "run_timestamp": run_timestamp,
    }
