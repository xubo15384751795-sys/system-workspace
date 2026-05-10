from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_SRC = ROOT / "Workbench" / "src"
if str(WORKBENCH_SRC) not in sys.path:
    sys.path.insert(0, str(WORKBENCH_SRC))

from workbench.workspace import promote_snapshot


def test_promotion_blocks_when_latest_routing_decision_denies(tmp_path, monkeypatch) -> None:
    events_dir = tmp_path / "Output" / "system_learning" / "events"
    decisions_dir = tmp_path / "Output" / "system_learning" / "routing_decisions"
    decisions_dir.mkdir(parents=True)
    decision = decisions_dir / "2026-05-10-deny.yaml"
    decision.write_text(
        "\n".join(
            [
                "decision_id: deny_current_snapshot",
                "timestamp: 2026-05-10T00:00:00Z",
                "promotion_gate_decision:",
                "  may_promote_current_snapshot: false",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(promote_snapshot, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(promote_snapshot, "ROUTING_DECISIONS", decisions_dir)
    monkeypatch.setattr(promote_snapshot, "SYSTEM_EVENTS", events_dir)

    with pytest.raises(SystemExit):
        promote_snapshot._enforce_routing_decision("run_a", "snapshot_run_a")

    event = json.loads(next(events_dir.glob("events_*.jsonl")).read_text(encoding="utf-8"))
    assert event["event_type"] == "snapshot_publish_attempt"
    assert event["decision"] == "deny"
    assert event["rule_id"] == "routing_decision.may_promote_current_snapshot"
    assert event["metadata"]["decision_id"] == "deny_current_snapshot"


def test_promotion_allows_when_latest_routing_decision_allows(tmp_path, monkeypatch) -> None:
    decisions_dir = tmp_path / "Output" / "system_learning" / "routing_decisions"
    decisions_dir.mkdir(parents=True)
    (decisions_dir / "2026-05-10-allow.yaml").write_text(
        "\n".join(
            [
                "decision_id: allow_current_snapshot",
                "timestamp: 2026-05-10T00:00:00Z",
                "promotion_gate_decision:",
                "  may_promote_current_snapshot: true",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(promote_snapshot, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(promote_snapshot, "ROUTING_DECISIONS", decisions_dir)
    monkeypatch.setattr(promote_snapshot, "SYSTEM_EVENTS", tmp_path / "events")

    decision = promote_snapshot._enforce_routing_decision("run_a", "snapshot_run_a")

    assert decision["decision_id"] == "allow_current_snapshot"
    assert decision["may_promote_current_snapshot"] is True


def test_force_promotion_is_traced_as_authority_config(tmp_path, monkeypatch) -> None:
    registry = tmp_path / "governance" / "config_authority_registry.yaml"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        """
force_promoted:
  type: AUTHORITY_CONFIG
  default_allowed: false
  severity: CRITICAL
  reason: "Allows promotion despite blockers."
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(promote_snapshot, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(promote_snapshot, "CONFIG_AUTHORITY_REGISTRY", registry)

    events = promote_snapshot._audit_force_promotion("run_a", True)

    trace = tmp_path / "Output" / "governance" / "traces" / "decision_trace.jsonl"
    assert events[0]["event_type"] == "AUTHORITY_CONFIG_ENABLED"
    assert "AUTHORITY_CONFIG_ENABLED" in trace.read_text(encoding="utf-8")
