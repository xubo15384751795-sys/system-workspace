"""Map trade signals to Context Layer packets."""
from __future__ import annotations

from typing import Any

from caselab_context.load_context import default_regime
from caselab_context.resolve_meaning import build_context_packet

TICKER_CONTEXT_MAP: dict[str, dict[str, str]] = {
    "NVDA": {
        "actor": "Nvidia",
        "verb": "raising_guidance",
        "object": "data_center",
    },
    "MSFT": {
        "actor": "OpenAI",
        "verb": "fundraising",
        "object": "compute",
    },
    "GOOGL": {
        "actor": "Nvidia",
        "verb": "expanding",
        "object": "ai_compute",
    },
    "META": {
        "actor": "Nvidia",
        "verb": "expanding",
        "object": "ai_compute",
    },
    "AMZN": {
        "actor": "Nvidia",
        "verb": "expanding",
        "object": "ai_compute",
    },
    "SPY": {
        "actor": "Federal Reserve",
        "verb": "tightening",
        "object": "federal_funds",
    },
    "TLT": {
        "actor": "Federal Reserve",
        "verb": "tightening",
        "object": "federal_funds",
    },
    "HYG": {
        "actor": "Federal Reserve",
        "verb": "tightening",
        "object": "federal_funds",
    },
    "XLF": {
        "actor": "JPMorgan Chase",
        "verb": "clearing",
        "object": "treasury",
    },
    "KRE": {
        "actor": "JPMorgan Chase",
        "verb": "acquiring",
        "object": "distressed_bank",
    },
}


def enrich_trade_signal(ticker: str, signal: dict[str, Any] | None = None) -> dict[str, Any]:
    mapping = TICKER_CONTEXT_MAP.get(ticker.upper())
    if not mapping:
        return {"context_packet": None, "reason": "no_ticker_mapping"}
    regime = default_regime()
    if signal:
        if signal.get("signal") == "bearish" and ticker in {"SPY", "TLT", "HYG"}:
            regime = {**regime, "rates": "rising", "market_mood": "risk_off", "credit": "fragile"}
        if signal.get("signal") == "bullish" and ticker in {"TLT"}:
            regime = {**regime, "rates": "falling", "market_mood": "risk_on"}
        if signal.get("signal") == "bullish" and ticker in {"NVDA", "GOOGL", "META", "AMZN"}:
            regime = {**regime, "technology_cycle": "scaling", "credit": "expanding"}
    return build_context_packet(
        mapping["actor"],
        mapping["verb"],
        mapping["object"],
        regime,
    )


def context_section_markdown(packet: dict[str, Any]) -> str:
    ctx = packet.get("context_packet")
    if not ctx:
        return ""
    meaning = ctx.get("contextual_meaning") or {}
    lines = [
        "## Context Layer",
        "",
        f"**Actor:** {ctx.get('actor')}",
        f"**Matched rules:** {', '.join(ctx.get('matched_rules') or [])}",
        f"**Deeper structure:** {meaning.get('deeper_structure', 'n/a')}",
        "",
        "### Risk Transfer",
        "",
    ]
    transfer = meaning.get("risk_transfer") or {}
    lines.append(f"- from: {transfer.get('from', 'unknown')}")
    lines.append(f"- to: {transfer.get('to', 'unknown')}")
    checks = meaning.get("next_checks") or []
    if checks:
        lines += ["", "### Next Checks", ""]
        for check in checks:
            lines.append(f"- {check}")
    lines.append("")
    return "\n".join(lines)
