"""Run Context Layer sample pack and seed feedback_log.jsonl."""
from __future__ import annotations

import argparse
import json

from caselab_context.resolve_meaning import append_feedback_log, build_context_packet

SAMPLES = [
    {
        "actor": "Goldman Sachs",
        "verb": "arrange_financing",
        "object": "ai_data_center",
        "regime": {"liquidity": "abundant", "credit": "expanding", "technology_cycle": "scaling"},
        "expected_rule": "gs_financing_ai_abundant",
        "review_status": "needs_review",
    },
    {
        "actor": "Goldman Sachs",
        "verb": "ipo",
        "object": "public_market",
        "regime": {"liquidity": "abundant"},
        "expected_rule": "gs_ipo_risk_transfer",
        "review_status": "accepted",
    },
    {
        "actor": "Goldman Sachs",
        "verb": "raising_capital",
        "object": "balance_sheet",
        "regime": {"liquidity": "stressed"},
        "expected_rule": "gs_capital_raise_stressed",
        "review_status": "needs_review",
    },
    {
        "actor": "Nvidia",
        "verb": "raising_guidance",
        "object": "data_center",
        "regime": {"technology_cycle": "scaling", "credit": "expanding"},
        "expected_rule": "nv_capex_scaling",
        "review_status": "needs_review",
    },
    {
        "actor": "OpenAI",
        "verb": "ipo",
        "object": "public_market",
        "regime": {"liquidity": "abundant", "technology_cycle": "scaling"},
        "expected_rule": "oai_ipo_preparation",
        "review_status": "needs_review",
    },
    {
        "actor": "Federal Reserve",
        "verb": "tightening",
        "object": "federal_funds",
        "regime": {"rates": "rising", "market_mood": "risk_off"},
        "expected_rule": "fed_rate_tightening",
        "review_status": "needs_review",
    },
    {
        "actor": "Federal Reserve",
        "verb": "injecting",
        "object": "liquidity",
        "regime": {"liquidity": "stressed", "market_mood": "crisis"},
        "expected_rule": "fed_liquidity_injection",
        "review_status": "needs_review",
    },
    {
        "actor": "JPMorgan Chase",
        "verb": "acquiring",
        "object": "distressed_bank",
        "regime": {"liquidity": "stressed", "market_mood": "crisis"},
        "expected_rule": "jpm_crisis_acquisition",
        "review_status": "needs_review",
    },
    {
        "actor": "Goldman Sachs",
        "verb": "arrange_financing",
        "object": "ai_data_center",
        "regime": {"liquidity": "tightening", "credit": "fragile"},
        "expected_rule": "gs_financing_ai_tight",
        "review_status": "needs_review",
    },
    {
        "actor": "Nvidia",
        "verb": "export_control",
        "object": "china",
        "regime": {"regulation": "tightening"},
        "expected_rule": "nv_export_restriction",
        "review_status": "needs_review",
    },
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Context Layer sample pack.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-log", action="store_true")
    args = parser.parse_args()

    results = []
    for sample in SAMPLES:
        packet = build_context_packet(
            sample["actor"],
            sample["verb"],
            sample["object"],
            sample["regime"],
        )
        matched = packet["context_packet"].get("matched_rules") or []
        ok = sample["expected_rule"] in matched
        feedback_id = None
        if not args.no_log:
            feedback_id = append_feedback_log(packet, review_status=sample["review_status"])
        results.append(
            {
                "sample": sample,
                "ok": ok,
                "matched_rules": matched,
                "feedback_id": feedback_id,
            }
        )

    summary = {
        "total": len(results),
        "passed": sum(1 for r in results if r["ok"]),
        "results": results,
    }
    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return

    print(f"Samples: {summary['total']}, passed: {summary['passed']}")
    for item in results:
        status = "PASS" if item["ok"] else "FAIL"
        sample = item["sample"]
        print(
            f"{status} {sample['actor']} {sample['verb']} {sample['object']} "
            f"-> {item['matched_rules']}"
        )


if __name__ == "__main__":
    main()
