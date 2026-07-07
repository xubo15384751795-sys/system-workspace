from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from system_learning import __version__
from system_learning.governance.lifecycle import GOVERNANCE_RULES_VERSION
from system_learning.schema import SCHEMA_VERSION

SENSOR_VERSIONS: dict[str, str] = {
    "ingestion": "1.0",
    "runtime_log": "1.0",
    "cartography": "1.0",
    "ml_integrity": "1.0",
    "analyzers": "1.0",
}


@dataclass(frozen=True)
class RunContext:
    """Immutable identity for one Hub orchestration run."""

    run_id: str
    started_at: str
    mode: str
    schema_version: str
    governance_rules_version: str
    sensor_versions: dict[str, str]
    hub_version: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def new_run_context(*, mode: str = "full", run_id: str | None = None) -> RunContext:
    started_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    resolved_id = run_id or f"hub-{started_at.replace(':', '').replace('-', '')[:15]}-{uuid.uuid4().hex[:8]}"
    return RunContext(
        run_id=resolved_id,
        started_at=started_at,
        mode=mode,
        schema_version=SCHEMA_VERSION,
        governance_rules_version=GOVERNANCE_RULES_VERSION,
        sensor_versions=dict(SENSOR_VERSIONS),
        hub_version=__version__,
    )


def filter_events_since(events: list[dict], since: str | None) -> list[dict]:
    if not since:
        return events
    return [event for event in events if str(event.get("timestamp", "")) >= since]
