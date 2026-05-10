from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKBENCH_SRC = ROOT / "Workbench" / "src"
if str(WORKBENCH_SRC) not in sys.path:
    sys.path.insert(0, str(WORKBENCH_SRC))

from workbench.governance.authority import AuthorityRegistry, write_authority_event


def test_authority_registry_blocks_forbidden_operation() -> None:
    registry = AuthorityRegistry(ROOT / "governance" / "module_authority_registry.yaml")

    check = registry.check("Deformation", "DIRECT_HTTP_ACQUIRE")

    assert check.allowed is False
    assert check.event_type == "AUTHORITY_VIOLATION"
    assert "explicitly forbidden" in check.reason


def test_authority_event_classifies_violation(tmp_path) -> None:
    path = tmp_path / "authority_trace.jsonl"

    write_authority_event(
        path,
        run_id="run_1",
        module="Deformation",
        operation="fetch_fred_data",
        authority="DIRECT_HTTP_ACQUIRE",
        allowed=False,
        reason="forbidden",
    )

    event = json.loads(path.read_text(encoding="utf-8"))
    assert event["event_type"] == "AUTHORITY_VIOLATION"
    assert event["severity"] == "HIGH"

