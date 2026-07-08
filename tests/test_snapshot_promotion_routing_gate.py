from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_SRC = ROOT / "packages" / "workbench" / "src"
if str(WORKBENCH_SRC) not in sys.path:
    sys.path.insert(0, str(WORKBENCH_SRC))

from workbench.workspace import promote_snapshot

pytestmark = pytest.mark.critical_gate


def test_promotion_blocks_when_latest_routing_decision_denies(tmp_path, monkeypatch) -> None:
    runtime_dir = tmp_path / "runtime"
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
    monkeypatch.setattr(promote_snapshot, "RUNTIME_LOG_DIR", runtime_dir)
    # Disable subprocess so events fall through to direct file write
    monkeypatch.setattr(promote_snapshot, "RECORD_RUNTIME_SCRIPT", tmp_path / "nonexistent_script.py")

    with pytest.raises(promote_snapshot.PromotionError):
        promote_snapshot._enforce_routing_decision("run_a", "snapshot_run_a")

    event = json.loads(next(runtime_dir.glob("records_*.jsonl")).read_text(encoding="utf-8"))
    assert event["event_type"] == "snapshot_publish_attempt"
    assert event["decision"] == "deny"
    assert event["rule_id"] == "routing_decision.may_promote_current_snapshot"
    assert event["metadata"]["decision_id"] == "deny_current_snapshot"


def test_promotion_allows_when_latest_routing_decision_allows(tmp_path, monkeypatch) -> None:
    decisions_dir = tmp_path / "Output" / "system_learning" / "routing_decisions"
    decisions_dir.mkdir(parents=True)
    # Use a recent timestamp so the decision isn't expired (max 30 days)
    recent = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    recent_date = recent[:10]
    (decisions_dir / f"{recent_date}-allow.yaml").write_text(
        "\n".join(
            [
                "decision_id: allow_current_snapshot",
                f"timestamp: {recent}",
                "promotion_gate_decision:",
                "  may_promote_current_snapshot: true",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(promote_snapshot, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(promote_snapshot, "ROUTING_DECISIONS", decisions_dir)
    monkeypatch.setattr(promote_snapshot, "RUNTIME_LOG_DIR", tmp_path / "runtime")
    monkeypatch.setattr(promote_snapshot, "RECORD_RUNTIME_SCRIPT", tmp_path / "nonexistent_script.py")

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


def test_force_promotion_status_is_non_claim_quarantine() -> None:
    assert promote_snapshot._promotion_status(True, []) == "quarantine"
    assert promote_snapshot._promotion_status(True, ["operator_trace missing"]) == "legacy_canonicalization"
    assert promote_snapshot._claim_carrying_allowed("quarantine") is False
    assert promote_snapshot._claim_carrying_allowed("legacy_canonicalization") is False
    assert promote_snapshot._claim_carrying_allowed("canonical") is True


def test_diagnostic_blockers_reject_empty_validation_outputs(tmp_path) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "diagnostics").mkdir(parents=True)
    (run_dir / "tables").mkdir()
    (run_dir / "diagnostics" / "rejection_flags.json").write_text("{}\n", encoding="utf-8")
    (run_dir / "diagnostics" / "residual_tests.json").write_text("{}\n", encoding="utf-8")
    (run_dir / "diagnostics" / "operator_diagnostics.json").write_text("{}\n", encoding="utf-8")
    (run_dir / "tables" / "benchmark_comparison.csv").write_text(
        "benchmark_value,name,residual_value\n,not_available,\n",
        encoding="utf-8",
    )

    blockers = promote_snapshot._diagnostic_blockers(run_dir)

    assert "diagnostics/rejection_flags.json is empty" in blockers
    assert "diagnostics/residual_tests.json is empty" in blockers
    assert "diagnostics/operator_diagnostics.json is empty" in blockers
    assert "tables/benchmark_comparison.csv contains not_available" in blockers
