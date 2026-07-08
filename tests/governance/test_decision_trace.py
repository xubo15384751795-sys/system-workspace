from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.governance_loop


ROOT = Path(__file__).resolve().parents[2]
WORKBENCH_SRC = ROOT / "packages" / "workbench" / "src"
if str(WORKBENCH_SRC) not in sys.path:
    sys.path.insert(0, str(WORKBENCH_SRC))

from workbench.governance.decision_trace import record_decision


def test_decision_trace_records_impact_and_consumer(tmp_path) -> None:
    path = tmp_path / "decision_trace.jsonl"

    record_decision(
        path,
        run_id="run_1",
        artifact="measurement_audit.json",
        artifact_type="AUDIT",
        finding="FAMILY_MONOCULTURE",
        decision_impact="ACTION_REQUIRED",
        consumer="proxy_review_gate",
        severity="MEDIUM",
        reason="single-family dependency",
    )

    event = json.loads(path.read_text(encoding="utf-8"))
    assert event["decision_impact"] == "ACTION_REQUIRED"
    assert event["consumer"] == "proxy_review_gate"
    assert event["ts"] > 0


def test_decision_trace_rejects_action_without_consumer(tmp_path) -> None:
    with pytest.raises(ValueError, match="consumer"):
        record_decision(
            tmp_path / "decision_trace.jsonl",
            run_id="run_1",
            artifact="fake_report.md",
            artifact_type="REPORT",
            finding="WARNING_ONLY_WORDS",
            decision_impact="BLOCK",
            consumer=None,
            severity="HIGH",
            reason="block without consumer is fake governance",
        )
