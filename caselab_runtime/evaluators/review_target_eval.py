"""Evaluate structured outputs against Review-Target minimums."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

REQUIRED_TRADE_FIELDS = {
    "ticker",
    "agent",
    "signal",
    "confidence",
    "horizon",
    "data_quality",
    "review_status",
}


def _broken_wiki_links(text: str) -> list[str]:
    return re.findall(r"\[\[([^\]]+)\]\]", text)


def evaluate_trade_idea(payload: dict[str, Any], body: str = "") -> dict[str, Any]:
    issues: list[str] = []
    for field in REQUIRED_TRADE_FIELDS:
        if field not in payload or payload.get(field) in (None, ""):
            issues.append(f"missing_field:{field}")
    evidence = payload.get("evidence") or []
    if payload.get("signal") in {"bullish", "bearish"} and not evidence:
        issues.append("missing_evidence_for_directional_signal")
    if not payload.get("risk_flags") and payload.get("signal") in {"bullish", "bearish"}:
        issues.append("missing_risk_flags")
    if payload.get("review_status") not in {
        "needs_review",
        "accepted",
        "rejected",
        "needs_more_data",
    }:
        issues.append("invalid_review_status")
    return {
        "ok": not issues,
        "issues": issues,
        "wiki_links": _broken_wiki_links(body),
    }


def evaluate_context_packet(packet: dict[str, Any]) -> dict[str, Any]:
    issues: list[str] = []
    ctx = packet.get("context_packet") or packet
    meaning = ctx.get("contextual_meaning") or {}
    for field in ("deeper_structure", "next_checks"):
        if not meaning.get(field):
            issues.append(f"missing_context_field:{field}")
    if not ctx.get("matched_rules"):
        issues.append("no_matched_rules")
    if ctx.get("confidence") == "low" and not meaning.get("next_checks"):
        issues.append("low_confidence_without_next_checks")
    return {"ok": not issues, "issues": issues}


def evaluate_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {"ok": False, "issues": ["missing_frontmatter"], "path": str(path)}
    match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    body = text[match.end() :] if match else text
    import yaml

    payload = yaml.safe_load(match.group(1)) if match else {}
    note_type = payload.get("type")
    if note_type == "trade_idea":
        result = evaluate_trade_idea(payload, body)
    else:
        result = {"ok": True, "issues": [], "note": "no_evaluator_for_type"}
    result["path"] = str(path)
    result["type"] = note_type
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Review-Target evaluator for structured outputs.")
    parser.add_argument("path", help="File or directory to evaluate")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    target = Path(args.path)
    results: list[dict[str, Any]] = []
    paths = [target] if target.is_file() else sorted(target.rglob("*.md"))
    for path in paths:
        if path.suffix != ".md":
            continue
        results.append(evaluate_file(path))
    summary = {
        "checked": len(results),
        "failed": sum(1 for r in results if not r.get("ok")),
        "results": results,
    }
    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return
    print(f"Checked: {summary['checked']}, failed: {summary['failed']}")
    for result in results:
        if not result.get("ok"):
            print(f"FAIL {result['path']}: {', '.join(result.get('issues', []))}")


if __name__ == "__main__":
    main()
