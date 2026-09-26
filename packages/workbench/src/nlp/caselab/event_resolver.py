"""Event Resolver — maps real-world events to M/D/K/X via entity environments.

READS: entity_environments.json (pre-built index)
WRITES: Output/state/caselab/events/ (standalone)

Input:  event description + entity name
Output: environment context, structural impact chain, M/D/K/X delta

Usage:
    from nlp.caselab.event_resolver import EventResolver
    resolver = EventResolver()
    result = resolver.resolve("Goldman Sachs 宣布裁员 20%", entity_name="Goldman Sachs")
"""
from __future__ import annotations

from system_runtime.paths import WorkspacePaths

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

ENV_INDEX = WorkspacePaths.discover().root / "Data" / "nlp" / "caselab_environments"
OUTPUT_DIR = WorkspacePaths.discover().root / "Output" / "state" / "caselab" / "events"


class EventResolver:
    """Resolves real-world events against entity environments."""

    def __init__(self, index_path: Path | None = None):
        self.index_path = index_path or ENV_INDEX / "entity_environments.json"
        self._environments: dict[str, dict] = {}
        self._load()

    def _load(self):
        if self.index_path.exists():
            self._environments = json.loads(self.index_path.read_text(encoding="utf-8"))

    def resolve(
        self,
        event_text: str,
        entity_name: str | None = None,
    ) -> dict[str, Any]:
        """Resolve an event against entity environment.

        Parameters
        ----------
        event_text : str
            Natural language event description.
        entity_name : str, optional
            Entity name. If not provided, attempts to extract from event_text.

        Returns
        -------
        dict with keys:
            entity: matched entity info
            environment: full environment context
            event_analysis: parsed event type and keywords
            structural_impact: causal chain
            mdx_delta: estimated M/D/K/X changes
            historical_precedent: closest connected case
        """
        # 1. Find entity
        if not entity_name:
            entity_name = self._extract_entity(event_text)
        env = self._find_entity(entity_name or "")

        if not env:
            return {
                "status": "entity_not_found",
                "query": entity_name,
                "suggestion": "Add this entity to CaseLab first.",
            }

        # 2. Parse event
        event_analysis = self._analyze_event(event_text, env)

        # 3. Compute structural impact
        impact = self._compute_structural_impact(event_analysis, env)

        # 4. Estimate M/D/K/X delta
        mdx_delta = self._estimate_mdx_delta(event_analysis, impact, env)

        # 5. Find historical precedent
        precedent = self._find_precedent(event_analysis, env)

        result = {
            "status": "resolved",
            "timestamp": datetime.now(UTC).isoformat(),
            "event_text": event_text,
            "entity": {
                "id": env["entity_id"],
                "name": env["entity_name"],
                "type": env["entity_type"],
            },
            "environment": {
                "variables": env["environment_variables"],
                "dna_keywords": env["dna_keywords"],
                "inertia_map": env["inertia_map"],
                "mechanisms": env["mechanisms"],
                "structural_vector": env["structural_vector"],
            },
            "event_analysis": event_analysis,
            "structural_impact": impact,
            "mdx_delta": mdx_delta,
            "historical_precedent": precedent,
        }

        from nlp.canonical_compat import build_event_resolution_claim

        canonical_claim = build_event_resolution_claim(result)
        result["canonical_claim_id"] = canonical_claim["claim_id"]
        result["canonical_claim"] = canonical_claim

        # Save
        self._save_result(result)
        return result

    def _find_entity(self, name: str) -> dict | None:
        """Find entity by name (fuzzy match)."""
        if not name:
            return None

        name_lower = name.lower().strip()

        # Exact match
        for eid, env in self._environments.items():
            if env["entity_name"].lower() == name_lower:
                return env
            if eid == name_lower.replace(" ", "_"):
                return env

        # Alias match (exact abbreviations — checked BEFORE partial to avoid false substring matches)
        aliases = {
            "gs": "goldman_sachs",
            "ms": "morgan_stanley",
            "jpm": "jpmorgan_chase",
            "jpmorgan": "jpmorgan_chase",
            "jp morgan": "jpmorgan_chase",
            "fed": "federal_reserve",
            "boj": "bank_of_japan",
            "boe": "bank_of_england",
            "ecb": "ecb",
            "pboc": "pboc",
            "hkma": "hkma",
            "mas": "mas",
            "fdic": "fdic",
            "sec": "securities_and_exchange_commission",
            "cftc": "cftc",
            "taiwan": "taiwan",
            "hk": "hong_kong",
            "us": "united_states",
            "usa": "united_states",
            "uk": "united_kingdom",
            "eu": "european_commission",
        }
        if name_lower in aliases:
            target_id = aliases[name_lower]
            for eid, env in self._environments.items():
                if eid == target_id:
                    return env

        # Partial match (after alias to avoid 'gs' matching 'holdings', 'fed' matching 'fedwire', etc.)
        for eid, env in self._environments.items():
            if name_lower in env["entity_name"].lower():
                return env

        # Last resort: substring in entity_id (only if name is long enough to avoid false matches)
        if len(name_lower) >= 4:
            for eid, env in self._environments.items():
                if name_lower in eid:
                    return env

        return None

    def _extract_entity(self, text: str) -> str | None:
        """Try to extract entity name from event text."""
        text_lower = text.lower()
        for eid, env in self._environments.items():
            ename = env["entity_name"].lower()
            if ename in text_lower or eid.replace("_", " ") in text_lower:
                return cast(str, env["entity_name"])
        return None

    def _analyze_event(self, text: str, env: dict) -> dict[str, Any]:
        """Analyze what kind of event this is and what variables it touches."""
        text_lower = text.lower()

        # Event type classification
        event_types: list[str] = []
        touched_variables: list[str] = []
        severity = 0.5  # default

        # Financial events
        if any(kw in text_lower for kw in ["裁员", "layoff", "job cut", "downsiz"]):
            event_types.append("workforce_reduction")
            touched_variables.extend(["headcount", "talent_density", "cost_structure"])
            severity = 0.4
        if any(kw in text_lower for kw in ["融资", "fundrais", "capital rais", "bond issu"]):
            event_types.append("capital_raise")
            touched_variables.extend(["cash_flow", "leverage", "balance_sheet"])
            severity = 0.3
        if any(kw in text_lower for kw in ["违约", "default", "bankrupt", "破产"]):
            event_types.append("default")
            touched_variables.extend(["credit_spread", "counterparty_exposure", "balance_sheet"])
            severity = 0.9
        if any(kw in text_lower for kw in ["收购", "acquir", "merger", "合并"]):
            event_types.append("ma_event")
            touched_variables.extend(["market_share", "leverage", "balance_sheet"])
            severity = 0.5
        if any(kw in text_lower for kw in ["制裁", "sanction", "export control", "出口管制"]):
            event_types.append("regulatory_action")
            touched_variables.extend(["regulatory_risk", "market_share", "revenue"])
            severity = 0.7
        if any(kw in text_lower for kw in ["加息", "rate hike", "tighten", "缩表"]):
            event_types.append("monetary_tightening")
            touched_variables.extend(["credit_spread", "leverage", "cash_flow"])
            severity = 0.6
        if any(kw in text_lower for kw in ["降息", "rate cut", "eas", "stimulus"]):
            event_types.append("monetary_easing")
            touched_variables.extend(["credit_spread", "valuation", "capital_flow"])
            severity = 0.3
        if any(kw in text_lower for kw in ["财报", "earnings", "revenue miss", "profit warn"]):
            event_types.append("earnings_event")
            touched_variables.extend(["revenue", "stock_price", "analyst_sentiment"])
            severity = 0.4
        if any(kw in text_lower for kw in ["危机", "crisis", "crash", "崩盘"]):
            event_types.append("crisis_event")
            touched_variables.extend(["stock_price", "credit_spread", "trading_volume"])
            severity = 0.9
        if any(kw in text_lower for kw in ["上市", "ipo", "listing", "direct listing"]):
            event_types.append("ipo_event")
            touched_variables.extend(["valuation", "stock_price", "cash_flow"])
            severity = 0.4
        if any(kw in text_lower for kw in ["监管", "regulation", "investigation", "罚款"]):
            event_types.append("regulatory_event")
            touched_variables.extend(["regulatory_risk", "stock_price"])
            severity = 0.6

        if not event_types:
            event_types.append("general_news")
            severity = 0.2

        # Cross-reference with entity's environment variables
        env_vars_flat = []
        for cat_vars in env.get("environment_variables", {}).values():
            env_vars_flat.extend(cat_vars)

        matched_vars = [v for v in touched_variables if v in env_vars_flat]

        return {
            "event_types": event_types,
            "touched_variables": touched_variables,
            "matched_env_variables": matched_vars,
            "severity": severity,
            "text_keywords": _extract_event_keywords(text),
        }

    def _compute_structural_impact(
        self, event_analysis: dict, env: dict
    ) -> dict[str, Any]:
        """Compute how the event propagates through entity's variable structure."""
        touched = set(event_analysis["touched_variables"])
        graph = env.get("interaction_graph", [])
        propagation_chain: list[dict[str, str]] = []
        affected_vars = set(touched)

        # Trace through interaction graph
        for edge in graph:
            if edge["from"] in affected_vars:
                propagation_chain.append({
                    "from": edge["from"],
                    "to": edge["to"],
                    "relation": edge["relation"],
                    "via": edge["via_mechanism"],
                })
                affected_vars.add(edge["to"])

        # Inertia response
        inertia_response: list[str] = []
        for situation, response in env.get("inertia_map", {}).items():
            for event_type in event_analysis["event_types"]:
                if _concept_overlap(situation, event_type):
                    inertia_response.append(f"When [{situation}]: {response}")

        # DNA-based default response
        dna_response = []
        for kw in env.get("dna_keywords", []):
            if "杠杆" in kw and "leverage" in touched:
                dna_response.append(f"DNA [{kw}]: entity will likely deleverage")
            if "风险" in kw and any(v in touched for v in ["credit_spread", "counterparty_exposure"]):
                dna_response.append(f"DNA [{kw}]: entity will protect balance sheet first")
            if "流动性" in kw and "cash_flow" in touched:
                dna_response.append(f"DNA [{kw}]: entity will prioritize liquidity")
            if "平台" in kw and "market_share" in touched:
                dna_response.append(f"DNA [{kw}]: entity will defend platform dominance")

        return {
            "initial_impact": list(touched),
            "propagation_chain": propagation_chain,
            "all_affected_variables": sorted(affected_vars),
            "inertia_response": inertia_response,
            "dna_response": dna_response,
            "propagation_paths": env.get("mdx_impact_profile", {}).get("propagation_path", []),
        }

    def _estimate_mdx_delta(
        self,
        event_analysis: dict,
        impact: dict,
        env: dict,
    ) -> dict[str, Any]:
        """Estimate how this event changes M/D/K/X."""
        sensitivity = env.get("mdx_impact_profile", {}).get("sensitivity", {})
        severity = event_analysis["severity"]

        delta = {
            "M": round(sensitivity.get("M", 0) * severity * 0.1, 4),
            "K": round(sensitivity.get("K", 0) * severity * 0.1, 4),
            "D": round(sensitivity.get("D", 0) * severity * 0.1, 4),
            "X": round(sensitivity.get("X", 0) * severity * 0.1, 4),
        }

        # Adjust based on touched variables
        touched = set(event_analysis["touched_variables"])
        if "credit_spread" in touched:
            delta["K"] += 0.02
            delta["D"] += 0.01
        if "leverage" in touched:
            delta["K"] += 0.015
        if "capital_flow" in touched:
            delta["M"] += 0.02
            delta["X"] += 0.015
        if "counterparty_exposure" in touched:
            delta["K"] += 0.02
            delta["D"] += 0.015

        # Clamp
        for k in delta:
            delta[k] = round(min(0.15, max(-0.05, delta[k])), 4)

        direction = "WORSENING" if (delta["K"] > 0 or delta["D"] > 0) else "STABLE"

        return {
            "delta": delta,
            "direction": direction,
            "confidence": round(min(1.0, len(impact["propagation_chain"]) * 0.2 + 0.3), 2),
            "note": "Estimate based on entity sensitivity and event severity. Verify with market data.",
        }

    def _find_precedent(self, event_analysis: dict, env: dict) -> dict[str, Any]:
        """Find closest historical precedent from connected cases."""
        cases = env.get("historical_precedents", [])
        if not cases:
            return {"cases": [], "note": "No historical cases connected to this entity."}

        # Match event type to case mechanisms
        best_match = None
        best_score = 0

        for case_id in cases:
            case_env = None
            # Find case in environments
            for eid, e in self._environments.items():
                if case_id.lower().replace(" ", "_") in eid:
                    case_env = e
                    break

            if not case_env:
                continue

            # Score by mechanism overlap
            case_mechs = set(m.lower() for m in case_env.get("mechanisms", []))
            event_kws = set(event_analysis.get("text_keywords", []))
            overlap = len(case_mechs & event_kws)
            if overlap > best_score:
                best_score = overlap
                best_match = {
                    "case_id": case_id,
                    "mechanisms": case_env.get("mechanisms", []),
                    "relevance": overlap,
                }

        return {
            "cases": cases,
            "best_match": best_match,
            "note": f"Based on {len(cases)} connected cases. Best match has {best_score} mechanism overlap.",
        }

    def _save_result(self, result: dict):
        """Save resolution result to output directory."""
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        entity_id = result.get("entity", {}).get("id", "unknown")
        filename = f"{ts}_{entity_id}.json"
        (OUTPUT_DIR / filename).write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def _extract_event_keywords(text: str) -> list[str]:
    """Extract structural keywords from event text."""
    from nlp.caselab.text_match import extract_structural_keywords
    counts = extract_structural_keywords(text)
    return [c for c, n in counts.most_common(10) if n > 0]


def _concept_overlap(text: str, concept: str) -> bool:
    """Check if text overlaps with a concept."""
    text_lower = text.lower()
    concept_lower = concept.lower()
    overlap_words = {
        "workforce_reduction": ["裁员", "layoff", "cut", "downsiz", "减少"],
        "capital_raise": ["融资", "fundrais", "capital", "bond"],
        "default": ["违约", "default", "bankrupt"],
        "crisis_event": ["危机", "crisis", "crash"],
        "regulatory_action": ["制裁", "sanction", "control", "罚款"],
    }
    keywords = overlap_words.get(concept_lower, [concept_lower])
    return any(kw in text_lower for kw in keywords)
