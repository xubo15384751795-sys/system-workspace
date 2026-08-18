from __future__ import annotations

from collections.abc import Mapping

from nlp.extraction.schemas import ExtractedEntity, StructuralEventCard, VariableMapping


class ConfidenceRules:
    """Rule-based confidence scoring for candidate NLP outputs.

    Scores are intentionally conservative: the NLP layer proposes structure,
    but it does not admit evidence or make final framework judgments.
    """

    def score_entities(self, entities: list[ExtractedEntity]) -> float:
        if not entities:
            return 0.0
        grounded = sum(1 for entity in entities if entity.evidence_quote.strip())
        grounded_ratio = grounded / len(entities)
        diversity = len({entity.type for entity in entities})
        return round(min(0.9, 0.35 + grounded_ratio * 0.35 + diversity * 0.04), 2)

    def score_mapping(self, mapping: VariableMapping) -> float:
        populated = sum(1 for values in _mapping_values(mapping).values() if values)
        total_items = sum(len(values) for values in _mapping_values(mapping).values())
        if populated == 0:
            return 0.0
        return round(min(0.85, 0.25 + populated * 0.08 + min(total_items, 12) * 0.015), 2)

    def score_event_card(self, card: StructuralEventCard) -> dict[str, float]:
        quote_grounding = _quote_grounding_score(card.evidence_quotes)
        mapping_conf = self.score_mapping(card.variable_mapping)
        field_count = sum(
            1
            for values in [
                card.actors,
                card.assets,
                card.triggers,
                card.anchors,
                card.liquidity_paths,
                card.policy_response,
                card.market_impact,
            ]
            if values
        )
        event_conf = min(0.85, 0.25 + quote_grounding * 0.25 + mapping_conf * 0.25 + field_count * 0.04)
        return {
            "event_extraction": round(event_conf, 2),
            "variable_mapping": mapping_conf,
            "quote_grounding": quote_grounding,
        }


def score_confidence(
    item: StructuralEventCard | VariableMapping | list[ExtractedEntity] | Mapping[str, object],
) -> dict[str, float] | float:
    rules = ConfidenceRules()
    if isinstance(item, StructuralEventCard):
        return rules.score_event_card(item)
    if isinstance(item, VariableMapping):
        return rules.score_mapping(item)
    if isinstance(item, list):
        return rules.score_entities(item)
    if isinstance(item, Mapping):
        raw_quotes = item.get("evidence_quotes", [])
        quotes = raw_quotes if isinstance(raw_quotes, (list, tuple)) else []
        quote_grounding = _quote_grounding_score([str(q) for q in quotes])
        return {"quote_grounding": quote_grounding}
    raise TypeError(f"Unsupported confidence item: {type(item)!r}")


def _mapping_values(mapping: VariableMapping) -> dict[str, list[str]]:
    return {
        "S": mapping.S,
        "A": mapping.A,
        "L": mapping.L,
        "V": mapping.V,
        "P": mapping.P,
        "tau": mapping.tau,
    }


def _quote_grounding_score(quotes: list[str]) -> float:
    if not quotes:
        return 0.0
    useful = [quote for quote in quotes if len(quote.strip()) >= 20]
    return round(min(0.85, 0.35 + len(useful) * 0.1), 2)
