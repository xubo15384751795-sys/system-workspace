"""External indicator health ledger (Phase 2.2).

Each harvester release records per-indicator success/failure into
``Data/system_index/external_indicator_health.json``. ``build_next_actions``
reads it: indicators failing >= 7 consecutive days surface as HIGH-priority
NEXT_ACTIONS, so an indicator going stale (the OFR/CISS 73-day-blind-spot
failure mode) is visible within a week, not after two months.

Schema (external_indicator_health.json):
    {
      "SRISK": {"last_success": "2026-07-10", "consecutive_failures": 8, "last_error": "..."},
      "COVAR": {"last_success": "2026-07-18", "consecutive_failures": 0, "last_error": ""},
      ...
    }
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from _runtime_io import ROOT

HEALTH_PATH = ROOT / "Data" / "system_index" / "external_indicator_health.json"
FAILURE_THRESHOLD_DAYS = 7  # >= this many consecutive failures -> HIGH action


def _load_ledger(path: Path | None = None) -> dict[str, dict[str, Any]]:
    p = path or HEALTH_PATH
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def record_indicator_outcomes(
    outcomes: dict[str, dict[str, Any]],
    *,
    path: Path | None = None,
) -> None:
    """Update the health ledger with per-indicator outcomes from a release.

    ``outcomes`` maps indicator name -> {"success": bool, "error": str, "date": str}.
    On success: last_success = date, consecutive_failures = 0, last_error = "".
    On failure: consecutive_failures += 1, last_error = error (last_success unchanged).
    """
    p = path or HEALTH_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    ledger = _load_ledger(p)
    today = datetime.now(UTC).date().isoformat()
    for name, outcome in outcomes.items():
        entry = ledger.setdefault(name, {
            "last_success": "", "consecutive_failures": 0, "last_error": "",
        })
        date = outcome.get("date", today)
        if outcome.get("success"):
            entry["last_success"] = date
            entry["consecutive_failures"] = 0
            entry["last_error"] = ""
        else:
            entry["consecutive_failures"] = int(entry.get("consecutive_failures", 0)) + 1
            entry["last_error"] = str(outcome.get("error", ""))[:300]
    p.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def failing_indicators(threshold: int = FAILURE_THRESHOLD_DAYS, *, path: Path | None = None) -> list[dict[str, Any]]:
    """Return indicators with consecutive_failures >= threshold, sorted by
    failure count descending. Each entry: {name, last_success, consecutive_failures, last_error}.
    """
    ledger = _load_ledger(path)
    failing = [
        {"name": name, **entry}
        for name, entry in ledger.items()
        if int(entry.get("consecutive_failures", 0)) >= threshold
    ]
    failing.sort(key=lambda e: e["consecutive_failures"], reverse=True)
    return failing
