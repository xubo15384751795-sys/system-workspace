"""Build machine-readable agent policy from Paper Agent Rules."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml

from caselab_context.paper_paths import paper_root

PAPER_ROOT = paper_root()
AGENT_RULES = PAPER_ROOT / "90_Admin/Agent Rules.md"
REVIEW_TARGET = PAPER_ROOT / "90_Admin/Review-Target.md"
OUTPUT = Path(__file__).resolve().parents[1] / "policies" / "agent_policy.yml"


def _extract_bullets(text: str) -> list[str]:
    bullets = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("- "):
            bullets.append(line[2:].strip())
    return bullets


def build_policy() -> dict:
    rules_text = AGENT_RULES.read_text(encoding="utf-8") if AGENT_RULES.exists() else ""
    review_text = REVIEW_TARGET.read_text(encoding="utf-8") if REVIEW_TARGET.exists() else ""
    core_section = ""
    match = re.search(r"## 核心原则\n(.*?)(?:\n## |\Z)", rules_text, re.DOTALL)
    if match:
        core_section = match.group(1)
    return {
        "version": 2,
        "source_files": [str(AGENT_RULES), str(REVIEW_TARGET)],
        "core_principles": _extract_bullets(core_section)[:10],
        "review_standards": _extract_bullets(review_text)[:12],
        "rules": [
            {"id": "core_is_status_not_directory", "enforce": "use_yaml_status_fields"},
            {"id": "no_trade_without_evidence", "enforce": "directional_signal_requires_evidence"},
            {"id": "generated_needs_review", "enforce": "default_review_status_needs_review"},
            {"id": "context_before_trade_idea", "enforce": "attach_context_packet_when_entity_known"},
            {"id": "cross_layer_links_required", "enforce": "note_must_link_adjacent_layers"},
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build agent policy from Paper rules.")
    parser.add_argument("--print", action="store_true")
    args = parser.parse_args()
    policy = build_policy()
    OUTPUT.write_text(yaml.safe_dump(policy, allow_unicode=True, sort_keys=False), encoding="utf-8")
    if args.print:
        print(OUTPUT.read_text(encoding="utf-8"))
        return
    print(f"Wrote policy -> {OUTPUT}")


if __name__ == "__main__":
    main()
