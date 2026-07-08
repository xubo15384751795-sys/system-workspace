"""Causal graph traversal — quantitative structural reasoning.

READS: entity_environments.json (weighted interaction graph)
WRITES: Output/caselab/causal/ only

Converts qualitative interaction edges to quantitative causal chains.
Traces how an event propagates through an entity's variable graph
with decay, amplification, and state-dependent inertia.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

OUTPUT_DIR = Path(__file__).resolve().parents[5] / "Output" / "caselab" / "causal"


# ── Relation type → base weight and direction ────────────────────────────
# Each relation type has a base transmission weight (0-1) and whether
# it amplifies or decays the signal.

RELATION_WEIGHTS: dict[str, dict[str, float]] = {
    # Amplifying relations (signal gets stronger)
    "amplifies":              {"weight": 0.80, "decay": 1.0},
    "feedback_via_collateral": {"weight": 0.75, "decay": 1.0},
    "drives":                 {"weight": 0.70, "decay": 0.9},
    "reinforces_dominance":   {"weight": 0.70, "decay": 1.0},
    "expands":                {"weight": 0.65, "decay": 0.9},
    "prices_risk_onto":       {"weight": 0.65, "decay": 0.85},

    # Transfer relations (signal passes with some loss)
    "transfers_risk_to":      {"weight": 0.60, "decay": 0.8},
    "drives_innovation":      {"weight": 0.55, "decay": 0.85},
    "drives_growth":          {"weight": 0.55, "decay": 0.85},
    "funds_next_cycle":       {"weight": 0.55, "decay": 0.9},
    "attracts":               {"weight": 0.50, "decay": 0.85},
    "attracts_engineers":     {"weight": 0.50, "decay": 0.85},
    "attracts_ecosystem":     {"weight": 0.50, "decay": 0.85},
    "attracts_via_equity":    {"weight": 0.50, "decay": 0.85},
    "enables":                {"weight": 0.50, "decay": 0.85},
    "enables_equity_comp":    {"weight": 0.50, "decay": 0.85},
    "generates":              {"weight": 0.50, "decay": 0.85},
    "retains":                {"weight": 0.45, "decay": 0.85},
    "prices_in":              {"weight": 0.45, "decay": 0.8},
    "deepens":                {"weight": 0.45, "decay": 0.9},
    "supports":               {"weight": 0.45, "decay": 0.9},
    "scales":                 {"weight": 0.40, "decay": 0.85},
    "captures_margin":        {"weight": 0.40, "decay": 0.85},
    "protects":               {"weight": 0.40, "decay": 0.9},
    "stabilizes":             {"weight": 0.35, "decay": 0.9},

    # Stress/damage relations (signal amplifies negative)
    "dries_up":               {"weight": 0.85, "decay": 0.7},
    "depresses":              {"weight": 0.75, "decay": 0.8},
    "forces_deleveraging":    {"weight": 0.80, "decay": 0.75},
    "widens":                 {"weight": 0.70, "decay": 0.8},
    "widens_on_stress":       {"weight": 0.65, "decay": 0.8},
    "liquidation_depresses":  {"weight": 0.80, "decay": 0.75},
    "constrains":             {"weight": 0.60, "decay": 0.85},
    "threatens":              {"weight": 0.55, "decay": 0.85},
    "creates_refinancing_risk": {"weight": 0.60, "decay": 0.8},
    "hides_until_crisis":     {"weight": 0.50, "decay": 0.95},
    "layers_complexity":      {"weight": 0.45, "decay": 0.9},
    "amplifies_hidden":       {"weight": 0.65, "decay": 0.9},
    "lock_in_developers":     {"weight": 0.55, "decay": 0.9},
    "reduces_custom_work":    {"weight": 0.35, "decay": 0.9},
    "builds_moat":            {"weight": 0.50, "decay": 0.95},
}

# ── Variable → M/D/K/X sensitivity ──────────────────────────────────────
# How much does a change in each variable affect M/D/K/X.

VARIABLE_MDX_SENSITIVITY: dict[str, dict[str, float]] = {
    # Financial variables
    "balance_sheet":          {"M": 0.1, "K": 0.4, "D": 0.3, "X": 0.2},
    "leverage":               {"M": 0.1, "K": 0.5, "D": 0.4, "X": 0.2},
    "credit_spread":          {"M": 0.2, "K": 0.5, "D": 0.4, "X": 0.3},
    "cash_flow":              {"M": 0.1, "K": 0.3, "D": 0.2, "X": 0.1},
    "counterparty_exposure":  {"M": 0.1, "K": 0.4, "D": 0.3, "X": 0.3},

    # Market variables
    "stock_price":            {"M": 0.1, "K": 0.2, "D": 0.1, "X": 0.1},
    "valuation":              {"M": 0.1, "K": 0.2, "D": 0.1, "X": 0.1},
    "trading_volume":         {"M": 0.05, "K": 0.15, "D": 0.1, "X": 0.1},
    "analyst_sentiment":      {"M": 0.05, "K": 0.1, "D": 0.05, "X": 0.05},

    # Operational variables
    "talent_density":         {"M": 0.0, "K": 0.1, "D": 0.05, "X": 0.0},
    "headcount":              {"M": 0.0, "K": 0.05, "D": 0.05, "X": 0.0},
    "market_share":           {"M": 0.05, "K": 0.15, "D": 0.05, "X": 0.1},
    "revenue":                {"M": 0.05, "K": 0.1, "D": 0.05, "X": 0.05},
    "capex":                  {"M": 0.05, "K": 0.15, "D": 0.05, "X": 0.1},
    "product_pipeline":       {"M": 0.0, "K": 0.1, "D": 0.0, "X": 0.05},
    "switching_cost":         {"M": 0.0, "K": 0.1, "D": 0.0, "X": 0.05},
    "concentration_risk":     {"M": 0.1, "K": 0.3, "D": 0.2, "X": 0.2},
    "regulatory_risk":        {"M": 0.15, "K": 0.2, "D": 0.1, "X": 0.15},

    # Macro variables
    "capital_flow":           {"M": 0.3, "K": 0.2, "D": 0.1, "X": 0.3},
    "currency_stability":     {"M": 0.3, "K": 0.2, "D": 0.15, "X": 0.3},
    "bond_market_depth":      {"M": 0.2, "K": 0.2, "D": 0.1, "X": 0.2},
    "banking_system_health":  {"M": 0.2, "K": 0.3, "D": 0.2, "X": 0.2},
    "gdp_growth":             {"M": 0.3, "K": 0.1, "D": 0.1, "X": 0.1},
    "inflation":              {"M": 0.3, "K": 0.15, "D": 0.1, "X": 0.1},
    "tax_policy":             {"M": 0.15, "K": 0.05, "D": 0.0, "X": 0.05},
    "trade_policy":           {"M": 0.2, "K": 0.1, "D": 0.05, "X": 0.15},
    "tech_capacity":          {"M": 0.05, "K": 0.15, "D": 0.0, "X": 0.1},
    "talent_pipeline":        {"M": 0.0, "K": 0.1, "D": 0.0, "X": 0.05},
    "infrastructure":         {"M": 0.05, "K": 0.1, "D": 0.0, "X": 0.05},
    "energy_security":        {"M": 0.15, "K": 0.15, "D": 0.1, "X": 0.15},
    "regulatory_quality":     {"M": 0.1, "K": 0.1, "D": 0.05, "X": 0.05},
    "rule_of_law":            {"M": 0.1, "K": 0.1, "D": 0.05, "X": 0.05},
    "research_output":        {"M": 0.0, "K": 0.05, "D": 0.0, "X": 0.0},
    "startup_output":         {"M": 0.0, "K": 0.05, "D": 0.0, "X": 0.0},
    "vc_connection":          {"M": 0.0, "K": 0.05, "D": 0.0, "X": 0.0},
    "industry_partnership":   {"M": 0.0, "K": 0.05, "D": 0.0, "X": 0.0},
    "funding_level":          {"M": 0.0, "K": 0.05, "D": 0.0, "X": 0.0},
    "endowment_size":         {"M": 0.0, "K": 0.0, "D": 0.0, "X": 0.0},
    "global_ranking":         {"M": 0.0, "K": 0.0, "D": 0.0, "X": 0.0},
    "cost_structure":         {"M": 0.0, "K": 0.1, "D": 0.05, "X": 0.0},

    # Infrastructure variables
    "clearing_volume":        {"M": 0.05, "K": 0.2, "D": 0.1, "X": 0.1},
    "settlement_efficiency":  {"M": 0.0, "K": 0.1, "D": 0.05, "X": 0.05},
    "counterparty_netting":   {"M": 0.0, "K": 0.15, "D": 0.1, "X": 0.1},
    "operational_risk":       {"M": 0.05, "K": 0.15, "D": 0.1, "X": 0.1},
    "interconnectedness":     {"M": 0.1, "K": 0.25, "D": 0.15, "X": 0.2},
}


# ── State-dependent inertia modifier ────────────────────────────────────
# How does System's current state (K level) modify entity behavior?

def inertia_modifier(k_level: float, entity_type: str, dna_keywords: list[str]) -> dict[str, float]:
    """Compute how System state modifies entity inertia.

    When K is low (calm): entities tend to expand, take risk, grow.
    When K is high (stress): entities tend to contract, shed risk, defend.

    Returns modifier multipliers for transmission weight.
    """
    # K level to stress regime
    if k_level < 0.3:
        regime = "calm"
    elif k_level < 0.5:
        regime = "normal"
    elif k_level < 0.7:
        regime = "elevated"
    else:
        regime = "crisis"

    # Base modifiers by regime
    regime_mods = {
        "calm":     {"amplify": 0.8, "transmit": 0.7, "dampen": 1.2},
        "normal":   {"amplify": 1.0, "transmit": 1.0, "dampen": 1.0},
        "elevated": {"amplify": 1.2, "transmit": 1.1, "dampen": 0.9},
        "crisis":   {"amplify": 1.5, "transmit": 1.3, "dampen": 0.7},
    }
    mods = regime_mods[regime]

    # Entity type adjustments
    if entity_type == "company":
        sector_mod = 1.0
        if any(kw in dna_keywords for kw in ["杠杆", "资产负债表", "风险定价"]):
            # Financial entities amplify stress more in crisis
            if regime in ("elevated", "crisis"):
                mods = {k: v * 1.2 for k, v in mods.items()}
        if any(kw in dna_keywords for kw in ["平台", "生态", "锁定"]):
            # Platform entities are more resilient in crisis
            if regime in ("elevated", "crisis"):
                mods["dampen"] *= 1.3
    elif entity_type == "regulator":
        # Regulators are counter-cyclical: dampen more in crisis
        if regime in ("elevated", "crisis"):
            mods["dampen"] *= 1.5
            mods["amplify"] *= 0.7
    elif entity_type == "geo":
        # Geo entities: stress propagates more in crisis
        if regime in ("elevated", "crisis"):
            mods["transmit"] *= 1.2

    return mods


@dataclass
class PropagationResult:
    """Result of causal graph traversal."""
    source_variable: str
    source_impact: float
    paths: list[dict[str, Any]] = field(default_factory=list)
    terminal_variables: dict[str, float] = field(default_factory=dict)
    mdx_delta: dict[str, float] = field(default_factory=dict)
    regime: str = "normal"
    total_paths: int = 0
    max_depth: int = 0


def propagate_impact(
    entity_env: dict[str, Any],
    initial_variable: str,
    initial_impact: float,
    k_level: float = 0.5,
    max_depth: int = 5,
    min_weight: float = 0.05,
) -> PropagationResult:
    """Propagate impact through entity's weighted interaction graph.

    Parameters
    ----------
    entity_env : dict
        Entity environment from entity_environments.json.
    initial_variable : str
        Which variable is initially hit (e.g., "leverage").
    initial_impact : float
        How strong the initial impact is (0-1).
    k_level : float
        Current System K level (modifies inertia).
    max_depth : int
        Maximum traversal depth.
    min_weight : float
        Minimum weight to continue propagation.

    Returns
    -------
    PropagationResult with paths, terminal variables, and M/D/K/X delta.
    """
    graph = entity_env.get("interaction_graph", [])
    entity_type = entity_env.get("entity_type", "unknown")
    dna_keywords = entity_env.get("dna_keywords", [])

    # Get inertia modifiers
    mods = inertia_modifier(k_level, entity_type, dna_keywords)

    # Build adjacency list with weights
    adjacency: dict[str, list[dict]] = {}
    for edge in graph:
        src = edge["from"]
        dst = edge["to"]
        rel = edge["relation"]
        mech = edge.get("via_mechanism", "")

        rel_info = RELATION_WEIGHTS.get(rel, {"weight": 0.4, "decay": 0.85})
        base_weight = rel_info["weight"]
        decay = rel_info["decay"]

        # Apply inertia modifier
        if base_weight >= 0.6:
            weight = base_weight * mods["amplify"]
        elif base_weight >= 0.4:
            weight = base_weight * mods["transmit"]
        else:
            weight = base_weight * mods["dampen"]

        weight = min(1.0, max(0.0, weight))

        if src not in adjacency:
            adjacency[src] = []
        adjacency[src].append({
            "to": dst,
            "weight": weight,
            "decay": decay,
            "relation": rel,
            "mechanism": mech,
        })

    # BFS traversal with decay
    visited_vars: dict[str, float] = {initial_variable: initial_impact}
    all_paths: list[dict[str, Any]] = []
    queue: list[tuple[str, float, int, list[str]]] = [
        (initial_variable, initial_impact, 0, [initial_variable])
    ]

    while queue:
        current_var, current_impact, depth, path = queue.pop(0)

        if depth >= max_depth:
            continue
        if current_impact < min_weight:
            continue

        neighbors = adjacency.get(current_var, [])
        for edge in neighbors:
            dst = edge["to"]
            transmitted = current_impact * edge["weight"] * edge["decay"]

            if transmitted < min_weight:
                continue

            new_path = path + [dst]
            all_paths.append({
                "path": " → ".join(new_path),
                "impact": round(transmitted, 4),
                "depth": depth + 1,
                "mechanism": edge["mechanism"],
                "relation": edge["relation"],
            })

            # Accumulate at destination
            if dst in visited_vars:
                visited_vars[dst] = max(visited_vars[dst], transmitted)
            else:
                visited_vars[dst] = transmitted

            queue.append((dst, transmitted, depth + 1, new_path))

    # Compute M/D/K/X delta from terminal variables
    mdx = {"M": 0.0, "K": 0.0, "D": 0.0, "X": 0.0}
    for var, impact in visited_vars.items():
        sensitivity = VARIABLE_MDX_SENSITIVITY.get(var, {"M": 0.0, "K": 0.05, "D": 0.02, "X": 0.02})
        for dim in mdx:
            mdx[dim] += impact * sensitivity[dim]

    # Clamp
    for dim in mdx:
        mdx[dim] = round(min(2.5, max(-2.5, mdx[dim])), 4)

    return PropagationResult(
        source_variable=initial_variable,
        source_impact=initial_impact,
        paths=sorted(all_paths, key=lambda p: p["impact"], reverse=True),
        terminal_variables={k: round(v, 4) for k, v in sorted(visited_vars.items(), key=lambda x: x[1], reverse=True)},
        mdx_delta=mdx,
        regime="calm" if k_level < 0.3 else "normal" if k_level < 0.5 else "elevated" if k_level < 0.7 else "crisis",
        total_paths=len(all_paths),
        max_depth=max((p["depth"] for p in all_paths), default=0),
    )


def resolve_event_causal(
    entity_env: dict[str, Any],
    event_variables: list[str],
    event_impact: float,
    k_level: float = 0.5,
) -> dict[str, Any]:
    """Full causal resolution for an event hitting an entity.

    Propagates impact from all touched variables, merges results,
    and computes combined M/D/K/X delta.
    """
    all_paths: list[dict] = []
    all_terminals: dict[str, float] = {}
    combined_mdx = {"M": 0.0, "K": 0.0, "D": 0.0, "X": 0.0}

    for var in event_variables:
        result = propagate_impact(
            entity_env=entity_env,
            initial_variable=var,
            initial_impact=event_impact,
            k_level=k_level,
        )
        all_paths.extend(result.paths)
        for tv, impact in result.terminal_variables.items():
            all_terminals[tv] = max(all_terminals.get(tv, 0), impact)
        for dim in combined_mdx:
            combined_mdx[dim] += result.mdx_delta[dim]

    # Clamp
    for dim in combined_mdx:
        combined_mdx[dim] = round(min(2.5, max(-2.5, combined_mdx[dim])), 4)

    # Sort paths by impact
    all_paths.sort(key=lambda p: p["impact"], reverse=True)

    return {
        "entity_id": entity_env.get("entity_id"),
        "entity_name": entity_env.get("entity_name"),
        "event_variables": event_variables,
        "event_impact": event_impact,
        "k_level": k_level,
        "regime": "calm" if k_level < 0.3 else "normal" if k_level < 0.5 else "elevated" if k_level < 0.7 else "crisis",
        "propagation_paths": all_paths[:15],
        "terminal_variables": dict(list(all_terminals.items())[:10]),
        "mdx_delta": combined_mdx,
        "total_paths": len(all_paths),
    }
