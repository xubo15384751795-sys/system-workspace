"""Variation-inlet health owned by Learning Hub, never by judgment code."""
from __future__ import annotations

import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def count_current_entries(inbox: Path) -> int:
    if not inbox.is_file():
        return 0
    lines = inbox.read_text(encoding="utf-8").splitlines()
    marker = (
        "<!-- Add raw one-line hypotheses below. "
        "Comments and blank lines do not count. -->"
    )
    if marker in lines:
        lines = lines[lines.index(marker) + 1 :]
    return sum(
        1
        for raw in lines
        if raw.strip() and not raw.lstrip().startswith(("#", "<!--", "1.", "2."))
    )


def count_recent_additions(root: Path, *, days: int = 30) -> int:
    """Approximate monthly inlet volume from Git additions.

    Git history is the durable clock. For an untracked/new inbox, current raw
    entries count immediately so initial setup is not reported as an outage.
    """
    inbox = root / "hypotheses_inbox.md"
    result = subprocess.run(
        [
            "git",
            "log",
            f"--since={days} days ago",
            "--format=",
            "--numstat",
            "--",
            "hypotheses_inbox.md",
        ],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    additions = 0
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            parts = line.split("\t", 2)
            if len(parts) == 3 and parts[0].isdigit():
                additions += int(parts[0])
    if additions == 0:
        status = subprocess.run(
            ["git", "status", "--porcelain", "--", "hypotheses_inbox.md"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        age_seconds = (
            time.time() - inbox.stat().st_mtime if inbox.is_file() else float("inf")
        )
        if status.stdout.strip() and age_seconds <= days * 24 * 3600:
            additions = count_current_entries(inbox)
    return additions


def build_variation_health(root: Path, *, days: int = 30) -> dict[str, Any]:
    inbox = root / "hypotheses_inbox.md"
    current_entries = count_current_entries(inbox)
    recent_additions = count_recent_additions(root, days=days)
    deviations: list[str] = []
    if not inbox.is_file():
        deviations.append("hypotheses inbox is missing")
    if recent_additions == 0:
        deviations.append(f"zero hypothesis inflow during the last {days} days")
    return {
        "schema_version": "system.variation_health.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "window_days": days,
        "current_entry_count": current_entries,
        "recent_added_line_count": recent_additions,
        "status": "DEVIATION" if deviations else "PASS",
        "deviations": deviations,
        "authority": "none",
    }


def write_variation_health(report: dict[str, Any], root: Path) -> Path:
    path = root / "Output" / "system_learning" / "latest" / "hypothesis_inflow.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


__all__ = [
    "build_variation_health",
    "count_current_entries",
    "count_recent_additions",
    "write_variation_health",
]
