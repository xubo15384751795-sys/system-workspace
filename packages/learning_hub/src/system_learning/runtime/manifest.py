from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from system_learning.runtime.context import RunContext


def write_run_manifest(
    runs_dir: Path,
    context: RunContext,
    *,
    steps: list[str],
    stats: dict[str, Any],
    outputs: dict[str, str],
) -> Path:
    runs_dir.mkdir(parents=True, exist_ok=True)
    path = runs_dir / f"{context.run_id}.json"
    payload = {
        "run": context.to_dict(),
        "steps": steps,
        "stats": stats,
        "outputs": outputs,
        "completed_at": stats.get("completed_at"),
    }
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    latest = runs_dir / "latest.json"
    latest.write_text(json.dumps({"run_id": context.run_id, "manifest": str(path)}, indent=2) + "\n", encoding="utf-8")
    return path


def read_last_run_id(runs_dir: Path) -> str | None:
    latest = runs_dir / "latest.json"
    if not latest.exists():
        return None
    try:
        payload = json.loads(latest.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return str(payload.get("run_id") or "")
