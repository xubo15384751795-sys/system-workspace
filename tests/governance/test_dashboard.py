from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKBENCH_SRC = ROOT / "Workbench" / "src"
if str(WORKBENCH_SRC) not in sys.path:
    sys.path.insert(0, str(WORKBENCH_SRC))

from workbench.governance.dashboard import render_governance_dashboard


def test_dashboard_renders_inventory_counts() -> None:
    dashboard = render_governance_dashboard(
        [
            {
                "artifact_id": "routing_decisions",
                "artifact_type": "LEDGER",
                "consumer": "promotion_gate",
                "decision_impact": "BLOCK",
            },
            {
                "artifact_id": "recurrence_report.md",
                "artifact_type": "REPORT",
                "consumer": "human_display",
                "decision_impact": "DISPLAY_ONLY",
            },
            {
                "artifact_id": "provenance_gap_ledger",
                "artifact_type": "LEDGER",
                "consumer": None,
                "decision_impact": "NONE",
            },
        ]
    )

    assert "| ALIVE | 1 |" in dashboard
    assert "| PASSIVE | 1 |" in dashboard
    assert "| ZOMBIE | 1 |" in dashboard
    assert "routing_decisions" in dashboard
