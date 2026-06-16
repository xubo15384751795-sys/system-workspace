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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
HORIZON_OUTPUT_DIR = ROOT.parent / "Horizon" / "Output"
OUTPUT_DIR = ROOT / "Data" / "horizon_events"


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    items = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def read_horizon_events() -> list[dict[str, Any]]:
    """Read events from Horizon output."""
    events = []

    # Check for Horizon's event output
    horizon_event_file = HORIZON_OUTPUT_DIR / "events.jsonl"
    if horizon_event_file.exists():
        events.extend(load_jsonl(horizon_event_file))

    # Check for Horizon's news output
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
                "published_at": item.get("published_at", datetime.now(UTC).isoformat()),
                "ai_score": item.get("ai_score", 0.5),
                "tags": item.get("tags", []),
                "related_assets": item.get("related_assets", []),
                "related_entities": item.get("related_entities", []),
                "possible_mechanisms": item.get("possible_mechanisms", []),
                "source_run_id": item.get("source_run_id", ""),
            })

    return events


def generate_sample_events() -> list[dict[str, Any]]:
    """Generate sample events for testing."""
    now = datetime.now(UTC)

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
        event_tags = set(t.lower() for t in event.get("tags", []))
        event_entities = set(e.lower() for e in event.get("related_entities", []))
        event_assets = set(a.lower() for a in event.get("related_assets", []))
        event_title = event.get("title", "").lower()
        event_summary = event.get("summary", "").lower()
        event_text = event_title + " " + event_summary

        event_matches = []
        for mechanism in mechanisms:
            mechanism_id = mechanism.get("mechanism_id", "")
            mechanism_name = mechanism.get("name", "").lower()
            mechanism_claim = mechanism.get("causal_claim", "").lower()
            mechanism_signals = set(s.lower() for s in mechanism.get("observable_signals", []))

            match_reasons = []
            source_fields = []
            score = 0.0

            # Direct mechanism match (high weight)
            if mechanism_id in event_mechanisms:
                match_reasons.append("direct_mechanism_match")
                source_fields.append("possible_mechanisms")
                score += 0.5

            # Tag overlap (medium weight)
            mechanism_tags = set(mechanism_claim.split())
            tag_overlap = event_tags.intersection(mechanism_tags)
            if tag_overlap:
                match_reasons.append(f"tag_overlap: {', '.join(tag_overlap)}")
                source_fields.append("tags")
                score += 0.2

            # Entity overlap (medium weight)
            if event_entities and mechanism_name:
                entity_overlap = event_entities.intersection(set(mechanism_name.split()))
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

            # Text similarity (low weight, require more keywords)
            text_keywords = set(event_text.split())
            mechanism_keywords = set(mechanism_claim.split())
            keyword_overlap = text_keywords.intersection(mechanism_keywords)
            if len(keyword_overlap) >= 3:
                match_reasons.append(f"text_similarity: {len(keyword_overlap)} keywords")
                source_fields.append("title/summary")
                score += 0.1

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
            if score >= 0.2 and match_reasons:
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
    now = datetime.now(UTC)
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
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

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
    digest_path.write_text(json.dumps(digest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


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
        print("No events found. Use --sample to generate sample events.")
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
