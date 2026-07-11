"""Paper world model freshness checks.

Phase 4: stale Paper no longer lowers claim_ceiling in judgment_layer.
Freshness is recorded on the judgment card; trade decision size steps down.
``lower_claim_ceiling_for_stale`` remains for legacy callers only.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_TTL_HOURS = 72


def _root() -> Path:
    return Path(os.environ.get("SYSTEM_ROOT", Path(__file__).resolve().parents[1]))


def load_manifest(manifest_path: Path | None = None) -> dict[str, Any] | None:
    path = manifest_path or (_root() / "Data" / "paper_world_model" / "manifest.json")
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def check_paper_world_model_freshness(
    *,
    ttl_hours: int = DEFAULT_TTL_HOURS,
    manifest_path: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    manifest = load_manifest(manifest_path)
    if not manifest:
        return {
            "fresh": False,
            "stale": True,
            "age_hours": None,
            "synced_at": None,
            "reason": "manifest_missing",
            "ttl_hours": ttl_hours,
        }

    synced_at_raw = manifest.get("synced_at")
    if not synced_at_raw:
        return {
            "fresh": False,
            "stale": True,
            "age_hours": None,
            "synced_at": None,
            "reason": "synced_at_missing",
            "ttl_hours": ttl_hours,
            "manifest": manifest,
        }

    synced_at = datetime.fromisoformat(str(synced_at_raw).replace("Z", "+00:00"))
    age_hours = (now - synced_at).total_seconds() / 3600
    stale = age_hours > ttl_hours
    return {
        "fresh": not stale,
        "stale": stale,
        "age_hours": round(age_hours, 2),
        "synced_at": synced_at_raw,
        "reason": "ttl_exceeded" if stale else "ok",
        "ttl_hours": ttl_hours,
        "manifest": manifest,
    }


def lower_claim_ceiling_for_stale(current: str) -> str:
    """Downgrade claim ceiling when Paper world model is stale."""
    order = [
        "diagnostic_observation",
        "diagnostic_watch_only",
        "mechanism_hypothesis",
        "watch_condition",
        "structural_diagnostic_with_caveats",
        "structural_diagnostic",
    ]
    if current in order:
        idx = order.index(current)
        return order[max(0, idx - 2)] if idx >= 2 else "diagnostic_watch_only"
    if current == "structural_diagnostic":
        return "mechanism_hypothesis"
    return "diagnostic_watch_only"
