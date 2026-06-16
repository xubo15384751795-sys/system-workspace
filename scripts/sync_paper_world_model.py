#!/usr/bin/env python3
"""Sync Paper World Model — extract structured world model from Paper.

This script reads Paper knowledge base and extracts:
- Cases (from 01_Cases/)
- Mechanisms (from 03_Mechanisms/)
- Variables (from 08_Variables/)
- Indicators (from 10_Indicators/)
- Trade Ideas (from 05_Trade-Ideas/)

Each record preserves source_file for traceability.
Content with review_status != approved cannot enter strong judgments.

Usage:
    python3 scripts/sync_paper_world_model.py
    python3 scripts/sync_paper_world_model.py --json

Output:
    Data/paper_world_model/cases.jsonl
    Data/paper_world_model/mechanisms.jsonl
    Data/paper_world_model/variables.jsonl
    Data/paper_world_model/indicators.jsonl
    Data/paper_world_model/trade_ideas.jsonl
    Output/paper_world_model/sync_report.md
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PAPER_DIR = Path("/Users/a1/Paper")
OUTPUT_DIR = ROOT / "Data" / "paper_world_model"
REPORT_DIR = ROOT / "Output" / "paper_world_model"


def parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from markdown content."""
    if not content.startswith("---"):
        return {}, content

    try:
        # Find closing ---
        end_idx = content.index("---", 3)
        frontmatter_str = content[3:end_idx].strip()
        body = content[end_idx + 3:].strip()

        # Simple YAML parser (no dependency)
        frontmatter = {}
        current_key = None
        current_list = None

        for line in frontmatter_str.split("\n"):
            line = line.rstrip()
            if not line or line.startswith("#"):
                continue

            # List item
            if line.startswith("  - ") and current_key:
                if current_list is None:
                    current_list = []
                item = line[4:].strip().strip('"').strip("'")
                # Handle Obsidian links
                if item.startswith("[[") and item.endswith("]]"):
                    item = item[2:-2]
                current_list.append(item)
                continue

            # Save previous list
            if current_list is not None and current_key:
                frontmatter[current_key] = current_list
                current_list = None

            # Key-value pair
            if ": " in line:
                key, value = line.split(": ", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")

                # Handle list start
                if value == "":
                    current_key = key
                    current_list = None
                    continue

                # Handle Obsidian links
                if value.startswith("[[") and value.endswith("]]"):
                    value = value[2:-2]

                frontmatter[key] = value
                current_key = key
                current_list = None

        # Save last list
        if current_list is not None and current_key:
            frontmatter[current_key] = current_list

        return frontmatter, body

    except (ValueError, IndexError):
        return {}, content


def extract_case(file_path: Path, content: str) -> dict[str, Any] | None:
    """Extract case data from a case file."""
    frontmatter, body = parse_frontmatter(content)

    if frontmatter.get("type") != "case":
        return None

    case_id = file_path.stem
    mechanisms = frontmatter.get("mechanisms", [])
    if isinstance(mechanisms, str):
        mechanisms = [mechanisms]

    return {
        "case_id": case_id,
        "case_type": frontmatter.get("case_type", "unknown"),
        "status": frontmatter.get("status", "candidate"),
        "main_entity": frontmatter.get("main_entity", ""),
        "country": frontmatter.get("country", ""),
        "sector": frontmatter.get("sector", ""),
        "mechanism_ids": mechanisms,
        "trade_relevance": frontmatter.get("trade_relevance", "medium"),
        "tags": frontmatter.get("tags", []),
        "review_status": frontmatter.get("review_status", "needs_review"),
        "review_score": frontmatter.get("review_score"),
        "source_file": str(file_path.relative_to(PAPER_DIR)),
        "extracted_at": datetime.now(UTC).isoformat(),
    }


def extract_mechanism(file_path: Path, content: str) -> dict[str, Any] | None:
    """Extract mechanism data from a mechanism file."""
    frontmatter, body = parse_frontmatter(content)

    if frontmatter.get("type") != "mechanism":
        return None

    return {
        "mechanism_id": file_path.stem,
        "name": frontmatter.get("name", file_path.stem),
        "description": frontmatter.get("description", "")[:500],
        "causal_claim": frontmatter.get("causal_claim", ""),
        "observable_signals": frontmatter.get("observable_signals", []),
        "invalidation_conditions": frontmatter.get("invalidation_conditions", []),
        "related_cases": frontmatter.get("related_cases", []),
        "related_variables": frontmatter.get("related_variables", []),
        "confidence": frontmatter.get("confidence", "medium"),
        "review_status": frontmatter.get("review_status", "needs_review"),
        "source_file": str(file_path.relative_to(PAPER_DIR)),
        "extracted_at": datetime.now(UTC).isoformat(),
    }


def extract_variable(file_path: Path, content: str) -> dict[str, Any] | None:
    """Extract variable data from a variable file."""
    frontmatter, body = parse_frontmatter(content)

    if frontmatter.get("type") != "variable":
        return None

    return {
        "variable_id": file_path.stem,
        "name": frontmatter.get("name", file_path.stem),
        "description": frontmatter.get("description", "")[:500],
        "data_source": frontmatter.get("data_source", ""),
        "frequency": frontmatter.get("frequency", "unknown"),
        "related_mechanisms": frontmatter.get("related_mechanisms", []),
        "trade_implication": frontmatter.get("trade_implication", ""),
        "review_status": frontmatter.get("review_status", "needs_review"),
        "source_file": str(file_path.relative_to(PAPER_DIR)),
        "extracted_at": datetime.now(UTC).isoformat(),
    }


def extract_indicator(file_path: Path, content: str) -> dict[str, Any] | None:
    """Extract indicator data from an indicator file."""
    frontmatter, body = parse_frontmatter(content)

    if frontmatter.get("type") != "indicator":
        return None

    return {
        "indicator_id": file_path.stem,
        "name": frontmatter.get("name", file_path.stem),
        "description": frontmatter.get("description", "")[:500],
        "data_source": frontmatter.get("data_source", ""),
        "frequency": frontmatter.get("frequency", "unknown"),
        "related_variables": frontmatter.get("related_variables", []),
        "signal_interpretation": frontmatter.get("signal_interpretation", ""),
        "review_status": frontmatter.get("review_status", "needs_review"),
        "source_file": str(file_path.relative_to(PAPER_DIR)),
        "extracted_at": datetime.now(UTC).isoformat(),
    }


def extract_trade_idea(file_path: Path, content: str) -> dict[str, Any] | None:
    """Extract trade idea data from a trade idea file."""
    frontmatter, body = parse_frontmatter(content)

    # Trade ideas may not have explicit type field
    if frontmatter.get("type") not in ("trade_idea", "trade", None):
        return None

    return {
        "idea_id": file_path.stem,
        "name": frontmatter.get("name", file_path.stem),
        "description": frontmatter.get("description", "")[:500],
        "asset_class": frontmatter.get("asset_class", ""),
        "market_regime": frontmatter.get("market_regime", ""),
        "historical_period": frontmatter.get("historical_period", ""),
        "causal_claim": frontmatter.get("causal_claim", ""),
        "observable_signals": frontmatter.get("observable_signals", []),
        "invalidation_conditions": frontmatter.get("invalidation_conditions", []),
        "trade_implication": frontmatter.get("trade_implication", ""),
        "confidence": frontmatter.get("confidence", "medium"),
        "related_mechanisms": frontmatter.get("related_mechanisms", []),
        "related_variables": frontmatter.get("related_variables", []),
        "review_status": frontmatter.get("review_status", "needs_review"),
        "source_file": str(file_path.relative_to(PAPER_DIR)),
        "extracted_at": datetime.now(UTC).isoformat(),
    }


def scan_directory(dir_path: Path, extractor: Any) -> list[dict]:
    """Scan a directory and extract data from all markdown files."""
    results = []
    if not dir_path.exists():
        return results

    for file_path in sorted(dir_path.rglob("*.md")):
        try:
            content = file_path.read_text(encoding="utf-8")
            data = extractor(file_path, content)
            if data:
                results.append(data)
        except Exception as e:
            print(f"  Warning: Failed to process {file_path}: {e}")

    return results


def write_jsonl(data: list[dict], output_path: Path) -> None:
    """Write data to JSONL file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def build_sync_report(
    cases: list[dict],
    mechanisms: list[dict],
    variables: list[dict],
    indicators: list[dict],
    trade_ideas: list[dict],
) -> str:
    """Build sync report markdown."""
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    def count_by_status(items: list[dict]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in items:
            status = item.get("review_status", "unknown")
            if isinstance(status, list):
                status = status[0] if status else "unknown"
            counts[str(status)] = counts.get(str(status), 0) + 1
        return counts

    lines = [
        "# Paper World Model Sync Report",
        "",
        f"**Generated:** {now}",
        "",
        "## Summary",
        "",
        f"- Cases: {len(cases)}",
        f"- Mechanisms: {len(mechanisms)}",
        f"- Variables: {len(variables)}",
        f"- Indicators: {len(indicators)}",
        f"- Trade Ideas: {len(trade_ideas)}",
        "",
        "## Review Status",
        "",
        "| Category | Approved | Needs Review | Rejected |",
        "|---|---:|---:|---:|",
    ]

    for name, items in [("Cases", cases), ("Mechanisms", mechanisms), ("Variables", variables),
                         ("Indicators", indicators), ("Trade Ideas", trade_ideas)]:
        counts = count_by_status(items)
        lines.append(f"| {name} | {counts.get('approved', 0)} | {counts.get('needs_review', 0)} | {counts.get('rejected', 0)} |")

    lines += [
        "",
        "## Usage Rules",
        "",
        "- `review_status = approved` content can enter strong judgments",
        "- `review_status = needs_review` content can only enter background",
        "- `review_status = rejected` content cannot enter any judgment",
        "",
        "## Source Files",
        "",
    ]

    # List source files
    all_items = cases + mechanisms + variables + indicators + trade_ideas
    source_files = sorted(set(item.get("source_file", "") for item in all_items))
    for sf in source_files[:20]:
        lines.append(f"- `{sf}`")
    if len(source_files) > 20:
        lines.append(f"- ... and {len(source_files) - 20} more")

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Paper World Model.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    args = parser.parse_args()

    if not PAPER_DIR.exists():
        print(f"Paper directory not found: {PAPER_DIR}")
        return

    print("Scanning Paper knowledge base...")

    print("  Extracting cases...")
    cases = scan_directory(PAPER_DIR / "01_Cases", extract_case)
    print(f"    Found {len(cases)} cases")

    print("  Extracting mechanisms...")
    mechanisms = scan_directory(PAPER_DIR / "03_Mechanisms", extract_mechanism)
    print(f"    Found {len(mechanisms)} mechanisms")

    print("  Extracting variables...")
    variables = scan_directory(PAPER_DIR / "08_Variables", extract_variable)
    print(f"    Found {len(variables)} variables")

    print("  Extracting indicators...")
    indicators = scan_directory(PAPER_DIR / "10_Indicators", extract_indicator)
    print(f"    Found {len(indicators)} indicators")

    print("  Extracting trade ideas...")
    trade_ideas = scan_directory(PAPER_DIR / "05_Trade-Ideas", extract_trade_idea)
    print(f"    Found {len(trade_ideas)} trade ideas")

    # Write JSONL files
    print("\nWriting JSONL files...")
    write_jsonl(cases, OUTPUT_DIR / "cases.jsonl")
    write_jsonl(mechanisms, OUTPUT_DIR / "mechanisms.jsonl")
    write_jsonl(variables, OUTPUT_DIR / "variables.jsonl")
    write_jsonl(indicators, OUTPUT_DIR / "indicators.jsonl")
    write_jsonl(trade_ideas, OUTPUT_DIR / "trade_ideas.jsonl")

    # Write sync report
    print("Writing sync report...")
    report = build_sync_report(cases, mechanisms, variables, indicators, trade_ideas)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "sync_report.md").write_text(report, encoding="utf-8")

    if args.json:
        result = {
            "cases": len(cases),
            "mechanisms": len(mechanisms),
            "variables": len(variables),
            "indicators": len(indicators),
            "trade_ideas": len(trade_ideas),
        }
        print(json.dumps(result, indent=2))
    else:
        print(f"\n=== Sync Complete ===")
        print(f"Cases: {len(cases)}")
        print(f"Mechanisms: {len(mechanisms)}")
        print(f"Variables: {len(variables)}")
        print(f"Indicators: {len(indicators)}")
        print(f"Trade Ideas: {len(trade_ideas)}")


if __name__ == "__main__":
    main()
