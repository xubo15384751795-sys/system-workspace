"""Failure behavior contract — verify governance rules are enforceable.

These tests verify that the pipeline registry's failure_behavior declarations
form a consistent defensive chain.  They do NOT run the pipeline; they check
that the declared invariants hold structurally.

Core scenarios tested:
  1. Harvester release missing → structural_replay / freshness must block or degrade
  2. framework_output missing → judgment / trade_decision cannot produce strong claims
  3. promotion_gate blocked → trade_decision must be hold_flat or research_only

See: governance/daily_pipeline_registry.yaml
     governance/architecture_cleanup_decisions.md D2
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "governance" / "daily_pipeline_registry.yaml"

BLOCKING_BEHAVIORS = {
    "block_core_judgment",
    "block_current_readout",
    "block_promotion",
    "hold_flat",
    "lower_claim_ceiling",
}
DEGRADING_BEHAVIORS = BLOCKING_BEHAVIORS | {"research_only"}
NON_BLOCKING = {"continue_with_warning", "research_only"}


def _load_registry() -> dict:
    return yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))


def _steps(reg: dict) -> dict[str, dict]:
    return {k: v for k, v in reg.get("steps", {}).items() if isinstance(v, dict)}


def _steps_consuming(reg: dict, path_prefix: str) -> list[tuple[str, dict]]:
    """Steps that consume a path starting with *path_prefix*."""
    results = []
    for name, step in _steps(reg).items():
        consumed = set()
        for source in ("input", "consumes"):
            for p in step.get(source, []):
                consumed.add(str(p))
        for p in step.get("contracts", {}).get("inputs", []):
            consumed.add(str(p))
        if any(c.startswith(path_prefix) or path_prefix.startswith(c) for c in consumed):
            results.append((name, step))
    return results


# ---------------------------------------------------------------------------
# Scenario 1: Harvester release missing
# ---------------------------------------------------------------------------

class TestHarvesterReleaseMissing:
    """If the Harvester release is absent, core judgment must degrade."""

    def test_structural_replay_blocks_on_harvester(self) -> None:
        reg = _load_registry()
        step = _steps(reg).get("structural_replay")
        assert step is not None, "structural_replay not in registry"
        fb = step.get("failure_behavior", "")
        assert fb in BLOCKING_BEHAVIORS, (
            f"structural_replay failure_behavior={fb!r} — must block when Harvester missing"
        )

    def test_freshness_validator_blocks_on_harvester(self) -> None:
        reg = _load_registry()
        step = _steps(reg).get("freshness_validator")
        assert step is not None, "freshness_validator not in registry"
        fb = step.get("failure_behavior", "")
        assert fb in BLOCKING_BEHAVIORS, (
            f"freshness_validator failure_behavior={fb!r} — must block when Harvester missing"
        )

    def test_harvester_required_evidence_steps_have_blocking_behavior(self) -> None:
        """Every step with requires_harvester_evidence=true must have a blocking failure_behavior."""
        reg = _load_registry()
        violations = []
        for name, step in _steps(reg).items():
            if step.get("requires_harvester_evidence"):
                fb = step.get("failure_behavior", "")
                if fb not in DEGRADING_BEHAVIORS:
                    violations.append(
                        f"{name}: requires_harvester_evidence=true but "
                        f"failure_behavior={fb!r} (expected blocking/degrading)"
                    )
        assert not violations, (
            "Harvester-dependent steps without blocking behavior:\n"
            + "\n".join(violations)
        )

    def test_harvester_failure_propagates_to_judgment_chain(self) -> None:
        """If harvester fails with block_core_judgment, judgment_layer must also block."""
        reg = _load_registry()
        harvester = _steps(reg).get("harvester", {})
        assert harvester.get("failure_behavior") == "block_core_judgment"

        judgment = _steps(reg).get("judgment_layer", {})
        jfb = judgment.get("failure_behavior", "")
        assert jfb in BLOCKING_BEHAVIORS, (
            f"judgment_layer failure_behavior={jfb!r} — must block when harvester fails"
        )


# ---------------------------------------------------------------------------
# Scenario 2: framework_output missing
# ---------------------------------------------------------------------------

class TestFrameworkOutputMissing:
    """If framework_output.json is absent, no strong judgment allowed."""

    def test_judgment_layer_consumes_framework_output(self) -> None:
        reg = _load_registry()
        consumers = _steps_consuming(reg, "Output/current/framework_output.json")
        names = [n for n, _ in consumers]
        assert "judgment_layer" in names, (
            f"judgment_layer does not consume framework_output — found: {names}"
        )

    def test_judgment_blocks_without_framework_output(self) -> None:
        reg = _load_registry()
        step = _steps(reg).get("judgment_layer")
        assert step is not None
        fb = step.get("failure_behavior", "")
        assert fb in BLOCKING_BEHAVIORS, (
            f"judgment_layer failure_behavior={fb!r} — must block when framework_output missing"
        )

    def test_quality_validation_blocks_without_framework_output(self) -> None:
        reg = _load_registry()
        step = _steps(reg).get("quality_validation")
        assert step is not None
        fb = step.get("failure_behavior", "")
        assert fb in BLOCKING_BEHAVIORS, (
            f"quality_validation failure_behavior={fb!r} — must block when framework_output missing"
        )

    def test_trade_decision_cannot_override_judgment_block(self) -> None:
        """trade_decision depends on judgment — if judgment blocks, trade must also degrade."""
        reg = _load_registry()
        trade = _steps(reg).get("trade_decision", {})
        fb = trade.get("failure_behavior", "")
        assert fb in DEGRADING_BEHAVIORS, (
            f"trade_decision failure_behavior={fb!r} — must degrade/block when judgment fails"
        )


# ---------------------------------------------------------------------------
# Scenario 3: promotion_gate blocked
# ---------------------------------------------------------------------------

class TestPromotionGateBlocked:
    """If promotion gate blocks, trade decision must not execute normally."""

    def test_promotion_gate_blocks_trade(self) -> None:
        reg = _load_registry()
        gate = _steps(reg).get("judgment_promotion_gate", {})
        assert gate.get("failure_behavior") == "block_promotion"

        trade = _steps(reg).get("trade_decision", {})
        fb = trade.get("failure_behavior", "")
        assert fb in {"hold_flat", "research_only"}, (
            f"trade_decision failure_behavior={fb!r} — must be hold_flat or research_only "
            f"when promotion gate blocks"
        )

    def test_trade_decision_consumes_promotion_gate(self) -> None:
        reg = _load_registry()
        consumers = _steps_consuming(reg, "Output/judgment/promotion_gate.json")
        names = [n for n, _ in consumers]
        assert "trade_decision" in names, (
            f"trade_decision does not consume promotion_gate — found: {names}"
        )

    def test_risk_gate_blocks_on_trade_decision(self) -> None:
        """risk_gate depends on trade_decision — must block or hold."""
        reg = _load_registry()
        risk = _steps(reg).get("risk_gate", {})
        fb = risk.get("failure_behavior", "")
        assert fb in BLOCKING_BEHAVIORS, (
            f"risk_gate failure_behavior={fb!r} — must block when trade_decision fails"
        )


# ---------------------------------------------------------------------------
# Structural invariants
# ---------------------------------------------------------------------------

class TestFailureBehaviorStructuralInvariants:
    """Cross-cutting invariants on failure_behavior declarations."""

    def test_no_core_judgment_step_uses_continue_with_warning(self) -> None:
        """Steps affecting core judgment must never use continue_with_warning."""
        reg = _load_registry()
        violations = []
        for name, step in _steps(reg).items():
            if step.get("authority", {}).get("affects_core_judgment"):
                fb = step.get("failure_behavior", "")
                if fb == "continue_with_warning":
                    violations.append(name)
        assert not violations, (
            f"Core judgment steps using continue_with_warning: {violations}"
        )

    def test_shadow_steps_must_continue_with_warning(self) -> None:
        """Shadow/experimental steps should not block the pipeline."""
        reg = _load_registry()
        violations = []
        for name, step in _steps(reg).items():
            if step.get("status") == "shadow_active":
                fb = step.get("failure_behavior", "")
                if fb not in NON_BLOCKING:
                    violations.append(f"{name}: shadow but failure_behavior={fb!r}")
        assert not violations, (
            "Shadow steps with blocking behavior:\n" + "\n".join(violations)
        )

    def test_hold_flat_only_on_trade_chain(self) -> None:
        """hold_flat should only appear on trade/risk/position steps."""
        reg = _load_registry()
        trade_chain = {"trade_decision", "risk_gate", "position_sizing"}
        violations = []
        for name, step in _steps(reg).items():
            if step.get("failure_behavior") == "hold_flat" and name not in trade_chain:
                violations.append(name)
        assert not violations, (
            f"hold_flat used outside trade chain: {violations}"
        )
