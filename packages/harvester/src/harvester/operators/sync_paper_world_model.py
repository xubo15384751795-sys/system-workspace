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
    PAPER_ROOT=/path/to/Paper python3 scripts/sync_paper_world_model.py

Output:
    Data/paper_world_model/cases.jsonl
    Data/paper_world_model/mechanisms.jsonl
    Data/paper_world_model/variables.jsonl
    Data/paper_world_model/indicators.jsonl
    Data/paper_world_model/trade_ideas.jsonl
    Data/paper_world_model/manifest.json
    Output/paper_world_model/sync_report.md
    Output/paper_world_model/validation_errors.json (on failure)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from caselab_context.paper_paths import paper_root  # noqa: E402
from verity.runtime.runtime_io import ROOT, ensure_dir

OUTPUT_DIR = ROOT / "Data" / "paper_world_model"
REPORT_DIR = ROOT / "Output" / "paper_world_model"
SCHEMA_PATH = ROOT / "protocols" / "paper_world_model.schema.json"

SCAN_DIRS = (
    ("01_Cases", "cases", "extract_case"),
    ("03_Mechanisms", "mechanisms", "extract_mechanism"),
    ("08_Variables", "variables", "extract_variable"),
    ("10_Indicators", "indicators", "extract_indicator"),
    ("05_Trade-Ideas", "trade_ideas", "extract_trade_idea"),
)

SCHEMA_DEF_BY_CATEGORY = {
    "cases": "case",
    "mechanisms": "mechanism",
    "variables": "variable",
    "indicators": "indicator",
    "trade_ideas": "trade_idea",
}


def parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from markdown content."""
    if not content.startswith("---"):
        return {}, content

    try:
        end_idx = content.index("---", 3)
        frontmatter_str = content[3:end_idx].strip()
        body = content[end_idx + 3 :].strip()

        frontmatter: dict[str, Any] = {}
        current_key: str | None = None
        current_list: list[str] | None = None

        for line in frontmatter_str.split("\n"):
            line = line.rstrip()
            if not line or line.startswith("#"):
                continue

            if line.startswith("  - ") and current_key:
                if current_list is None:
                    current_list = []
                item = line[4:].strip().strip('"').strip("'")
                if item.startswith("[[") and item.endswith("]]"):
                    item = item[2:-2]
                current_list.append(item)
                continue

            if current_list is not None and current_key:
                frontmatter[current_key] = current_list
                current_list = None

            if ": " in line:
                key, value = line.split(": ", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")

                if value == "":
                    current_key = key
                    current_list = None
                    continue

                if value.startswith("[[") and value.endswith("]]"):
                    value = value[2:-2]

                frontmatter[key] = value
                current_key = key
                current_list = None

        if current_list is not None and current_key:
            frontmatter[current_key] = current_list

        return frontmatter, body

    except (ValueError, IndexError):
        return {}, content


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str) and value:
        return [value]
    return []


def _normalize_review_status(value: Any) -> str:
    status = str(value or "needs_review").strip().lower()
    aliases = {
        "approved": "approved",
        "needs_review": "needs_review",
        "rejected": "rejected",
        "reviewed": "needs_review",
        "accept": "approved",
        "accepted": "approved",
    }
    if status in aliases:
        return aliases[status]
    if status in {"approved", "needs_review", "rejected"}:
        return status
    return "needs_review"


def _normalize_review_score(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _iso_timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def extract_case(file_path: Path, content: str, paper_dir: Path) -> dict[str, Any] | None:
    frontmatter, _body = parse_frontmatter(content)
    if frontmatter.get("type") != "case":
        return None

    case_type = str(frontmatter.get("case_type", "unknown"))
    if case_type not in {"trading", "structural", "macro", "micro", "unknown"}:
        case_type = "unknown"

    status = str(frontmatter.get("status", "candidate"))
    if status not in {"candidate", "validated", "deprecated"}:
        status = "candidate"

    trade_relevance = str(frontmatter.get("trade_relevance", "medium"))
    if trade_relevance not in {"high", "medium", "low"}:
        trade_relevance = "medium"

    return {
        "case_id": file_path.stem,
        "case_type": case_type,
        "status": status,
        "main_entity": str(frontmatter.get("main_entity", "")),
        "country": str(frontmatter.get("country", "")),
        "sector": str(frontmatter.get("sector", "")),
        "mechanism_ids": _as_list(frontmatter.get("mechanisms")),
        "trade_relevance": trade_relevance,
        "tags": _as_list(frontmatter.get("tags")),
        "review_status": _normalize_review_status(frontmatter.get("review_status")),
        "review_score": _normalize_review_score(frontmatter.get("review_score")),
        "source_file": str(file_path.relative_to(paper_dir)),
        "extracted_at": _iso_timestamp(),
    }


def extract_mechanism(file_path: Path, content: str, paper_dir: Path) -> dict[str, Any] | None:
    frontmatter, _body = parse_frontmatter(content)
    if frontmatter.get("type") != "mechanism":
        return None

    confidence = str(frontmatter.get("confidence", "medium"))
    if confidence not in {"high", "medium", "low"}:
        confidence = "medium"

    return {
        "mechanism_id": file_path.stem,
        "name": str(frontmatter.get("name", file_path.stem)),
        "description": str(frontmatter.get("description", ""))[:500],
        "causal_claim": str(frontmatter.get("causal_claim", "")),
        "observable_signals": _as_list(frontmatter.get("observable_signals")),
        "invalidation_conditions": _as_list(frontmatter.get("invalidation_conditions")),
        "related_cases": _as_list(frontmatter.get("related_cases")),
        "related_variables": _as_list(frontmatter.get("related_variables")),
        "confidence": confidence,
        "review_status": _normalize_review_status(frontmatter.get("review_status")),
        "source_file": str(file_path.relative_to(paper_dir)),
        "extracted_at": _iso_timestamp(),
    }


def extract_variable(file_path: Path, content: str, paper_dir: Path) -> dict[str, Any] | None:
    frontmatter, _body = parse_frontmatter(content)
    if frontmatter.get("type") != "variable":
        return None

    frequency = str(frontmatter.get("frequency", "unknown"))
    if frequency not in {"daily", "weekly", "monthly", "quarterly", "unknown"}:
        frequency = "unknown"

    return {
        "variable_id": file_path.stem,
        "name": str(frontmatter.get("name", file_path.stem)),
        "description": str(frontmatter.get("description", ""))[:500],
        "data_source": str(frontmatter.get("data_source", "")),
        "frequency": frequency,
        "related_mechanisms": _as_list(frontmatter.get("related_mechanisms")),
        "trade_implication": str(frontmatter.get("trade_implication", "")),
        "review_status": _normalize_review_status(frontmatter.get("review_status")),
        "source_file": str(file_path.relative_to(paper_dir)),
        "extracted_at": _iso_timestamp(),
    }


def extract_indicator(file_path: Path, content: str, paper_dir: Path) -> dict[str, Any] | None:
    frontmatter, _body = parse_frontmatter(content)
    if frontmatter.get("type") != "indicator":
        return None

    frequency = str(frontmatter.get("frequency", "unknown"))
    if frequency not in {"daily", "weekly", "monthly", "quarterly", "unknown"}:
        frequency = "unknown"

    return {
        "indicator_id": file_path.stem,
        "name": str(frontmatter.get("name", file_path.stem)),
        "description": str(frontmatter.get("description", ""))[:500],
        "data_source": str(frontmatter.get("data_source", "")),
        "frequency": frequency,
        "related_variables": _as_list(frontmatter.get("related_variables")),
        "signal_interpretation": str(frontmatter.get("signal_interpretation", "")),
        "review_status": _normalize_review_status(frontmatter.get("review_status")),
        "source_file": str(file_path.relative_to(paper_dir)),
        "extracted_at": _iso_timestamp(),
    }


def extract_trade_idea(file_path: Path, content: str, paper_dir: Path) -> dict[str, Any] | None:
    frontmatter, _body = parse_frontmatter(content)
    if frontmatter.get("type") not in ("trade_idea", "trade", None):
        return None

    confidence = str(frontmatter.get("confidence", "medium"))
    if confidence not in {"high", "medium", "low"}:
        confidence = "medium"

    return {
        "idea_id": file_path.stem,
        "name": str(frontmatter.get("name", file_path.stem)),
        "description": str(frontmatter.get("description", ""))[:500],
        "asset_class": str(frontmatter.get("asset_class", "")),
        "market_regime": str(frontmatter.get("market_regime", "")),
        "historical_period": str(frontmatter.get("historical_period", "")),
        "causal_claim": str(frontmatter.get("causal_claim", "")),
        "observable_signals": _as_list(frontmatter.get("observable_signals")),
        "invalidation_conditions": _as_list(frontmatter.get("invalidation_conditions")),
        "trade_implication": str(frontmatter.get("trade_implication", "")),
        "confidence": confidence,
        "related_mechanisms": _as_list(frontmatter.get("related_mechanisms")),
        "related_variables": _as_list(frontmatter.get("related_variables")),
        "review_status": _normalize_review_status(frontmatter.get("review_status")),
        "source_file": str(file_path.relative_to(paper_dir)),
        "extracted_at": _iso_timestamp(),
    }


EXTRACTORS = {
    "extract_case": extract_case,
    "extract_mechanism": extract_mechanism,
    "extract_variable": extract_variable,
    "extract_indicator": extract_indicator,
    "extract_trade_idea": extract_trade_idea,
}


def list_paper_scan_files(paper_dir: Path) -> list[Path]:
    """List markdown files that participate in world-model sync."""
    files: list[Path] = []
    for subdir, _category, _extractor_name in SCAN_DIRS:
        dir_path = paper_dir / subdir
        if dir_path.exists():
            files.extend(sorted(dir_path.rglob("*.md")))
    return files


def scan_directory(dir_path: Path, extractor_name: str, paper_dir: Path) -> tuple[list[dict], list[Path]]:
    """Scan a directory and extract data from all markdown files."""
    extractor = EXTRACTORS[extractor_name]
    results: list[dict] = []
    scanned_files: list[Path] = []
    if not dir_path.exists():
        return results, scanned_files

    for file_path in sorted(dir_path.rglob("*.md")):
        scanned_files.append(file_path)
        try:
            content = file_path.read_text(encoding="utf-8")
            data = extractor(file_path, content, paper_dir)
            if data:
                results.append(data)
        except Exception as exc:
            print(f"  Warning: Failed to process {file_path}: {exc}")

    return results, scanned_files


def write_jsonl(data: list[dict], output_path: Path) -> None:
    ensure_dir(output_path.parent)
    with output_path.open("w", encoding="utf-8") as handle:
        for item in data:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")


def compute_paper_mtime_hash(scanned_files: list[Path], paper_dir: Path) -> str:
    digest = hashlib.sha256()
    for file_path in sorted(scanned_files):
        rel = file_path.relative_to(paper_dir).as_posix()
        mtime = int(file_path.stat().st_mtime)
        digest.update(f"{rel}:{mtime}\n".encode())
    return digest.hexdigest()


def validate_records(
    categories: dict[str, list[dict]],
    schema_path: Path = SCHEMA_PATH,
) -> list[dict[str, Any]]:
    """Validate JSONL records against paper_world_model schema definitions."""
    if not schema_path.exists():
        return [{"category": "*", "record_id": "*", "error": f"schema missing: {schema_path}"}]

    try:
        from jsonschema import Draft202012Validator, FormatChecker
    except ImportError:
        return []

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    definitions = schema.get("definitions", {})
    errors: list[dict[str, Any]] = []
    format_checker = FormatChecker()

    for category, records in categories.items():
        def_name = SCHEMA_DEF_BY_CATEGORY.get(category)
        if not def_name or def_name not in definitions:
            continue
        validator = Draft202012Validator(definitions[def_name], format_checker=format_checker)
        id_field = {
            "cases": "case_id",
            "mechanisms": "mechanism_id",
            "variables": "variable_id",
            "indicators": "indicator_id",
            "trade_ideas": "idea_id",
        }[category]

        for record in records:
            record_errors = sorted(validator.iter_errors(record), key=lambda e: e.path)
            if not record_errors:
                continue
            errors.append(
                {
                    "category": category,
                    "record_id": record.get(id_field, "?"),
                    "source_file": record.get("source_file"),
                    "errors": [e.message for e in record_errors],
                }
            )

    return errors


def build_sync_report(
    cases: list[dict],
    mechanisms: list[dict],
    variables: list[dict],
    indicators: list[dict],
    trade_ideas: list[dict],
) -> str:
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

    for name, items in [
        ("Cases", cases),
        ("Mechanisms", mechanisms),
        ("Variables", variables),
        ("Indicators", indicators),
        ("Trade Ideas", trade_ideas),
    ]:
        counts = count_by_status(items)
        lines.append(
            f"| {name} | {counts.get('approved', 0)} | "
            f"{counts.get('needs_review', 0)} | {counts.get('rejected', 0)} |"
        )

    lines += [
        "",
        "## Usage Rules",
        "",
        "- `review_status = approved` content can enter strong judgments",
        "- `review_status = needs_review` content can only enter background (includes `reviewed` alias)",
        "- `review_status = rejected` content cannot enter any judgment",
        "",
        "## Source Files",
        "",
    ]

    all_items = cases + mechanisms + variables + indicators + trade_ideas
    source_files = sorted({item.get("source_file", "") for item in all_items if item.get("source_file")})
    for source in source_files[:20]:
        lines.append(f"- `{source}`")
    if len(source_files) > 20:
        lines.append(f"- ... and {len(source_files) - 20} more")

    return "\n".join(lines) + "\n"


def run_sync(
    paper_dir: Path | None = None,
    output_dir: Path = OUTPUT_DIR,
    report_dir: Path = REPORT_DIR,
    *,
    quiet_on_success: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    paper_dir = paper_dir or paper_root()
    synced_at = _iso_timestamp()

    if not paper_dir.exists():
        raise FileNotFoundError(f"Paper directory not found: {paper_dir}")

    all_scanned = list_paper_scan_files(paper_dir)
    current_hash = compute_paper_mtime_hash(all_scanned, paper_dir)
    existing_manifest_path = output_dir / "manifest.json"
    if not force and existing_manifest_path.exists():
        try:
            existing = json.loads(existing_manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = None
        if existing and existing.get("paper_mtime_hash") == current_hash:
            # Hash match confirms Paper is still current — refresh TTL heartbeat.
            # Without this, skip leaves synced_at frozen and trade size steps down forever.
            existing["synced_at"] = synced_at
            existing["freshness_check"] = "paper_unchanged_heartbeat"
            ensure_dir(output_dir)
            existing_manifest_path.write_text(
                json.dumps(existing, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            if not quiet_on_success:
                print("Paper unchanged — freshness heartbeat updated (use --force to rescan)")
            return {
                "skipped": True,
                "reason": "paper_unchanged",
                "synced_at": synced_at,
                "manifest": str(existing_manifest_path),
                **(existing.get("record_counts") or {}),
            }

    if not quiet_on_success:
        print("Scanning Paper knowledge base...")

    categories: dict[str, list[dict]] = {}

    for subdir, category, extractor_name in SCAN_DIRS:
        if not quiet_on_success:
            print(f"  Extracting {category}...")
        records, scanned = scan_directory(paper_dir / subdir, extractor_name, paper_dir)
        categories[category] = records
        if not quiet_on_success:
            print(f"    Found {len(records)} {category}")

    if not quiet_on_success:
        print("\nWriting JSONL files...")
    for category in categories:
        write_jsonl(categories[category], output_dir / f"{category}.jsonl")

    validation_errors = validate_records(categories)
    if validation_errors:
        ensure_dir(report_dir)
        error_path = report_dir / "validation_errors.json"
        error_path.write_text(
            json.dumps(
                {
                    "synced_at": synced_at,
                    "paper_root": str(paper_dir),
                    "error_count": len(validation_errors),
                    "errors": validation_errors,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        raise ValueError(f"Schema validation failed ({len(validation_errors)} records). See {error_path}")

    manifest = {
        "schema_version": "paper_world_model.v1",
        "synced_at": synced_at,
        "paper_root": str(paper_dir),
        "paper_mtime_hash": current_hash,
        "record_counts": {key: len(val) for key, val in categories.items()},
        "jsonl_files": [f"{key}.jsonl" for key in categories],
    }
    ensure_dir(output_dir)
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    if not quiet_on_success:
        print("Writing sync report...")
    report = build_sync_report(
        categories["cases"],
        categories["mechanisms"],
        categories["variables"],
        categories["indicators"],
        categories["trade_ideas"],
    )
    ensure_dir(report_dir)
    (report_dir / "sync_report.md").write_text(report, encoding="utf-8")

    result = {
        **manifest["record_counts"],
        "synced_at": synced_at,
        "manifest": str(output_dir / "manifest.json"),
    }

    if not quiet_on_success:
        print("\n=== Sync Complete ===")
        for key, count in manifest["record_counts"].items():
            print(f"{key}: {count}")

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Paper World Model.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    parser.add_argument(
        "--quiet-on-success",
        action="store_true",
        help="Suppress progress output when sync succeeds (for git hooks).",
    )
    parser.add_argument("--force", action="store_true", help="Force sync even if Paper hash unchanged.")
    args = parser.parse_args()

    try:
        result = run_sync(quiet_on_success=args.quiet_on_success, force=args.force)
    except FileNotFoundError as exc:
        print(str(exc))
        sys.exit(1)
    except ValueError as exc:
        print(str(exc))
        sys.exit(1)

    if args.json:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
