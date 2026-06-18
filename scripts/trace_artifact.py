#!/usr/bin/env python3
"""Trace a Paper world-model artifact to source note and downstream consumers.

Usage:
    python3 scripts/trace_artifact.py --mechanism MECH_ID
    python3 scripts/trace_artifact.py --case CASE_ID
    python3 scripts/trace_artifact.py --source-file 03_Mechanisms/foo.md
    python3 scripts/trace_artifact.py --mechanism MECH_ID --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from _runtime_io import load_json, load_jsonl, load_yaml
from caselab_context.paper_paths import paper_root

PAPER_WORLD_MODEL_DIR = ROOT / "Data" / "paper_world_model"
MANIFEST_PATH = PAPER_WORLD_MODEL_DIR / "manifest.json"
OPERATOR_REGISTRY = ROOT / "governance" / "operator_registry.yaml"

CATEGORY_CONFIG = {
    "case": ("cases.jsonl", "case_id"),
    "mechanism": ("mechanisms.jsonl", "mechanism_id"),
    "variable": ("variables.jsonl", "variable_id"),
    "indicator": ("indicators.jsonl", "indicator_id"),
    "idea": ("trade_ideas.jsonl", "idea_id"),
}


def _find_by_id(category: str, record_id: str) -> dict[str, Any] | None:
    filename, id_field = CATEGORY_CONFIG[category]
    for row in load_jsonl(PAPER_WORLD_MODEL_DIR / filename):
        if str(row.get(id_field, "")) == record_id:
            return row
    return None


def _find_by_source_file(source_file: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    normalized = source_file.replace("\\", "/").lstrip("/")
    for category, (filename, id_field) in CATEGORY_CONFIG.items():
        for row in load_jsonl(PAPER_WORLD_MODEL_DIR / filename):
            row_source = str(row.get("source_file", "")).replace("\\", "/")
            if row_source == normalized or row_source.endswith(normalized):
                matches.append({"category": category, "id_field": id_field, "record": row})
    return matches


def _downstream_consumers() -> list[dict[str, Any]]:
    registry = load_yaml(OPERATOR_REGISTRY) or {}
    consumers: list[dict[str, Any]] = []
    for name, op in registry.get("operators", {}).items():
        inputs = op.get("inputs", [])
        joined = " ".join(str(item) for item in inputs).lower()
        if "paper" in joined or "paper_world_model" in joined:
            consumers.append(
                {
                    "operator": name,
                    "type": op.get("type"),
                    "inputs": inputs,
                    "outputs": op.get("outputs", []),
                    "claim_ceiling": op.get("claim_ceiling"),
                }
            )
    return consumers


def trace(
    *,
    category: str | None = None,
    record_id: str | None = None,
    source_file: str | None = None,
) -> dict[str, Any]:
    manifest = load_json(MANIFEST_PATH)
    paper_dir = paper_root()
    records: list[dict[str, Any]] = []

    if source_file:
        records = _find_by_source_file(source_file)
    elif category and record_id:
        row = _find_by_id(category, record_id)
        if row:
            id_field = CATEGORY_CONFIG[category][1]
            records = [{"category": category, "id_field": id_field, "record": row}]
    else:
        raise ValueError("Provide --source-file or both category flag and id")

    enriched: list[dict[str, Any]] = []
    for item in records:
        row = item["record"]
        rel_source = str(row.get("source_file", ""))
        paper_path = str(paper_dir / rel_source) if rel_source else None
        enriched.append(
            {
                "category": item["category"],
                "id": row.get(item["id_field"]),
                "review_status": row.get("review_status"),
                "source_file": rel_source,
                "paper_path": paper_path,
                "paper_exists": bool(paper_path and Path(paper_path).exists()),
                "extracted_at": row.get("extracted_at"),
            }
        )

    return {
        "manifest": manifest,
        "paper_root": str(paper_dir),
        "matches": enriched,
        "downstream_consumers": _downstream_consumers(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Trace Paper world-model artifact provenance.")
    parser.add_argument("--case", dest="case_id", help="Case ID to trace.")
    parser.add_argument("--mechanism", dest="mechanism_id", help="Mechanism ID to trace.")
    parser.add_argument("--variable", dest="variable_id", help="Variable ID to trace.")
    parser.add_argument("--indicator", dest="indicator_id", help="Indicator ID to trace.")
    parser.add_argument("--idea", dest="idea_id", help="Trade idea ID to trace.")
    parser.add_argument("--source-file", help="Relative Paper source path.")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    args = parser.parse_args()

    category = None
    record_id = None
    if args.case_id:
        category, record_id = "case", args.case_id
    elif args.mechanism_id:
        category, record_id = "mechanism", args.mechanism_id
    elif args.variable_id:
        category, record_id = "variable", args.variable_id
    elif args.indicator_id:
        category, record_id = "indicator", args.indicator_id
    elif args.idea_id:
        category, record_id = "idea", args.idea_id
    elif not args.source_file:
        parser.error("Provide an artifact id flag or --source-file")

    try:
        result = trace(category=category, record_id=record_id, source_file=args.source_file)
    except ValueError as exc:
        print(str(exc))
        sys.exit(1)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    manifest = result.get("manifest") or {}
    print("Paper World Model Trace")
    print("=" * 60)
    if manifest:
        print(f"Last sync: {manifest.get('synced_at', 'unknown')}")
        print(f"Paper root: {manifest.get('paper_root', result.get('paper_root'))}")
        print(f"Record counts: {manifest.get('record_counts', {})}")
    else:
        print("No manifest.json — run scripts/sync_paper_world_model.py first")

    matches = result.get("matches", [])
    if not matches:
        print("\nNo matching records found.")
        sys.exit(1)

    for match in matches:
        print(f"\n[{match['category']}] {match['id']}")
        print(f"  review_status: {match.get('review_status')}")
        print(f"  source_file: {match.get('source_file')}")
        print(f"  paper_path: {match.get('paper_path')}")
        print(f"  paper_exists: {match.get('paper_exists')}")
        print(f"  extracted_at: {match.get('extracted_at')}")

    print("\nDownstream consumers:")
    for consumer in result.get("downstream_consumers", []):
        outputs = ", ".join(consumer.get("outputs", []))
        print(f"  - {consumer['operator']} ({consumer.get('type')}): {outputs}")


if __name__ == "__main__":
    main()
