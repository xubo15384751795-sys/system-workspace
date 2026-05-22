from __future__ import annotations

import sys
from pathlib import Path

import pytest
pytestmark = pytest.mark.critical_gate


ROOT = Path(__file__).resolve().parents[2]
WORKBENCH_SRC = ROOT / "Workbench" / "src"
if str(WORKBENCH_SRC) not in sys.path:
    sys.path.insert(0, str(WORKBENCH_SRC))

from workbench.governance.routing_gate import RoutingGateError, assert_promotion_allowed


def test_routing_decision_blocks_promotion(tmp_path) -> None:
    routing_dir = tmp_path / "routing_decisions"
    routing_dir.mkdir()
    (routing_dir / "2026-05-10.yaml").write_text(
        """
run_id: test
may_promote_current_snapshot: false
reason: "semantic risk"
blocking_findings:
  - DATA_TRUNCATED_PROXY
required_actions:
  - "Attach semantic metadata"
""",
        encoding="utf-8",
    )

    with pytest.raises(RoutingGateError, match="semantic risk"):
        assert_promotion_allowed(routing_dir)


def test_routing_decision_allows_promotion(tmp_path) -> None:
    routing_dir = tmp_path / "routing_decisions"
    routing_dir.mkdir()
    (routing_dir / "2026-05-10.yaml").write_text(
        """
run_id: test
may_promote_current_snapshot: true
reason: "reviewed"
""",
        encoding="utf-8",
    )

    decision = assert_promotion_allowed(routing_dir)
    assert decision["promotion_gate_decision"]["may_promote_current_snapshot"] is True
