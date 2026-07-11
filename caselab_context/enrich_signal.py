"""Map trade signals to Context Layer packets via world_model.query()."""
from __future__ import annotations

from typing import Any

from caselab_context.world_model import query

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

    response = query(
        mapping["actor"],
        mapping["verb"],
        mapping["object"],
        use_indicator_regime=True,
        evaluate_state=True,
        min_quality="useful",
        rematch_on_transition=True,
    )
    payload = response.to_dict()
    if signal:
        payload["agent_signal"] = {
            "ticker": ticker.upper(),
            "signal": signal.get("signal"),
            "confidence": signal.get("confidence"),
        }
    return payload


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
    ]

    regime = ctx.get("regime") or {}
    if regime:
        lines += [
            "### Regime",
            "",
            f"- liquidity: {regime.get('liquidity', 'n/a')}",
            f"- credit: {regime.get('credit', 'n/a')}",
            f"- technology_cycle: {regime.get('technology_cycle', 'n/a')}",
            "",
        ]

    world_state = packet.get("world_state") or ctx.get("world_state")
    if world_state and world_state.get("machines"):
        lines += ["### World State", ""]
        for machine in world_state["machines"]:
            lines.append(
                f"- **{machine.get('canonical_name')}**: {machine.get('current_state')}"
            )
            variables = machine.get("variables") or {}
            if variables:
                var_text = ", ".join(f"{k}={v}" for k, v in variables.items())
                lines.append(f"  - variables: {var_text}")
            if machine.get("transition"):
                tr = machine["transition"]
                lines.append(f"  - transition: {tr.get('from')} → {tr.get('to')}")
        lines.append("")

    if ctx.get("state_transitions"):
        lines += ["### State Transitions", ""]
        for tr in ctx["state_transitions"]:
            lines.append(
                f"- {tr.get('canonical_name')}: {tr.get('from')} → {tr.get('to')}"
            )
        prior_rules = ctx.get("matched_rules_prior") or []
        if prior_rules:
            lines.append(f"- prior matched rules: {', '.join(prior_rules)}")
        if ctx.get("resolver_rematched_on_transition"):
            lines.append("- resolver rules changed after transition")
        lines.append("")

    lines += [
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
