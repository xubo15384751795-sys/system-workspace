#!/usr/bin/env python3
"""Horizon Event Adapter — read and process events from Horizon.

This script reads events from Horizon's output and converts them
to structured events for System consumption.

Usage:
    python3 scripts/horizon_event_adapter.py
    python3 scripts/horizon_event_adapter.py --json
    python3 scripts/horizon_event_adapter.py --sample  # Generate sample events

Output:
    Data/horizon_events/events.jsonl
    Data/horizon_events/daily_digest.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import timedelta
from pathlib import Path
from typing import Any

from _runtime_io import ROOT, ensure_dir, load_json, load_jsonl, utc_now, write_json

HORIZON_ROOT = Path(os.environ.get("HORIZON_ROOT", str(ROOT.parent / "Horizon")))
HORIZON_OUTPUT_DIR = HORIZON_ROOT / "Output"
OUTPUT_DIR = ROOT / "Data" / "horizon_events"

_SUMMARY_HEADING = re.compile(
    r"^###\s+\[([^\]]+)\]\(([^)]+)\).*$",
    re.MULTILINE,
)


def read_horizon_summary_events() -> list[dict[str, Any]]:
    """Parse structured events from latest Horizon daily summary markdown."""
    summaries_dir = HORIZON_ROOT / "data" / "summaries"
    if not summaries_dir.exists():
        return []

    candidates = sorted(summaries_dir.glob("horizon-*-en.md"))
    if not candidates:
        return []

    latest = candidates[-1]
    text = latest.read_text(encoding="utf-8")
    date_part = latest.stem.replace("horizon-", "").replace("-en", "")
    events: list[dict[str, Any]] = []

    for index, match in enumerate(_SUMMARY_HEADING.finditer(text), start=1):
        title, url = match.group(1), match.group(2)
        block = text[match.end() : match.end() + 800]
        score_match = re.search(r"(\d+(?:\.\d+)?)/10", block)
        ai_score = float(score_match.group(1)) / 10.0 if score_match else 0.5
        summary_lines = [
            line.strip()
            for line in block.splitlines()
            if line.strip() and not line.startswith("#") and not line.startswith("|")
        ]
        summary = summary_lines[0][:500] if summary_lines else title
        events.append(
            {
                "event_id": f"horizon_summary_{date_part}_{index}",
                "title": title,
                "summary": summary,
                "source_type": "horizon_summary",
                "url": url,
                "published_at": f"{date_part}T12:00:00Z",
                "ai_score": ai_score,
                "tags": ["horizon", "summary"],
                "related_assets": [],
                "related_entities": [],
                "possible_mechanisms": [],
                "source_run_id": latest.name,
            }
        )
    return events


def read_horizon_events() -> list[dict[str, Any]]:
    """Read events from Horizon output and summaries."""
    events: list[dict[str, Any]] = []

    horizon_event_file = HORIZON_OUTPUT_DIR / "events.jsonl"
    if horizon_event_file.exists():
        events.extend(load_jsonl(horizon_event_file))

    horizon_news_file = HORIZON_OUTPUT_DIR / "news.jsonl"
    if horizon_news_file.exists():
        news_items = load_jsonl(horizon_news_file)
        for item in news_items:
            events.append({
                "event_id": item.get("id", f"news_{item.get('published_at', '')}"),
                "title": item.get("title", ""),
                "summary": item.get("summary", item.get("description", "")),
                "source_type": "news",
                "url": item.get("url", ""),
                "published_at": item.get("published_at", utc_now().isoformat()),
                "ai_score": item.get("ai_score", 0.5),
                "tags": item.get("tags", []),
                "related_assets": item.get("related_assets", []),
                "related_entities": item.get("related_entities", []),
                "possible_mechanisms": item.get("possible_mechanisms", []),
                "source_run_id": item.get("source_run_id", ""),
            })

    if not events:
        events.extend(read_horizon_summary_events())

    return events


def generate_sample_events() -> list[dict[str, Any]]:
    """Generate sample events for testing."""
    now = utc_now()

    return [
        {
            "event_id": "sample_001",
            "title": "Fed signals potential rate cut in September",
            "summary": "Federal Reserve officials indicated openness to rate cuts if inflation continues to moderate.",
            "source_type": "news",
            "url": "https://example.com/fed-rate-cut",
            "published_at": (now - timedelta(hours=2)).isoformat(),
            "ai_score": 0.85,
            "tags": ["fed", "rates", "monetary_policy"],
            "related_assets": ["SPY", "TLT", "HYG"],
            "related_entities": ["Federal Reserve"],
            "possible_mechanisms": ["rate_cut_dovish", "liquidity_expansion"],
            "source_run_id": "sample_run",
        },
        {
            "event_id": "sample_002",
            "title": "China property developer defaults on dollar bonds",
            "summary": "Major Chinese property developer missed payment on offshore dollar bonds, raising contagion fears.",
            "source_type": "news",
            "url": "https://example.com/china-default",
            "published_at": (now - timedelta(hours=4)).isoformat(),
            "ai_score": 0.72,
            "tags": ["china", "property", "credit", "default"],
            "related_assets": ["HYG", "KRE", "XLF"],
            "related_entities": ["China Property Developer"],
            "possible_mechanisms": ["credit_contagion", "risk_off"],
            "source_run_id": "sample_run",
        },
        {
            "event_id": "sample_003",
            "title": "AI chip shortage intensifies",
            "summary": "New report indicates AI chip supply constraints worsening, affecting major tech companies.",
            "source_type": "news",
            "url": "https://example.com/ai-chip-shortage",
            "published_at": (now - timedelta(hours=6)).isoformat(),
            "ai_score": 0.68,
            "tags": ["ai", "semiconductor", "supply_chain"],
            "related_assets": ["SMH", "NVDA", "AMD"],
            "related_entities": ["NVIDIA", "AMD", "TSMC"],
            "possible_mechanisms": ["supply_chain_bottleneck", "ai_capex_cycle"],
            "source_run_id": "sample_run",
        },
    ]


_STOP_WORDS = frozenset(
    "the a an is are was were be been being have has had do does did "
    "will would shall should may might can could of in to for on with at by from "
    "as into through during before after above below between out off over under "
    "and or but if not no nor so yet both either neither each every any all "
    "this that these those it its he she they we you i my our their his her".split()
)


def _extract_meaningful_tokens(text: str) -> set[str]:
    """Extract meaningful tokens from text, filtering stop words and short words."""
    return {w for w in text.lower().split() if len(w) > 2 and w not in _STOP_WORDS}


def _derive_event_tags(event: dict[str, Any]) -> set[str]:
    """Derive meaningful tags from event content when structured tags are generic."""
    tags = set(t.lower() for t in event.get("tags", []))
    # If tags are only generic ["horizon", "summary"], extract from content
    generic = {"horizon", "summary", "news", "update"}
    if tags <= generic:
        title = event.get("title", "").lower()
        summary = event.get("summary", "").lower()
        text = title + " " + summary
        # Extract domain-relevant tokens
        domain_tokens = _extract_meaningful_tokens(text)
        tags = tags | domain_tokens
    return tags


def _derive_event_entities(event: dict[str, Any]) -> set[str]:
    """Derive entity names from event title when structured entities are empty."""
    entities = set(e.lower() for e in event.get("related_entities", []))
    if not entities:
        title = event.get("title", "")
        # Extract capitalized sequences as potential entity names
        caps = re.findall(r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*", title)
        for cap in caps:
            entities.add(cap.lower())
    return entities


def match_events_to_mechanisms(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Match events to Paper mechanisms using multiple criteria with noise reduction."""
    # Load Paper mechanisms, variables, and indicators
    mechanisms = load_jsonl(ROOT / "Data" / "paper_world_model" / "mechanisms.jsonl")
    variables = load_jsonl(ROOT / "Data" / "paper_world_model" / "variables.jsonl")
    indicators = load_jsonl(ROOT / "Data" / "paper_world_model" / "indicators.jsonl")

    # Build lookup sets for variables and indicators (longer names only to reduce noise)
    variable_names = {v.get("name", "").lower() for v in variables if v.get("name") and len(v.get("name", "")) > 4}
    indicator_names = {i.get("name", "").lower() for i in indicators if i.get("name") and len(i.get("name", "")) > 4}

    all_matches = []
    for event in events:
        event_mechanisms = set(event.get("possible_mechanisms", []))
        event_tags = _derive_event_tags(event)
        event_entities = _derive_event_entities(event)
        event_assets = set(a.lower() for a in event.get("related_assets", []))
        event_title = event.get("title", "").lower()
        event_summary = event.get("summary", "").lower()
        event_text = event_title + " " + event_summary

        event_matches = []
        for mechanism in mechanisms:
            mechanism_id = mechanism.get("mechanism_id", "")
            mechanism_name = mechanism.get("name", "")
            mechanism_name_lower = mechanism_name.lower()
            mechanism_claim = mechanism.get("causal_claim", "").lower()
            mechanism_desc = mechanism.get("description", "").lower()
            mechanism_signals = set(s.lower() for s in mechanism.get("observable_signals", []))

            match_reasons = []
            source_fields = []
            score = 0.0

            # Direct mechanism match (high weight)
            if mechanism_id in event_mechanisms:
                match_reasons.append("direct_mechanism_match")
                source_fields.append("possible_mechanisms")
                score += 0.5

            # Name-in-text match: mechanism name appears in event text (high weight)
            if mechanism_name_lower and len(mechanism_name_lower) > 3:
                # Exact name match
                if mechanism_name_lower in event_text:
                    match_reasons.append(f"name_in_text: {mechanism_name}")
                    source_fields.append("title/summary")
                    score += 0.4
                else:
                    # Partial name match: all words of mechanism name present
                    name_words = set(mechanism_name_lower.split())
                    meaningful_name_words = {w for w in name_words if w not in _STOP_WORDS}
                    if meaningful_name_words and meaningful_name_words.issubset(
                        set(event_text.split())
                    ):
                        match_reasons.append(f"partial_name_match: {mechanism_name}")
                        source_fields.append("title/summary")
                        score += 0.3

            # Tag overlap (medium weight)
            mechanism_tags = _extract_meaningful_tokens(mechanism_claim or mechanism_desc)
            tag_overlap = event_tags.intersection(mechanism_tags)
            if tag_overlap:
                match_reasons.append(f"tag_overlap: {', '.join(sorted(tag_overlap)[:5])}")
                source_fields.append("tags")
                score += 0.2

            # Entity overlap (medium weight) — require meaningful words (>3 chars)
            if event_entities and mechanism_name_lower:
                name_words = {w for w in mechanism_name_lower.split() if len(w) > 3}
                entity_overlap = event_entities.intersection(name_words)
                if entity_overlap:
                    match_reasons.append(f"entity_overlap: {', '.join(entity_overlap)}")
                    source_fields.append("related_entities")
                    score += 0.2

            # Asset overlap (medium weight)
            if event_assets and mechanism_signals:
                asset_overlap = event_assets.intersection(mechanism_signals)
                if asset_overlap:
                    match_reasons.append(f"asset_overlap: {', '.join(asset_overlap)}")
                    source_fields.append("related_assets")
                    score += 0.2

            # Text similarity (low weight) — use claim OR description, lowered threshold
            text_keywords = _extract_meaningful_tokens(event_text)
            mechanism_keywords = _extract_meaningful_tokens(mechanism_claim or mechanism_desc)
            keyword_overlap = text_keywords.intersection(mechanism_keywords)
            if len(keyword_overlap) >= 2:
                match_reasons.append(f"text_similarity: {len(keyword_overlap)} keywords")
                source_fields.append("title/summary")
                score += 0.15

            # Variable/indicator name matching (low weight, require exact match)
            for var_name in variable_names:
                if var_name in event_text and len(var_name) > 5:
                    match_reasons.append(f"variable_match: {var_name}")
                    source_fields.append("variables")
                    score += 0.1
                    break

            for ind_name in indicator_names:
                if ind_name in event_text and len(ind_name) > 5:
                    match_reasons.append(f"indicator_match: {ind_name}")
                    source_fields.append("indicators")
                    score += 0.1
                    break

            # Only add match if score is above threshold
            if score >= 0.15 and match_reasons:
                # Determine role based on score
                if score >= 0.5:
                    role = "trigger"
                    confidence = "high"
                elif score >= 0.3:
                    role = "support"
                    confidence = "medium"
                else:
                    role = "background"
                    confidence = "low"

                event_matches.append({
                    "event_id": event.get("event_id"),
                    "mechanism_id": mechanism_id,
                    "score": round(score, 2),
                    "confidence": confidence,
                    "role": role,
                    "match_reasons": match_reasons,
                    "source_fields": list(set(source_fields)),
                })

        # Keep only top 3 matches per event
        event_matches.sort(key=lambda x: x["score"], reverse=True)
        all_matches.extend(event_matches[:3])

    return all_matches


def build_daily_digest(events: list[dict[str, Any]], matches: list[dict[str, Any]]) -> dict[str, Any]:
    """Build daily digest of events."""
    now = utc_now()
    date_str = now.strftime("%Y-%m-%d")

    # Group by source type
    by_source: dict[str, int] = {}
    for event in events:
        source_type = event.get("source_type", "unknown")
        by_source[source_type] = by_source.get(source_type, 0) + 1

    # Get top events by AI score
    top_events = sorted(events, key=lambda e: e.get("ai_score", 0), reverse=True)[:5]

    # Get mechanism matches
    mechanism_matches: dict[str, int] = {}
    for match in matches:
        mechanism_id = match.get("mechanism_id", "unknown")
        mechanism_matches[mechanism_id] = mechanism_matches.get(mechanism_id, 0) + 1

    return {
        "date": date_str,
        "generated_at": now.isoformat(),
        "total_events": len(events),
        "by_source": by_source,
        "top_events": [
            {
                "event_id": e.get("event_id"),
                "title": e.get("title"),
                "ai_score": e.get("ai_score"),
                "source_type": e.get("source_type"),
            }
            for e in top_events
        ],
        "mechanism_matches": mechanism_matches,
        "total_matches": len(matches),
    }


def write_outputs(events: list[dict[str, Any]], matches: list[dict[str, Any]], digest: dict[str, Any]) -> None:
    """Write outputs to disk."""
    ensure_dir(OUTPUT_DIR)

    # Write events
    events_path = OUTPUT_DIR / "events.jsonl"
    with events_path.open("w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    # Write mechanism matches
    matches_path = OUTPUT_DIR / "event_mechanism_matches.jsonl"
    with matches_path.open("w", encoding="utf-8") as f:
        for match in matches:
            f.write(json.dumps(match, ensure_ascii=False) + "\n")

    # Write daily digest
    digest_path = OUTPUT_DIR / "daily_digest.json"
    write_json(digest_path, digest)


def main() -> None:
    parser = argparse.ArgumentParser(description="Horizon Event Adapter.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    parser.add_argument("--sample", action="store_true", help="Generate sample events.")
    args = parser.parse_args()

    # Read or generate events
    if args.sample:
        events = generate_sample_events()
    else:
        events = read_horizon_events()

    if not events:
        allow_sample = os.environ.get("HORIZON_ALLOW_SAMPLE", "").lower() in {"1", "true", "yes"}
        if allow_sample:
            events = generate_sample_events()
        else:
            print("No Horizon events found (checked Output/*.jsonl and data/summaries).")
            print("Run Horizon first, or pass --sample / set HORIZON_ALLOW_SAMPLE=1.")
            return

    # Match to mechanisms
    matches = match_events_to_mechanisms(events)

    # Build daily digest
    digest = build_daily_digest(events, matches)

    # Write outputs
    write_outputs(events, matches, digest)

    if args.json:
        print(json.dumps({"events": events, "matches": matches, "digest": digest}, indent=2, ensure_ascii=False))
    else:
        print(f"Horizon events: {len(events)}")
        print(f"Mechanism matches: {len(matches)}")
        print(f"Top events:")
        for e in digest.get("top_events", [])[:3]:
            print(f"  - {e.get('title')} (score={e.get('ai_score')})")


if __name__ == "__main__":
    main()
