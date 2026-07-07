from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, Field

from nlp.chunking.chunk_schema import TextChunk
from nlp.extraction.schemas import ExtractedEntity

RELATION_TYPES = [
    "holds",
    "funds",
    "guarantees",
    "regulates",
    "liquidates",
    "reprices",
    "backstops",
    "transmits",
    "depends_on",
    "exposes_to",
]


class ExtractedRelation(BaseModel):
    source: str
    target: str
    relation: str
    evidence_quote: str = ""
    chunk_id: str = ""
    confidence: float = 0.5


_RELATION_PATTERNS: list[tuple[str, str, float]] = [
    ("holds", r"(\b[A-Z][a-zA-Z&.\s]{3,40}?)\s+(?:holds?|held|owns?|owned)\s+(\b[A-Z][a-zA-Z&.\s]{3,40}?)(?:\.|,|\s+worth|\s+valued|\s+in\s+the)", 0.6),
    ("funds", r"(\b[A-Z][a-zA-Z&.\s]{3,40}?)\s+(?:funds?|funded|provides?\s+funding\s+(?:to|for))\s+(\b[A-Z][a-zA-Z&.\s]{3,40}?)(?:\.|,|\s+through|\s+via)", 0.6),
    ("guarantees", r"(\b[A-Z][a-zA-Z&.\s]{3,40}?)\s+(?:guarantees?|guaranteed|backstops?|underwrites?)\s+(\b[A-Z][a-zA-Z&.\s]{3,40}?)(?:\.|,|\s+(?:against|for|up\s+to))", 0.7),
    ("regulates", r"(\b[A-Z][a-zA-Z&.\s]{3,40}?)\s+(?:regulates?|oversees?|supervises?)\s+(\b[A-Z][a-zA-Z&.\s]{3,40}?)(?:\.|,|;)", 0.65),
    ("liquidates", r"(\b[A-Z][a-zA-Z&.\s]{3,40}?)\s+(?:liquidates?|sold|selling|unwound|unwinds?)\s+(\b[A-Z][a-zA-Z&.\s]{3,40}?)(?:\.|,|\s+(?:at|for|to|in))", 0.55),
    ("reprices", r"(\b[A-Z][a-zA-Z&.\s]{3,40}?)\s+(?:repriced|revalued|marked\s+(?:down|to))\s+(\b[A-Z][a-zA-Z&.\s]{3,40}?)(?:\.|,|\s+(?:from|to|at))", 0.55),
    ("transmits", r"(\b[A-Z][a-zA-Z&.\s]{3,40}?)\s+(?:transmits?|pass(?:ed|es)\s+(?:through|on)|channels?)\s+(?:to|through|via)?\s*(\b[A-Z][a-zA-Z&.\s]{3,40}?)(?:\.|,|;)", 0.45),
    ("depends_on", r"(\b[A-Z][a-zA-Z&.\s]{3,40}?)\s+(?:depends?\s+on|rel(?:y|ies)\s+on|linked\s+to)\s+(\b[A-Z][a-zA-Z&.\s]{3,40}?)(?:\.|,|;)", 0.55),
    ("exposes_to", r"(\b[A-Z][a-zA-Z&.\s]{3,40}?)\s+(?:exposes?\s+(?:to|against)|creates?\s+exposure\s+(?:to|for))\s+(\b[A-Z][a-zA-Z&.\s]{3,40}?)(?:\.|,|;)", 0.55),
    ("backstops", r"(\b[A-Z][a-zA-Z&.\s]{3,40}?)\s+(?:backstops?\s+)?(\b[A-Z][a-zA-Z&.\s]{3,40}?)(?:\s+(?:with|through|via)\s+(?:lending\s+)?(?:program|facility|tool))", 0.5),
]


def extract_relations(
    chunks: list[TextChunk] | None = None,
    entities: list[ExtractedEntity] | None = None,
    *,
    source_text: str = "",
    min_confidence: float = 0.4,
) -> list[ExtractedRelation]:
    """Extract directed relations between entities in text chunks.

    Supports two paths:
    1. Regex-based: chunks + entities for pattern-matched relations
    2. Co-occurrence: entities + source_text for entity-pair relations

    Extracts relations like holds, funds, guarantees, regulates, backstops, etc.
    """
    entities = entities or []
    chunks = chunks or []
    relations: list[ExtractedRelation] = []
    seen: set[tuple[str, str, str]] = set()

    entity_texts = {e.text.lower(): e.text for e in entities}

    for chunk in chunks:
        for rel_type, pattern, weight in _RELATION_PATTERNS:
            for m in re.finditer(pattern, chunk.text, re.IGNORECASE):
                source_raw = m.group(1).strip()
                target_raw = m.group(2).strip()
                source = _resolve_entity(source_raw, entity_texts)
                target = _resolve_entity(target_raw, entity_texts)
                if not source or not target or source.lower() == target.lower():
                    continue
                key = (source.lower(), target.lower(), rel_type)
                if key in seen:
                    continue
                seen.add(key)
                quote_start = max(0, m.start() - 60)
                quote_end = min(len(chunk.text), m.end() + 60)
                evidence = chunk.text[quote_start:quote_end].strip()
                confidence = weight
                if source in entity_texts and target in entity_texts:
                    confidence = min(0.85, weight + 0.15)
                if confidence < min_confidence:
                    continue
                relations.append(
                    ExtractedRelation(
                        source=source,
                        target=target,
                        relation=rel_type,
                        evidence_quote=evidence,
                        chunk_id=chunk.chunk_id,
                        confidence=round(confidence, 2),
                    )
                )

    if relations or not source_text.strip():
        return relations

    institution_types = {"institution", "regulator", "central_bank"}
    asset_types = {"asset", "collateral", "liability", "currency"}
    policy_types = {"policy_tool"}
    risk_types = {"risk_event", "valuation_gap", "liquidity_event", "narrative"}

    institutions = [e for e in entities if e.type in institution_types]
    assets = [e for e in entities if e.type in asset_types]
    policies = [e for e in entities if e.type in policy_types]
    risks = [e for e in entities if e.type in risk_types]

    for inst in institutions:
        for asset in assets:
            if _co_occur(source_text, inst.text, asset.text):
                key = (inst.text.lower(), asset.text.lower(), "holds")
                if key not in seen:
                    seen.add(key)
                    relations.append(
                        ExtractedRelation(
                            source=inst.text, target=asset.text, relation="holds",
                            evidence_quote=_find_co_occurrence(source_text, inst.text, asset.text),
                            confidence=0.5,
                        )
                    )

    for pol in policies:
        for inst in institutions:
            if _co_occur(source_text, pol.text, inst.text):
                key = (pol.text.lower(), inst.text.lower(), "backstops")
                if key not in seen:
                    seen.add(key)
                    relations.append(
                        ExtractedRelation(
                            source=pol.text, target=inst.text, relation="backstops",
                            evidence_quote=_find_co_occurrence(source_text, pol.text, inst.text),
                            confidence=0.5,
                        )
                    )

    for risk in risks:
        for asset in assets:
            if _co_occur(source_text, risk.text, asset.text):
                key = (risk.text.lower(), asset.text.lower(), "reprices")
                if key not in seen:
                    seen.add(key)
                    relations.append(
                        ExtractedRelation(
                            source=risk.text, target=asset.text, relation="reprices",
                            evidence_quote=_find_co_occurrence(source_text, risk.text, asset.text),
                            confidence=0.45,
                        )
                    )

    return relations


def _resolve_entity(text: str, entity_map: dict[str, str]) -> Optional[str]:
    tl = text.lower().strip()
    if tl in entity_map:
        return entity_map[tl]
    for ekey, evalue in entity_map.items():
        if ekey in tl or tl in ekey:
            return evalue
    if re.search(r"\b[A-Z][a-z]{2,}(?:\s[A-Z][a-z]{2,})*\b", text):
        return text.strip()
    return None


def _co_occur(text: str, a: str, b: str) -> bool:
    tl = text.lower()
    return a.lower() in tl and b.lower() in tl


def _find_co_occurrence(text: str, a: str, b: str) -> str:
    tl = text.lower()
    ai = tl.find(a.lower())
    bi = tl.find(b.lower())
    if ai < 0 or bi < 0:
        return ""
    start = max(0, min(ai, bi) - 40)
    end = min(len(text), max(ai + len(a), bi + len(b)) + 80)
    return text[start:end].strip()
