"""Unified world-model query API for external projects."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from caselab_context.load_context import load_resolver_rules
from caselab_context.regime_from_indicators import infer_regime_from_indicators
from caselab_context.resolve_meaning import build_context_packet, match_rules
from caselab_context.state_machine_runtime import evaluate_world_state

# Map executable state-machine states onto resolver regime axes.
STATE_MACHINE_REGIME_MAP: dict[str, tuple[str, dict[str, str]]] = {
    "credit_cycle": (
        "credit",
        {
            "expansion": "expanding",
            "late_cycle": "fragile",
            "crisis": "contracting",
            "recovery": "expanding",
        },
    ),
    "ai_capex_cycle": (
        "technology_cycle",
        {
            "growth": "scaling",
            "bottleneck": "early",
            "saturation": "saturation",
        },
    ),
}

STATE_MACHINE_CTX_KEYS: dict[str, str] = {
    "credit_cycle": "credit_cycle_state",
    "ai_capex_cycle": "ai_capex_cycle_state",
}


@dataclass
class WorldModelResponse:
    context_packet: dict[str, Any]
    regime_source: str
    warnings: list[str] = field(default_factory=list)
    world_state: dict[str, Any] | None = None
    schema_version: str = "1.2"

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "context_packet": self.context_packet,
            "regime_source": self.regime_source,
            "warnings": self.warnings,
        }
        if self.world_state is not None:
            payload["world_state"] = self.world_state
        return payload


def _apply_machine_state_to_regime(
    regime: dict[str, str],
    world_state: dict[str, Any] | None,
    *,
    state_key: str = "current_state",
) -> None:
    if not world_state:
        return
    for machine in world_state.get("machines") or []:
        machine_id = str(machine.get("id") or "")
        mapping = STATE_MACHINE_REGIME_MAP.get(machine_id)
        if not mapping:
            continue
        axis, state_map = mapping
        state = machine.get(state_key)
        if state and state in state_map:
            regime[axis] = state_map[state]


def _align_regime_with_world_state(regime: dict[str, str], world_state: dict[str, Any] | None) -> None:
    _apply_machine_state_to_regime(regime, world_state, state_key="current_state")


def _prior_regime_from_world_state(
    regime: dict[str, str],
    world_state: dict[str, Any] | None,
) -> dict[str, str]:
    prior = dict(regime)
    _apply_machine_state_to_regime(prior, world_state, state_key="previous_state")
    return prior


def _collect_state_transitions(world_state: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not world_state:
        return []
    transitions: list[dict[str, Any]] = []
    for machine in world_state.get("machines") or []:
        transition = machine.get("transition")
        if not transition:
            continue
        transitions.append(
            {
                "machine_id": machine.get("id"),
                "canonical_name": machine.get("canonical_name"),
                "from": transition.get("from"),
                "to": transition.get("to"),
                "lookback_days": transition.get("lookback_days"),
                "variables": machine.get("variables"),
            }
        )
    return transitions


def _attach_machine_states_to_packet(ctx: dict[str, Any], world_state: dict[str, Any] | None) -> None:
    if not world_state:
        return
    ctx["world_state"] = world_state
    for machine in world_state.get("machines") or []:
        machine_id = str(machine.get("id") or "")
        ctx_key = STATE_MACHINE_CTX_KEYS.get(machine_id)
        if ctx_key:
            ctx[ctx_key] = machine.get("current_state")


def _transition_resolver_rematch(
    ctx: dict[str, Any],
    *,
    actor: str,
    verb: str,
    action_object: str,
    regime: dict[str, str],
    world_state: dict[str, Any] | None,
) -> list[str]:
    """Compare resolver matches before vs after a state transition."""
    warnings: list[str] = []
    transitions = _collect_state_transitions(world_state)
    if not transitions:
        return warnings

    ctx["state_transitions"] = transitions
    prior_regime = _prior_regime_from_world_state(regime, world_state)
    ctx["prior_regime"] = prior_regime

    rules = load_resolver_rules()
    prior_matched = match_rules(actor, verb, action_object, prior_regime, rules)
    prior_ids = [str(rule.get("id")) for rule in prior_matched]
    current_ids = [str(rule_id) for rule_id in (ctx.get("matched_rules") or [])]

    ctx["matched_rules_prior"] = prior_ids
    if set(prior_ids) != set(current_ids):
        ctx["resolver_rematched_on_transition"] = True
        warnings.append("resolver_rules_changed_after_state_transition")
    else:
        ctx["resolver_rematched_on_transition"] = False

    return warnings


def _collect_warnings(packet: dict[str, Any], *, min_quality: str | None) -> list[str]:
    warnings: list[str] = []
    ctx = packet.get("context_packet") or packet
    if not ctx.get("matched_rules"):
        warnings.append("no_resolver_rule_matched")
    source = ctx.get("regime_source")
    if source == "default":
        warnings.append("regime_fallback_to_default")
    similar = ctx.get("similar_notes") or []
    if not similar:
        warnings.append("no_similar_notes_found")
    if min_quality:
        seed_hits = [item for item in similar if (item.get("quality") or "seed") == "seed"]
        if seed_hits:
            warnings.append("seed_notes_in_similar_results")
    meaning = ctx.get("contextual_meaning") or {}
    if not meaning.get("non_transferable_conditions"):
        warnings.append("missing_non_transferable_conditions")
    return warnings


def current_regime(*, evaluate_state: bool = True) -> dict[str, Any]:
    """Return regime axes aligned with executable state machines."""
    regime_meta = infer_regime_from_indicators()
    regime = dict(regime_meta["regime"])
    world_state = None
    if evaluate_state:
        world_state = evaluate_world_state(snapshot=regime_meta.get("indicator_snapshot"))
        _align_regime_with_world_state(regime, world_state)
    return {
        **regime_meta,
        "regime": regime,
        "world_state": world_state,
    }


def query(
    actor: str,
    verb: str,
    action_object: str,
    *,
    use_indicator_regime: bool = True,
    min_quality: str = "useful",
    regime_override: dict[str, str] | None = None,
    evaluate_state: bool = True,
    state_machine_ids: list[str] | None = None,
    rematch_on_transition: bool = True,
) -> WorldModelResponse:
    """Resolve a world-model context packet for an actor action."""
    regime_meta: dict[str, Any] | None = None
    regime: dict[str, str] | None = regime_override
    snapshot: dict[str, Any] | None = None
    regime_source = "override" if regime_override else "paper_or_default"

    if regime is None and use_indicator_regime:
        regime_meta = infer_regime_from_indicators()
        regime = dict(regime_meta["regime"])
        snapshot = regime_meta.get("indicator_snapshot")
        regime_source = str(regime_meta.get("source") or "indicators")

    world_state = None
    if evaluate_state:
        world_state = evaluate_world_state(machine_ids=state_machine_ids, snapshot=snapshot)
        if regime is not None:
            _align_regime_with_world_state(regime, world_state)

    packet = build_context_packet(
        actor,
        verb,
        action_object,
        regime=regime,
        use_indicator_regime=False,
        min_quality=min_quality,
    )
    ctx = packet["context_packet"]

    if regime_meta:
        ctx["regime_source"] = regime_meta.get("source")
        ctx["regime_evidence"] = regime_meta.get("evidence")
        ctx["regime_as_of"] = regime_meta.get("as_of")
        ctx["indicator_snapshot"] = regime_meta.get("indicator_snapshot")
    elif regime_override:
        ctx["regime_source"] = "override"

    _attach_machine_states_to_packet(ctx, world_state)

    warnings = _collect_warnings(packet, min_quality=min_quality)
    if evaluate_state and world_state and not world_state.get("machines"):
        warnings.append("no_state_machines_evaluated")

    if rematch_on_transition and regime is not None:
        warnings.extend(
            _transition_resolver_rematch(
                ctx,
                actor=actor,
                verb=verb,
                action_object=action_object,
                regime=regime,
                world_state=world_state,
            )
        )

    return WorldModelResponse(
        context_packet=ctx,
        regime_source=regime_source,
        warnings=warnings,
        world_state=world_state,
    )


# Backward-compatible alias used in Round 11 tests/docs.
_align_regime_credit_with_world_state = _align_regime_with_world_state
