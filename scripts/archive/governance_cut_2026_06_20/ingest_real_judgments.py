"""Ingest real daily judgment cards and trade ledger entries into the feedback sample pool.

Reads from:
- Output/judgment/{date}.json  (judgment cards)
- Output/trade_ledger/decisions.jsonl  (trade ledger entries)

Appends to:
- Data/feedback_samples/sample_manifest.jsonl

Each real judgment becomes a sample of type 'real_judgment'.
Forward outcomes will be computed by evaluate_feedback_samples.py.

Usage:
    python3 scripts/ingest_real_judgments.py
    python3 scripts/ingest_real_judgments.py --dry-run
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from _workspace_imports import add_scripts
add_scripts()
from _runtime_io import ensure_dir, load_json, load_jsonl, utc_now  # noqa: E402

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
JUDGMENT_DIR = ROOT / "Output" / "judgment"
LEDGER_PATH = ROOT / "Output" / "trade_ledger" / "decisions.jsonl"
MANIFEST_PATH = ROOT / "Data" / "feedback_samples" / "sample_manifest.jsonl"


def _short_hash(date: str, source: str) -> str:
    raw = f"{date}_{source}"
    return hashlib.sha256(raw.encode()).hexdigest()[:8]


def _parse_judgment_card(path: Path) -> dict | None:
    """Parse a judgment card into the feedback_sample system_judgment format."""
    card = load_json(path)
    if not card:
        return None

    # Map from judgment card schema to feedback_sample schema
    confidence = card.get("confidence", {})
    if isinstance(confidence, dict):
        conf_level = confidence.get("level", "low")
    else:
        conf_level = str(confidence)

    claim_ladder = card.get("claim_ladder", {})
    tier = claim_ladder.get("tier", 0)
    label = claim_ladder.get("label", "observation")
    statement = claim_ladder.get("claim_statement", "")
    watch = claim_ladder.get("watch_conditions", [])
    invalidation = claim_ladder.get("invalidation_conditions", [])

    decision = card.get("decision", "UNKNOWN")
    # Normalize: WATCH_ONLY -> WATCH, RESEARCH_REVIEW stays
    if decision == "WATCH_ONLY":
        decision = "WATCH"

    gate = card.get("gate_status", {})

    return {
        "system_judgment": {
            "decision": decision,
            "confidence": conf_level,
            "claim_tier": tier,
            "claim_label": label,
            "claim_statement": statement,
            "mechanism_hypothesis": statement,
            "evidence_grade": "C",  # Real pipeline output, not a replay proxy
        },
        "conditions": {
            "watch_conditions": watch,
            "invalidation_conditions": invalidation,
        },
        "gate_status": gate,
    }


def _parse_ledger_entries(path: Path) -> dict[str, list[dict]]:
    """Group trade ledger entries by date."""
    entries = load_jsonl(path)
    by_date: dict[str, list[dict]] = {}
    for entry in entries:
        date = entry.get("date", "")
        if date:
            by_date.setdefault(date, []).append(entry)
    return by_date


def ingest(dry_run: bool = False) -> list[dict]:
    """Ingest real judgments into the sample manifest."""
    now_iso = utc_now().isoformat()
    samples = []

    # Load existing manifest to avoid duplicates
    existing_ids = set()
    if MANIFEST_PATH.exists():
        for entry in load_jsonl(MANIFEST_PATH):
            sid = entry.get("sample_id", "")
            existing_ids.add(sid)

    # 1. Parse judgment cards
    judgment_cards = sorted(JUDGMENT_DIR.glob("20*.json"))
    print(f"[INFO] Found {len(judgment_cards)} judgment cards")

    for card_path in judgment_cards:
        date_str = card_path.stem  # e.g., "2026-06-18"
        sid = f"{date_str}_real_judgment_{_short_hash(date_str, 'real_judgment')}"

        if sid in existing_ids:
            print(f"  [SKIP] {sid} already in manifest")
            continue

        parsed = _parse_judgment_card(card_path)
        if not parsed:
            continue

        sample = {
            "schema_version": "feedback_sample.v1",
            "sample_id": sid,
            "as_of_date": date_str,
            "sample_type": "real_judgment",
            "why_selected": f"Real daily judgment card from pipeline run",
            "generated_at": now_iso,
            "allowed_lookback": "",  # Real pipeline uses all available data
            "system_state": {
                "m_value": None,
                "d_value": None,
                "k_value": None,
                "x_value": None,
            },
            "source_judgment_path": str(card_path),
            "forward_outcome": {},
            "review_label": "needs_review",
        }
        sample.update(parsed)
        samples.append(sample)
        print(f"  [ADD] {sid}: {parsed['system_judgment']['decision']}/{parsed['system_judgment']['confidence']}")

    # 2. Parse trade ledger entries (use the best entry per date)
    if LEDGER_PATH.exists():
        ledger_by_date = _parse_ledger_entries(LEDGER_PATH)
        print(f"[INFO] Found {len(ledger_by_date)} dates in trade ledger")

        for date_str, entries in ledger_by_date.items():
            sid = f"{date_str}_real_ledger_{_short_hash(date_str, 'real_ledger')}"
            if sid in existing_ids:
                continue

            # Use the first entry (usually the most complete)
            entry = entries[0]
            thesis = entry.get("trade_thesis", {})
            claim_ladder = thesis.get("claim_ladder", {})

            sample = {
                "schema_version": "feedback_sample.v1",
                "sample_id": sid,
                "as_of_date": date_str,
                "sample_type": "real_judgment",
                "why_selected": f"Real trade ledger entry ({len(entries)} entries on this date)",
                "generated_at": now_iso,
                "allowed_lookback": "",
                "system_state": {
                    "m_value": None,
                    "d_value": None,
                    "k_value": None,
                    "x_value": None,
                },
                "system_judgment": {
                    "decision": entry.get("decision", "NO_TRADE"),
                    "confidence": entry.get("confidence", "low"),
                    "claim_tier": claim_ladder.get("tier", 0),
                    "claim_label": claim_ladder.get("label", "observation"),
                    "claim_statement": claim_ladder.get("claim_statement", ""),
                    "mechanism_hypothesis": thesis.get("hypothesis", ""),
                    "evidence_grade": entry.get("evidence_grade", "D"),
                },
                "conditions": {
                    "watch_conditions": thesis.get("watch_conditions", []),
                    "invalidation_conditions": thesis.get("invalidation_conditions", entry.get("invalidation", [])),
                },
                "source_judgment_path": str(LEDGER_PATH),
                "forward_outcome": {},
                "review_label": "needs_review",
            }
            samples.append(sample)
            print(f"  [ADD] {sid}: {sample['system_judgment']['decision']}/{sample['system_judgment']['confidence']}")

    if not samples:
        print("[INFO] No new samples to add")
        return []

    # Append to manifest
    if not dry_run:
        with open(MANIFEST_PATH, "a", encoding="utf-8") as f:
            for sample in samples:
                f.write(json.dumps(sample, ensure_ascii=False) + "\n")
        print(f"[OK] Appended {len(samples)} real judgment samples to {MANIFEST_PATH}")
    else:
        print(f"[DRY-RUN] Would append {len(samples)} samples")

    return samples


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest real judgment cards into feedback sample pool"
    )
    parser.add_argument("--dry-run", action="store_true", help="Don't write anything")
    args = parser.parse_args()
    ingest(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
