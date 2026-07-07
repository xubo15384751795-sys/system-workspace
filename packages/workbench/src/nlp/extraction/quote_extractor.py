from __future__ import annotations

import re

from nlp.chunking.chunk_schema import TextChunk


def extract_quotes(chunks: list[TextChunk], *, max_quotes: int = 10) -> list[dict[str, str]]:
    """Extract key evidence-bearing sentences from chunks.

    Selects sentences that contain named entities, numeric values,
    or structural keywords (risk, liquidity, valuation, etc.).
    """
    structural_keywords = [
        "risk", "liquidity", "funding", "valuation", "spread",
        "default", "downgrade", "volatility", "stress", "shock",
        "contagion", "margin", "collateral", "haircut", "run",
        "loss", "write-down", "impairment", "unrealized",
        "credit", "rate", "yield", "bond", "equity", "sell-off",
        "intervention", "backstop", "bailout", "guarantee",
        "anchor", "visibility", "opacity", "transparency",
        "forced sell", "fire sale", "liquidat",
        "私募", "风险", "流动", "估值", "违约", "杠杆",
    ]

    candidates: list[dict[str, str]] = []
    for chunk in chunks:
        sentences = _split_sentences(chunk.text)
        for sent in sentences:
            sent_clean = sent.strip()
            if len(sent_clean) < 30 or len(sent_clean) > 600:
                continue
            score = sum(1 for kw in structural_keywords if kw.lower() in sent_clean.lower())
            has_entity = bool(re.search(r"\b[A-Z][a-z]{2,}(?:\s[A-Z][a-z]{2,})*\b", sent_clean))
            has_number = bool(re.search(r"\d+(?:\.\d+)?%?", sent_clean))
            if score >= 2 or (score >= 1 and has_entity) or (score >= 1 and has_number):
                candidates.append({
                    "chunk_id": chunk.chunk_id,
                    "text": re.sub(r"\s+", " ", sent_clean),
                })

    candidates.sort(key=lambda x: sum(1 for kw in structural_keywords if kw.lower() in x["text"].lower()), reverse=True)
    return candidates[:max_quotes]


def _split_sentences(text: str) -> list[str]:
    raw = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
    return [s.strip() for s in raw if s.strip()]
