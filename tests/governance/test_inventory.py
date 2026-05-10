from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKBENCH_SRC = ROOT / "Workbench" / "src"
if str(WORKBENCH_SRC) not in sys.path:
    sys.path.insert(0, str(WORKBENCH_SRC))

from workbench.governance.inventory import classify_artifact, write_inventory


def test_classify_artifact_statuses() -> None:
    assert classify_artifact({"consumer": None, "decision_impact": "NONE"}) == "ZOMBIE"
    assert classify_artifact({"consumer": "human_report", "decision_impact": "DISPLAY_ONLY"}) == "PASSIVE"
    assert classify_artifact({"consumer": "promotion_gate", "decision_impact": "BLOCK"}) == "ALIVE"
    assert classify_artifact({"consumer": "proxy_review_gate", "decision_impact": "ACTION_REQUIRED"}) == "ALIVE_WEAK"


def test_write_inventory_normalizes_risk(tmp_path) -> None:
    path = tmp_path / "inventory.json"

    inventory = write_inventory(
        path,
        [
            {
                "artifact_id": "routing_decisions",
                "artifact_type": "LEDGER",
                "consumer": "promotion_gate",
                "decision_impact": "BLOCK",
            },
            {
                "artifact_id": "provenance_gap_ledger",
                "artifact_type": "LEDGER",
                "consumer": None,
                "decision_impact": "NONE",
            },
        ],
    )

    rows = json.loads(path.read_text(encoding="utf-8"))
    assert inventory[0].status == "ALIVE"
    assert rows[1]["status"] == "ZOMBIE"
    assert rows[1]["risk_level"] == "HIGH"

