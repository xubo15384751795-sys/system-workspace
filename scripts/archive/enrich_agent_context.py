"""Attach Context Layer sections to generated trade idea notes in Paper."""
from __future__ import annotations

import argparse
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from caselab_context.enrich_signal import context_section_markdown, enrich_trade_signal

PAPER_ROOT = Path("/Users/a1/Paper")
TRADE_IDEA_DIR = PAPER_ROOT / "05_Trade-Ideas" / "generated"


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    match = re.match(r"^---\n(.*?)\n---\n?", text, re.DOTALL)
    if not match:
        return {}, text
    meta = yaml.safe_load(match.group(1)) or {}
    body = text[match.end() :]
    return meta, body


def enrich_file(path: Path, dry_run: bool = False) -> bool:
    text = path.read_text(encoding="utf-8")
    if "## Context Layer" in text:
        return False
    meta, body = _parse_frontmatter(text)
    ticker = meta.get("ticker") or path.stem.split("-")[0]
    packet = enrich_trade_signal(
        ticker,
        {
            "signal": meta.get("signal"),
            "confidence": meta.get("confidence"),
        },
    )
    section = context_section_markdown(packet)
    if not section:
        return False
    ctx = packet["context_packet"]
    meta["context_rules"] = ctx.get("matched_rules")
    meta["context_confidence"] = ctx.get("confidence")
    new_text = "---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False) + "---\n" + body
    if "## Review Notes" in new_text:
        new_text = new_text.replace("## Review Notes", section + "## Review Notes", 1)
    else:
        new_text = new_text.rstrip() + "\n\n" + section
    if not dry_run:
        path.write_text(new_text, encoding="utf-8")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich Paper trade ideas with context packets.")
    parser.add_argument("--date", default=datetime.now(UTC).strftime("%Y-%m-%d"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not TRADE_IDEA_DIR.exists():
        print(f"Missing directory: {TRADE_IDEA_DIR}")
        return
    updated = 0
    for path in sorted(TRADE_IDEA_DIR.glob(f"*-{args.date}.md")):
        if enrich_file(path, dry_run=args.dry_run):
            updated += 1
            print(f"enriched: {path.name}")
    print(f"updated {updated} files")


if __name__ == "__main__":
    main()
