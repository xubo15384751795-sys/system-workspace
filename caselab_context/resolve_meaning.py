"""Resolve contextual meaning from actor, action, and regime."""
from __future__ import annotations

import argparse
import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from caselab_context.load_context import (
    default_regime,
    load_entity_dna,
    load_resolver_rules,
)
from caselab_context.regime_from_indicators import infer_regime_from_indicators
from caselab_context.retrieve_context import merge_similar_into_packet

FEEDBACK_LOG = Path(__file__).resolve().parent / "feedback_log.jsonl"


def _normalize(value: str) -> str:
    return re.sub(r"[\s_-]+", "_", value.strip().lower())


def _actor_names(rule: dict[str, Any]) -> set[str]:
    names = {_normalize(rule.get("actor", ""))}
    for alias in rule.get("actor_aliases") or []:
        names.add(_normalize(str(alias)))
    names.discard("")
    return names


def _regime_match(rule_regime: dict[str, Any], regime: dict[str, str]) -> bool:
    if not rule_regime:
        return True
    for axis, allowed in rule_regime.items():
        current = regime.get(axis)
        if current is None:
            return False
        allowed_values = [_normalize(str(v)) for v in allowed]
        if _normalize(current) not in allowed_values:
            return False
    return True


def _verb_match(rule_verbs: list[str], verb: str) -> bool:
    normalized = _normalize(verb)
    for item in rule_verbs:
        if item == "*":
            return True
        if _normalize(str(item)) == normalized:
            return True
    return False


def _object_match(rule_objects: list[str], obj: str) -> bool:
    normalized = _normalize(obj)
    for item in rule_objects:
        if item == "*":
            return True
        token = _normalize(str(item))
        if token in normalized or normalized in token:
            return True
    return False


def _specificity(rule: dict[str, Any]) -> int:
    score = 0
    verbs = rule.get("verbs") or []
    objects = rule.get("objects") or []
    regime = rule.get("regime") or {}
    if verbs and verbs != ["*"]:
        score += 2
    if objects and objects != ["*"]:
        score += 2
    score += len(regime)
    return score


def match_rules(
    actor: str,
    verb: str,
    obj: str,
    regime: dict[str, str],
    rules: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    actor_key = _normalize(actor)
    matched: list[dict[str, Any]] = []
    for rule in rules:
        if actor_key not in _actor_names(rule):
            continue
        if not _verb_match(rule.get("verbs") or [], verb):
            continue
        if not _object_match(rule.get("objects") or [], obj):
            continue
        if not _regime_match(rule.get("regime") or {}, regime):
            continue
        matched.append(rule)
    matched.sort(key=_specificity, reverse=True)
    return matched


def _is_default_rule(rule: dict[str, Any]) -> bool:
    rule_id = str(rule.get("id", ""))
    return "default" in rule_id


def build_context_packet(
    actor: str,
    verb: str,
    obj: str,
    regime: dict[str, str] | None = None,
    *,
    use_indicator_regime: bool = False,
    min_quality: str | None = None,
) -> dict[str, Any]:
    regime_meta: dict[str, Any] | None = None
    if use_indicator_regime:
        regime_meta = infer_regime_from_indicators()
        regime = regime_meta["regime"]
    else:
        regime = regime or default_regime()
    entity = load_entity_dna(actor)
    rules = load_resolver_rules()
    matched = match_rules(actor, verb, obj, regime, rules)
    if len(matched) > 1:
        matched = [rule for rule in matched if not _is_default_rule(rule)]
    primary = matched[0] if matched else None
    meaning = (primary or {}).get("meaning", {})
    packet = {
        "context_packet": {
            "actor": entity.get("entity", actor),
            "entity_dna": entity.get("context_layer") or {},
            "regime": regime,
            "action": {
                "verb": verb,
                "object": obj,
            },
            "contextual_meaning": meaning,
            "confidence": meaning.get("confidence", "low"),
            "matched_rules": [rule.get("id") for rule in matched if rule.get("id")],
            "entity_source": entity.get("source_path"),
        }
    }
    if regime_meta:
        packet["context_packet"]["regime_source"] = regime_meta.get("source")
        packet["context_packet"]["regime_evidence"] = regime_meta.get("evidence")
        packet["context_packet"]["regime_as_of"] = regime_meta.get("as_of")
        packet["context_packet"]["indicator_snapshot"] = regime_meta.get("indicator_snapshot")
    query = f"{actor} {verb} {obj}"
    return merge_similar_into_packet(packet, query, min_quality=min_quality)


def append_feedback_log(packet: dict[str, Any], review_status: str = "needs_review") -> str:
    ctx = packet["context_packet"]
    feedback_id = f"ctx-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}"
    entry = {
        "feedback_id": feedback_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "input": {
            "actor": ctx.get("actor"),
            "verb": ctx["action"]["verb"],
            "object": ctx["action"]["object"],
            "regime": ctx.get("regime"),
        },
        "matched_rules": ctx.get("matched_rules"),
        "contextual_meaning": ctx.get("contextual_meaning"),
        "review_status": review_status,
        "review_notes": "",
        "failure_reason": "",
    }
    FEEDBACK_LOG.parent.mkdir(parents=True, exist_ok=True)
    with FEEDBACK_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return feedback_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve CaseLab contextual meaning.")
    parser.add_argument("--actor", required=True)
    parser.add_argument("--verb", required=True)
    parser.add_argument("--object", required=True)
    parser.add_argument("--liquidity")
    parser.add_argument("--rates")
    parser.add_argument("--credit")
    parser.add_argument("--regulation")
    parser.add_argument("--market-mood")
    parser.add_argument("--technology-cycle")
    parser.add_argument("--log", action="store_true", help="Append result to feedback_log.jsonl")
    parser.add_argument("--json", action="store_true", help="Print JSON only")
    args = parser.parse_args()

    regime = default_regime()
    overrides = {
        "liquidity": args.liquidity,
        "rates": args.rates,
        "credit": args.credit,
        "regulation": args.regulation,
        "market_mood": args.market_mood,
        "technology_cycle": args.technology_cycle,
    }
    for key, value in overrides.items():
        if value:
            regime[key] = value

    packet = build_context_packet(args.actor, args.verb, args.object, regime)
    if args.log:
        feedback_id = append_feedback_log(packet)
        packet["feedback_id"] = feedback_id

    if args.json:
        print(json.dumps(packet, indent=2, ensure_ascii=False))
        return

    ctx = packet["context_packet"]
    meaning = ctx.get("contextual_meaning") or {}
    print(f"Actor: {ctx.get('actor')}")
    print(f"Matched rules: {', '.join(ctx.get('matched_rules') or []) or 'none'}")
    print(f"Surface: {meaning.get('surface_action', '')}")
    print(f"Deeper: {meaning.get('deeper_structure', '')}")
    print(f"Confidence: {ctx.get('confidence', '')}")
    if packet.get("feedback_id"):
        print(f"Feedback ID: {packet['feedback_id']}")


if __name__ == "__main__":
    main()
