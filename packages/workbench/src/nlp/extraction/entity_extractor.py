from __future__ import annotations

import re

from nlp.chunking.chunk_schema import TextChunk
from nlp.extraction.schemas import ExtractedEntity

INSTITUTION_PATTERNS = [
    r"\b(Federal Reserve|Fed|ECB|Bank of England|BoE|Bank of Japan|BoJ|"
    r"PBoC|BIS|IMF|Treasury|OFR|FSOC|SEC|FDIC|OCC)\b",
    r"\b(Silicon Valley Bank|SVB|Credit Suisse|Deutsche Bank|Goldman Sachs|"
    r"JPMorgan|BlackRock|Bridgewater|PIMCO|Citadel)\b",
    r"\b[A-Z][a-z]+ (?:Bank|Fund|Capital|Management|Advisors|Partners)\b",
]

REGULATOR_PATTERNS = [
    r"\b(Federal Reserve|Fed|ECB|SEC|CFTC|FDIC|OCC|FCA|PRA|ESMA|BIS|"
    r"Financial Stability Board|FSB)\b",
]

ASSET_PATTERNS = [
    r"\b(Treasur(?:y|ies)|MBS|CMBS|CLO|CDO|corporate bonds?|"
    r"equities?|stocks?|private credit|private equity|real estate|"
    r"commodit(?:y|ies)|gold|oil|FX|currency|crypto)\b",
]

POLICY_TOOL_PATTERNS = [
    r"\b(interest rate|federal funds rate|discount window|BTFP|QE|"
    r"quantitative (?:tightening|easing)|yield curve control|"
    r"forward guidance|capital buffer|LCR|NSFR|stress test|CCAR)\b",
]

RISK_EVENT_PATTERNS = [
    r"\b(default|bankruptcy|downgrade|downgraded|write.?down|"
    r"impairment|haircut|margin call|collateral call|fire sale|"
    r"forced sell(?:ing)?|run|contagion|spillover|contagion)\b",
]

VALUATION_GAP_PATTERNS = [
    r"\b(unrealized losses?|mark.?to.?market|book value|fair value|"
    r"held.?to.?maturity|available.?for.?sale|valuation gap|"
    r"discount|premium|NAV|basis point|spread)\b",
]

ENTITY_RULES: list[tuple[str, list[str], list[str]]] = [
    ("institution", INSTITUTION_PATTERNS, ["S", "P"]),
    ("regulator", REGULATOR_PATTERNS, ["S", "P", "V"]),
    ("asset", ASSET_PATTERNS, ["A", "L"]),
    ("policy_tool", POLICY_TOOL_PATTERNS, ["L", "A", "P"]),
    ("risk_event", RISK_EVENT_PATTERNS, ["A", "L", "V"]),
    ("valuation_gap", VALUATION_GAP_PATTERNS, ["A", "V", "tau"]),
]


def extract_entities(chunks: list[TextChunk]) -> list[ExtractedEntity]:
    entities: list[ExtractedEntity] = []
    seen: set[tuple[str, str, str]] = set()

    for chunk in chunks:
        for entity_type, patterns, var_hints in ENTITY_RULES:
            for pattern in patterns:
                for match in re.finditer(pattern, chunk.text, re.IGNORECASE):
                    text = match.group(0).strip()
                    quote = _find_quote(chunk.text, text)
                    key = (chunk.chunk_id, entity_type, text.lower())
                    if key in seen:
                        continue
                    seen.add(key)
                    entities.append(
                        ExtractedEntity(
                            chunk_id=chunk.chunk_id,
                            text=text,
                            type=entity_type,
                            variable_hint=list(var_hints),
                            evidence_quote=quote,
                        )
                    )

    return entities


def _find_quote(text: str, entity: str, context_chars: int = 200) -> str:
    idx = text.lower().find(entity.lower())
    if idx < 0:
        return entity
    start = max(0, idx - context_chars // 2)
    end = min(len(text), idx + len(entity) + context_chars // 2)
    return text[start:end].strip()
