from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Optional, cast
from urllib.parse import urlparse

from workbench.external_http import (
    ExternalEndpointSpec,
    ExternalGatewayError,
    ExternalGatewayPolicyError,
    OwnedExternalHTTPGateway,
)
from workbench.paths import workspace_root as _workspace_root

from nlp.chunking.chunk_schema import TextChunk
from nlp.extraction.schemas import ExtractedEntity, StructuralEventCard, VariableMapping

ROOT = _workspace_root()
logger = logging.getLogger(__name__)
LLM_RESPONSE_MAX_BYTES = 2_000_000
EXTRACTION_PROMPT = """You are an extraction agent for a structural NLP system. Your job is to read the text below and extract a structured event card as JSON. Do not interpret, do not analyze — only extract what is explicitly stated in the text.

Return a JSON object with these fields:
- event_name: short descriptive name for the event described (max 80 chars)
- actors: list of institutions, organizations, or named actors mentioned
- assets: list of assets, securities, or financial instruments mentioned
- triggers: list of triggering events or proximate causes
- anchors: list of valuation anchors, reference prices, or confidence anchors mentioned
- liquidity_paths: list of liquidation channels, forced selling, withdrawals, or redemption paths
- visibility_shift: description of any change in information visibility, disclosure, or opacity (empty string if none)
- policy_response: list of policy actions, interventions, or backstop measures mentioned
- market_impact: list of market reactions, price moves, or contagion effects
- evidence_quotes: list of 1-5 exact verbatim quotes from the text that support the extraction (DO NOT paraphrase)
- variable_mapping: object with keys S, A, L, V, P, tau, each containing a list of relevant text strings found in the passage
- extraction_notes: brief note about any ambiguity or extraction difficulty (max 200 chars)

CRITICAL RULES:
1. Every evidence_quote must be an EXACT substring of the provided text. Copy-paste, do not rephrase.
2. Every entry in variable_mapping must be traceable to something in the text.
3. If something is not mentioned, use an empty list or empty string. Do not hallucinate.
4. The status field must ALWAYS be "candidate".

Text to extract from:
---
{text}
---

Return ONLY valid JSON. No markdown, no explanation outside the JSON."""


def _try_llm_extract(text: str, *, model: str = "") -> Optional[dict]:
    """Attempt LLM extraction via a provider-agnostic API call.

    Tries anthropic first, then falls back to a generic OpenAI-compatible
    endpoint if ANTHROPIC_API_KEY is not set.
    """
    prompt = EXTRACTION_PROMPT.format(text=text[:8000])
    result = _try_anthropic(prompt, model=model)
    if result is not None:
        return result
    logger.info("LLM extraction fallback: trying openai-compatible backend")
    result = _try_openai_compatible(prompt, model=model)
    if result is None:
        logger.warning("LLM extraction unavailable; returning no candidate")
    return result


def _try_anthropic(prompt: str, *, model: str) -> Optional[dict]:
    import os
    if not os.environ.get("ANTHROPIC_API_KEY"):
        logger.info("LLM extraction backend anthropic skipped: API key not configured")
        return None
    try:
        import anthropic
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=model or "claude-sonnet-4-6",
            max_tokens=2048,
            temperature=0.0,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text if response.content else ""
        return _parse_json(text)
    except Exception as exc:  # noqa: BLE001 - optional backend must not break extraction
        logger.warning("LLM extraction backend anthropic failed: %s", type(exc).__name__)
        return None


def _try_openai_compatible(prompt: str, *, model: str) -> Optional[dict]:
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("LLM_API_KEY")
    base_url = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
    if not api_key:
        logger.info("LLM extraction backend openai-compatible skipped: API key not configured")
        return None
    try:
        parsed_base_url = urlparse(base_url)
        host = parsed_base_url.hostname or ""
        configured_hosts = {
            item.strip().casefold()
            for item in os.environ.get("LLM_ALLOWED_HOSTS", "api.openai.com").split(",")
            if item.strip()
        }
        if host.casefold() not in configured_hosts:
            raise ValueError("LLM endpoint host is not allowlisted")
        endpoint_url = f"{base_url.rstrip('/')}/chat/completions"
        endpoint = ExternalEndpointSpec(
            endpoint_id="llm_chat_completions",
            url=endpoint_url,
            allowed_hosts=frozenset({host}),
        )
        payload = json.dumps({
            "model": model or "gpt-4o",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
            "max_tokens": 2048,
        }).encode("utf-8")
        with OwnedExternalHTTPGateway(
            {"llm_chat_completions": endpoint},
            max_request_bytes=LLM_RESPONSE_MAX_BYTES,
            max_response_bytes=LLM_RESPONSE_MAX_BYTES,
        ) as gateway:
            response = gateway.post(
                "llm_chat_completions",
                payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                timeout_sec=120,
            )
            if not 200 <= response.status_code < 300:
                raise ExternalGatewayError("LLM endpoint returned a non-success status")
            body = json.loads(response.content.decode("utf-8"))
            content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
            return _parse_json(content)
    except (ExternalGatewayError, ExternalGatewayPolicyError, ValueError) as exc:
        # Optional backend failures must remain visible without exposing the
        # configured URL, API key, prompt, or provider response.
        logger.warning("LLM extraction backend openai-compatible failed: %s", type(exc).__name__)
        return None


def _parse_json(text: str) -> Optional[dict]:
    if not text or not text.strip():
        return None
    text = text.strip()
    m = re.search(r'\{[\s\S]*\}', text)
    if m:
        text = m.group(0)
    try:
        return cast(dict[str, Any], json.loads(text))
    except json.JSONDecodeError:
        return None


def llm_extract_event_card(
    chunks: list[TextChunk],
    entities: list[ExtractedEntity],
    *,
    document_id: str = "",
    event_name: str = "",
    model: str = "",
) -> Optional[StructuralEventCard]:
    """LLM-assisted event card extraction, used as fallback for rule-based extraction.

    Only called when rule-based extraction produces low-confidence results.
    All outputs are candidate — never auto-admitted.
    """
    joined = "\n".join(c.text for c in chunks)
    raw = _try_llm_extract(joined, model=model)
    if raw is None:
        return None

    try:
        vm_raw = raw.get("variable_mapping", {})
        variable_mapping = VariableMapping(
            S=vm_raw.get("S", []),
            A=vm_raw.get("A", []),
            L=vm_raw.get("L", []),
            V=vm_raw.get("V", []),
            P=vm_raw.get("P", []),
            tau=vm_raw.get("tau", []),
        )
        evidence_quotes = raw.get("evidence_quotes", [])
        if not evidence_quotes:
            evidence_quotes = [joined[:300].strip()]
        grounded_quotes = [q for q in evidence_quotes if q and q in joined]
        if not grounded_quotes:
            grounded_quotes = [joined[:300].strip()]
        source_quote = grounded_quotes[0] if grounded_quotes else joined[:300].strip()
        first_chunk = chunks[0] if chunks else None

        card = StructuralEventCard(
            event_id=f"event_llm_{document_id}" if document_id else f"event_llm_{_slugify(event_name or raw.get('event_name', 'untitled'))}",
            event_name=event_name or raw.get("event_name", "LLM Extracted Event"),
            source_chunks=[c.chunk_id for c in chunks],
            parent_chunk_id=first_chunk.parent_chunk_id if first_chunk else "",
            parent_section_title=first_chunk.parent_section_title if first_chunk else "",
            parent_context_hash=first_chunk.parent_context_hash if first_chunk else "",
            source_text_quote=source_quote,
            quote_start_char=joined.find(source_quote) if source_quote else -1,
            quote_end_char=joined.find(source_quote) + len(source_quote) if source_quote and source_quote in joined else -1,
            actors=raw.get("actors", []),
            assets=raw.get("assets", []),
            triggers=raw.get("triggers", []),
            anchors=raw.get("anchors", []),
            liquidity_paths=raw.get("liquidity_paths", []),
            visibility_shift=raw.get("visibility_shift", ""),
            policy_response=raw.get("policy_response", []),
            market_impact=raw.get("market_impact", []),
            evidence_quotes=grounded_quotes,
            variable_mapping=variable_mapping,
            confidence={
                "entity_extraction": 0.6,
                "event_extraction": 0.55,
                "variable_mapping": 0.5,
                "quote_grounding": 0.7 if len(grounded_quotes) >= 2 else 0.5,
            },
            status="candidate",
            extraction_notes=raw.get("extraction_notes", "LLM-assisted extraction. Review required before admission."),
            extraction={
                "extractor_version": "llm_assisted_v0.1",
                "model": model or "default",
                "extraction_method": "llm_json_fallback",
            },
        )
        return card
    except Exception as exc:  # noqa: BLE001 - optional backend remains candidate-only
        logger.warning(
            "LLM extraction response validation failed: %s",
            type(exc).__name__,
        )
        return None


def _slugify(value: str) -> str:
    value = value.lower().replace(" ", "_")
    return re.sub(r"[^a-z0-9_]", "", value)[:80]
