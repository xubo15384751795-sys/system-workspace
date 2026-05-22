from __future__ import annotations

import sys
from pathlib import Path

import pytest
pytestmark = pytest.mark.critical_gate


ROOT = Path(__file__).resolve().parents[3]
WORKBENCH_SRC = ROOT / "Workbench" / "src"
if str(WORKBENCH_SRC) not in sys.path:
    sys.path.insert(0, str(WORKBENCH_SRC))

from workbench.governance.routing_gate import RoutingGateError, assert_promotion_allowed


def test_missing_routing_decision_blocks_promotion(tmp_path) -> None:
    routing_dir = tmp_path / "routing_decisions"
    routing_dir.mkdir()

    with pytest.raises(RoutingGateError):
        assert_promotion_allowed(routing_dir)


def test_false_routing_decision_blocks_promotion(tmp_path) -> None:
    routing_dir = tmp_path / "routing_decisions"
    routing_dir.mkdir()
    (routing_dir / "deny.yaml").write_text(
        """
promotion_gate_decision:
  may_promote_current_snapshot: false
  reason: "not reviewed"
  blocking_findings:
    - "semantic risk"
  required_actions:
    - "review semantic metadata"
""",
        encoding="utf-8",
    )

    with pytest.raises(RoutingGateError, match="not reviewed"):
        assert_promotion_allowed(routing_dir)


def test_fake_blocking_routing_decision_without_actions_is_rejected(tmp_path) -> None:
    routing_dir = tmp_path / "routing_decisions"
    routing_dir.mkdir()
    (routing_dir / "fake_deny.yaml").write_text(
        """
promotion_gate_decision:
  may_promote_current_snapshot: false
  reason: "risk exists"
""",
        encoding="utf-8",
    )

    with pytest.raises(RoutingGateError, match="blocking_findings"):
        assert_promotion_allowed(routing_dir)


def test_fake_allow_routing_decision_with_blockers_is_rejected(tmp_path) -> None:
    routing_dir = tmp_path / "routing_decisions"
    routing_dir.mkdir()
    (routing_dir / "fake_allow.yaml").write_text(
        """
decision_id: fake_allow
promotion_gate_decision:
  may_promote_current_snapshot: true
  blocking_findings:
    - "DATA_TRUNCATED_PROXY"
""",
        encoding="utf-8",
    )

    with pytest.raises(RoutingGateError, match="cannot include blocking_findings"):
        assert_promotion_allowed(routing_dir)
