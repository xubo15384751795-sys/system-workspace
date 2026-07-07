from __future__ import annotations

import re

from nlp.chunking.chunk_schema import TextChunk
from nlp.extraction.schemas import ExtractedEntity, StructuralEventCard, VariableMapping
from nlp.mapping.variable_mapper import VariableMapper


def extract_event_card(
    chunks: list[TextChunk],
    entities: list[ExtractedEntity],
    *,
    document_id: str = "",
    event_name: str = "",
    use_llm: bool = False,
) -> StructuralEventCard:
    """Extract a candidate structural event card from chunks and entities.

    In MVP v0, extraction is rule-based with structured heuristics.
    The `use_llm` flag is reserved for future LLM-assisted extraction.

    All outputs are candidate — never auto-admitted.
    """
    joined = "\n".join(c.text for c in chunks)

    event_name = event_name or _guess_event_name(chunks)
    source_chunk_ids = [c.chunk_id for c in chunks]

    actors = _deduplicate([e.text for e in entities if e.type in ("institution", "regulator")])
    assets = _deduplicate([e.text for e in entities if e.type == "asset"])
    triggers = _extract_triggers(joined, entities)
    anchors = _extract_anchors(entities)
    liquidity_paths = _extract_liquidity_paths(joined, entities)
    visibility_shift = _extract_visibility_shift(joined)
    policy_response = _extract_policy_response(joined, entities)
    market_impact = _extract_market_impact(joined)
    evidence_quotes = _extract_evidence_quotes(chunks, entities)
    mapper = VariableMapper()
    mapping_result = mapper.map_event_with_votes(entities=entities, text=joined)
    variable_mapping = mapping_result.variable_mapping
    confidence = _estimate_confidence(entities, evidence_quotes, variable_mapping)
    source_text_quote = evidence_quotes[0] if evidence_quotes else ""
    quote_start_char = joined.find(source_text_quote) if source_text_quote else -1
    quote_end_char = quote_start_char + len(source_text_quote) if quote_start_char >= 0 else -1
    first_chunk = chunks[0] if chunks else None

    return StructuralEventCard(
        event_id=f"event_{document_id}" if document_id else f"event_{_slugify(event_name)}",
        event_name=event_name,
        source_chunks=source_chunk_ids,
        parent_chunk_id=first_chunk.parent_chunk_id if first_chunk else "",
        parent_section_title=first_chunk.parent_section_title if first_chunk else "",
        parent_context_hash=first_chunk.parent_context_hash if first_chunk else "",
        source_text_quote=source_text_quote,
        quote_start_char=quote_start_char,
        quote_end_char=quote_end_char,
        actors=actors,
        assets=assets,
        triggers=triggers,
        anchors=anchors,
        liquidity_paths=liquidity_paths,
        visibility_shift=visibility_shift,
        policy_response=policy_response,
        market_impact=market_impact,
        evidence_quotes=evidence_quotes,
        variable_mapping=variable_mapping,
        variable_votes=[vote.model_dump() for vote in mapping_result.votes],
        confidence_by_variable=mapping_result.confidence_by_variable,
        confidence=confidence,
        status="candidate",
        extraction_notes=(
            "Rule-based extraction (MVP v0). "
            "All entity and event assignments are candidate — not admitted evidence."
        ),
    )


def _guess_event_name(chunks: list[TextChunk]) -> str:
    for chunk in chunks[:2]:
        heading = chunk.metadata.get("heading", "")
        if heading:
            return heading
    if chunks:
        return chunks[0].text[:80].strip()
    return "Untitled Event"


def _deduplicate(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _extract_triggers(joined: str, entities: list[ExtractedEntity]) -> list[str]:
    triggers: list[str] = []
    trigger_keywords = [
        "triggered by", "led to", "caused", "prompted", "resulted in",
        "followed", "after", "when", "as a result of",
    ]
    for kw in trigger_keywords:
        m = re.search(rf"{re.escape(kw)}\s+(.{{20,150}}?)[\.\n]", joined, re.IGNORECASE)
        if m:
            triggers.append(re.sub(r"\s+", " ", m.group(1)).strip())
    if not triggers:
        risk_entities = [e.text for e in entities if e.type == "risk_event"]
        triggers.extend(risk_entities[:3])
    return _deduplicate(triggers)[:5]


def _extract_anchors(entities: list[ExtractedEntity]) -> list[str]:
    anchors: list[str] = []
    for e in entities:
        if e.type in ("asset", "valuation_gap"):
            anchors.append(e.text)
    return _deduplicate(anchors)[:5]


def _extract_liquidity_paths(joined: str, entities: list[ExtractedEntity]) -> list[str]:
    paths: list[str] = []
    path_patterns = [
        r"(?:liquidation|selling|withdrawal|redemption|margin call|collateral call|"
        r"fire sale|run)\s+(?:of|on|through|via)\s+(.{{10,80}}?)[\.\,\n]",
        r"(?:sold|liquidated|withdrawn|redeemed)\s+(.{{10,80}}?)[\.\,\n]",
    ]
    for pat in path_patterns:
        for m in re.finditer(pat, joined, re.IGNORECASE):
            paths.append(re.sub(r"\s+", " ", m.group(1)).strip())
    return _deduplicate(paths)[:5]


def _extract_visibility_shift(joined: str) -> str:
    visibility_markers = [
        r"(?:became visible|became apparent|came to light|was revealed|"
        r"was disclosed|materialized|emerged|surfaced)",
    ]
    for pat in visibility_markers:
        m = re.search(rf"(.{{0,120}}){pat}(.{{0,120}})", joined, re.IGNORECASE)
        if m:
            return re.sub(r"\s+", " ", (m.group(1) + m.group(2))).strip()[:300]
    return ""


def _extract_policy_response(joined: str, entities: list[ExtractedEntity]) -> list[str]:
    responses: list[str] = []
    policy_patterns = [
        r"(?:announced|introduced|launched|implemented|deployed|activated)\s+"
        r"(.{{10,100}}?)(?:program|facility|tool|measure|intervention|backstop)",
        r"(?:BTFP|discount window|QE|rate cut|bailout|guarantee|bridge)\b.{0,80}",
    ]
    for pat in policy_patterns:
        for m in re.finditer(pat, joined, re.IGNORECASE):
            responses.append(re.sub(r"\s+", " ", m.group(0)).strip())
    policy_entities = [e.text for e in entities if e.type == "policy_tool"][:3]
    responses.extend(policy_entities)
    return _deduplicate(responses)[:5]


def _extract_market_impact(joined: str) -> list[str]:
    impact_markers = [
        r"(?:sell.?off|rout|plunge|surge|spike|crash|spread widening|"
        r"contagion|flight.?to.?quality|risk.?off|volatility)\b.{0,100}",
    ]
    impacts: list[str] = []
    for pat in impact_markers:
        for m in re.finditer(pat, joined, re.IGNORECASE):
            impacts.append(re.sub(r"\s+", " ", m.group(0)).strip())
    return _deduplicate(impacts)[:5]


def _extract_evidence_quotes(chunks: list[TextChunk], entities: list[ExtractedEntity]) -> list[str]:
    quotes: list[str] = []
    for e in entities[:8]:
        if e.evidence_quote and e.evidence_quote not in quotes:
            quotes.append(e.evidence_quote)
    if not quotes and chunks:
        first = chunks[0].text[:300].strip()
        quotes = [first]
    return quotes[:5]


def _build_variable_mapping(entities: list[ExtractedEntity], joined: str) -> VariableMapping:
    vm: dict[str, list[str]] = {"S": [], "A": [], "L": [], "V": [], "P": [], "tau": []}
    for e in entities:
        for var in e.variable_hint:
            if e.text not in vm[var]:
                vm[var].append(e.text[:100])

    event_signals: dict[str, list[str]] = {
        "L": [r"forced\s+sell", r"liquidation", r"fire\s+sale", r"margin\s+call"],
        "A": [r"anchor", r"valuation\s+gap", r"book\s+value", r"fair\s+value"],
        "V": [r"unrealized", r"transparency", r"disclosure", r"visibility"],
        "P": [r"backstop", r"policy\s+tool", r"intervention", r"guarantee"],
        "tau": [r"delay", r"lag", r"recognition\s+lag", r"latency"],
        "S": [r"institution", r"actor", r"depositor", r"investor"],
    }
    for var, patterns in event_signals.items():
        for pat in patterns:
            if re.search(pat, joined, re.IGNORECASE) and not vm[var]:
                vm[var].append(f"signal:{pat}")

    return VariableMapping(**vm)


def _estimate_confidence(
    entities: list[ExtractedEntity],
    quotes: list[str],
    vm: VariableMapping,
) -> dict[str, float]:
    entity_conf = min(0.9, 0.5 + len(entities) * 0.02) if entities else 0.3
    quote_conf = 0.8 if len(quotes) >= 2 else (0.5 if quotes else 0.2)
    total_vars = sum(1 for v in [vm.S, vm.A, vm.L, vm.V, vm.P, vm.tau] if v)
    mapping_conf = min(0.85, 0.3 + total_vars * 0.1)
    return {
        "entity_extraction": round(entity_conf, 2),
        "event_extraction": round((entity_conf + quote_conf) / 2, 2),
        "variable_mapping": round(mapping_conf, 2),
        "quote_grounding": round(quote_conf, 2),
    }


def _slugify(value: str) -> str:
    value = value.lower().replace(" ", "_")
    return re.sub(r"[^a-z0-9_]", "", value)[:80]
