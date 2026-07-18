"""Shadow-only credit assignment primitives for deterministic decision DAGs.

A caller supplies deterministic replay and outcome-loss functions.  This
module only measures how approved baseline replacements change loss; it has no
filesystem or authority side effects.  Credit is review evidence, not
permission.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from copy import deepcopy
from itertools import combinations
from math import factorial
from typing import Any


ReplayFunction = Callable[[dict[str, Any]], dict[str, Any]]
LossFunction = Callable[[dict[str, Any]], float]


def build_trade_learning_trace(
    *,
    date: str,
    quality_inputs: Mapping[str, Any],
    velocity_gate: Mapping[str, Any] | None,
    sigma_vector: Mapping[str, Any] | None,
    stance: str,
    size: float,
    effective_size: float,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Build the replayable portion of the stance x size decision graph.

    Baselines are intentionally absent. Choosing them is a governance decision
    that must come from an approved credit policy.
    """
    velocity = dict(velocity_gate or {})
    sigma = dict(sigma_vector or {})
    quality = dict(quality_inputs)
    nodes = [
        {
            "node_id": "velocity_state",
            "kind": "proxy",
            "producer_step": "structural_replay",
            "parents": [],
            "active": bool(velocity or sigma),
            "value": {"velocity_gate": velocity, "sigma_vector": sigma},
            "baseline_status": "DECISION_REQUIRED",
        },
        *[
            {
                "node_id": node_id,
                "kind": "gate" if node_id.endswith("_gate") else "quality_input",
                "producer_step": {
                    "k_gate": "k_measurement_gate",
                    "x_gate": "x_measurement_gate",
                    "hmm_quality": "hmm_stability_audit",
                    "caselab_quality": "caselab_signal",
                    "paper_support": "paper_sync",
                    "paper_freshness": "paper_sync",
                    "proxy_quality": "validate_proxy_observation_catalog",
                    "promotion_gate": "judgment_promotion_gate",
                }[node_id],
                "parents": [],
                "active": quality.get(field) not in (None, "UNKNOWN", "unknown"),
                "value": quality.get(field),
                "baseline_status": "DECISION_REQUIRED",
            }
            for node_id, field in (
                ("k_gate", "k_verdict"),
                ("x_gate", "x_verdict"),
                ("hmm_quality", "hmm_grade"),
                ("caselab_quality", "caselab_label"),
                ("paper_support", "has_approved_paper"),
                ("paper_freshness", "paper_stale"),
                ("proxy_quality", "proxy_quality"),
                ("promotion_gate", "promotion_hard_blocked"),
            )
        ],
        {
            "node_id": "stance_operator",
            "kind": "operator",
            "producer_step": "trade_decision",
            "parents": ["velocity_state"],
            "active": True,
            "value": stance,
            "baseline_status": "DERIVED",
        },
        {
            "node_id": "size_operator",
            "kind": "operator",
            "producer_step": "trade_decision",
            "parents": [
                "k_gate", "x_gate", "hmm_quality", "caselab_quality",
                "paper_support", "paper_freshness", "proxy_quality", "promotion_gate",
            ],
            "active": True,
            "value": float(size),
            "baseline_status": "DERIVED",
        },
        {
            "node_id": "effective_sizing",
            "kind": "sizing",
            "producer_step": "trade_decision",
            "parents": ["stance_operator", "size_operator"],
            "active": True,
            "value": float(effective_size),
            "baseline_status": "DERIVED",
        },
    ]
    active = [node["node_id"] for node in nodes if node["active"]]
    return {
        "schema_version": "decision_learning_trace.v1",
        "date": date,
        "run_id": run_id,
        "authority": "shadow_only",
        "credit_can_grant_authority": False,
        "nodes": nodes,
        "activation": {
            "active_node_ids": active,
            "active_count": len(active),
            "total_count": len(nodes),
            "activation_ratio": round(len(active) / len(nodes), 6) if nodes else 0.0,
            "cost_status": "JOINABLE_FROM_RUN_STEPS" if run_id else "RUN_ID_UNAVAILABLE",
        },
        "replay_inputs": {
            "quality_inputs": quality,
            "velocity_gate": velocity,
            "sigma_vector": sigma,
        },
        "actual_output": {
            "stance": stance,
            "size": float(size),
            "effective_size": float(effective_size),
        },
    }


def validate_trace(trace: Mapping[str, Any]) -> list[str]:
    """Return structural errors; an empty list means the trace is replayable."""
    errors: list[str] = []
    nodes = trace.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return ["nodes must be a non-empty list"]
    ids = [str(node.get("node_id", "")) for node in nodes if isinstance(node, Mapping)]
    if any(not node_id for node_id in ids):
        errors.append("every node requires node_id")
    if len(ids) != len(set(ids)):
        errors.append("node_id values must be unique")
    known: set[str] = set()
    for node in nodes:
        if not isinstance(node, Mapping):
            errors.append("every node must be an object")
            continue
        unknown = [parent for parent in node.get("parents", []) if parent not in known]
        if unknown:
            errors.append(f"{node.get('node_id')}: parents must precede node: {unknown}")
        known.add(str(node.get("node_id", "")))
    if trace.get("authority") != "shadow_only":
        errors.append("trace authority must be shadow_only")
    if trace.get("credit_can_grant_authority") is not False:
        errors.append("credit_can_grant_authority must be false")
    return errors


def join_activation_costs(
    trace: Mapping[str, Any],
    steps: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Join active nodes to run-step duration without double-counting steps."""
    duration_by_step = {
        str(step.get("step")): float(step.get("duration_s", 0.0) or 0.0)
        for step in steps
        if step.get("step")
    }
    active_nodes = [
        node for node in trace.get("nodes", [])
        if isinstance(node, Mapping) and node.get("active") is True
    ]
    nodes_by_step: dict[str, list[str]] = {}
    for node in active_nodes:
        producer = str(node.get("producer_step", ""))
        if producer:
            nodes_by_step.setdefault(producer, []).append(str(node.get("node_id", "")))

    producer_costs = []
    node_costs = []
    for producer, node_ids in sorted(nodes_by_step.items()):
        duration = duration_by_step.get(producer)
        producer_costs.append({
            "producer_step": producer,
            "active_node_ids": node_ids,
            "duration_s": duration,
            "status": "measured" if duration is not None else "step_not_recorded",
        })
        share = duration / len(node_ids) if duration is not None and node_ids else None
        node_costs.extend({
            "node_id": node_id,
            "producer_step": producer,
            "attributed_duration_s": round(share, 6) if share is not None else None,
        } for node_id in node_ids)

    measured = [row["duration_s"] for row in producer_costs if row["duration_s"] is not None]
    return {
        "run_id": trace.get("run_id"),
        "unique_active_producer_steps": len(nodes_by_step),
        "measured_producer_steps": len(measured),
        "unmeasured_producer_steps": len(nodes_by_step) - len(measured),
        "unique_producer_cost_s": round(sum(measured), 6),
        "producer_costs": producer_costs,
        "node_costs": node_costs,
        "note": "Producer duration is counted once; shared-step node costs are equal attribution only.",
    }


def ablation_marginals(
    actual_inputs: Mapping[str, Any],
    *,
    baselines: Mapping[str, Any],
    replay: ReplayFunction,
    loss: LossFunction,
) -> dict[str, Any]:
    """Compute one-at-a-time loss deltas for approved input baselines."""
    actual = deepcopy(dict(actual_inputs))
    actual_output = replay(actual)
    actual_loss = float(loss(actual_output))
    rows: list[dict[str, Any]] = []
    for node_id, baseline in baselines.items():
        if node_id not in actual:
            rows.append({"node_id": node_id, "status": "NOT_IN_REPLAY_INPUTS"})
            continue
        replaced = deepcopy(actual)
        replaced[node_id] = deepcopy(baseline)
        counterfactual_output = replay(replaced)
        counterfactual_loss = float(loss(counterfactual_output))
        rows.append({
            "node_id": node_id,
            "status": "evaluated",
            "actual_loss": actual_loss,
            "counterfactual_loss": counterfactual_loss,
            "loss_reduction": counterfactual_loss - actual_loss,
            "counterfactual_output": counterfactual_output,
        })
    return {
        "method": "single_node_ablation",
        "actual_loss": actual_loss,
        "actual_output": actual_output,
        "credits": rows,
        "authority": "shadow_only",
        "credit_can_grant_authority": False,
    }


def exact_shapley_loss_reduction(
    actual_inputs: Mapping[str, Any],
    *,
    baselines: Mapping[str, Any],
    node_ids: Iterable[str],
    replay: ReplayFunction,
    loss: LossFunction,
) -> dict[str, float]:
    """Return exact Shapley loss reduction for a small disputed node set."""
    players = tuple(dict.fromkeys(node_ids))
    if len(players) > 10:
        raise ValueError("exact Shapley is limited to 10 nodes")
    missing = [node for node in players if node not in actual_inputs or node not in baselines]
    if missing:
        raise KeyError(f"missing actual value or baseline for: {missing}")
    n = len(players)
    cache: dict[frozenset[str], float] = {}

    def coalition_loss(actual_nodes: frozenset[str]) -> float:
        if actual_nodes not in cache:
            candidate = deepcopy(dict(actual_inputs))
            for node in players:
                if node not in actual_nodes:
                    candidate[node] = deepcopy(baselines[node])
            cache[actual_nodes] = float(loss(replay(candidate)))
        return cache[actual_nodes]

    credits: dict[str, float] = {node: 0.0 for node in players}
    for node in players:
        others = tuple(player for player in players if player != node)
        for count in range(len(others) + 1):
            weight = factorial(count) * factorial(n - count - 1) / factorial(n)
            for subset_tuple in combinations(others, count):
                subset = frozenset(subset_tuple)
                credits[node] += weight * (
                    coalition_loss(subset) - coalition_loss(subset | {node})
                )
    return credits
