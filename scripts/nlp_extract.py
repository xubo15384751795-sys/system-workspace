from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Workbench" / "src"))

from nlp import (
    chunk_document,
    extract_entities,
    extract_event_card,
    validate_event_card,
    write_event_card,
    write_extraction_report,
)


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Extract candidate structural event cards from markdown.")
    parser.add_argument("path", help="Path to markdown document")
    parser.add_argument("--event-name", default="", help="Optional event name override")
    args = parser.parse_args()

    source = Path(args.path)
    if not source.exists():
        print(f"File not found: {args.path}")
        return 1

    text = source.read_text(encoding="utf-8")
    doc_id = source.stem

    chunks = chunk_document(text, document_id=doc_id)
    entities = extract_entities(chunks)
    card = extract_event_card(chunks, entities, document_id=doc_id, event_name=args.event_name)

    joined = "\n".join(c.text for c in chunks)
    validation = validate_event_card(card, source_text=joined)

    json_path = write_event_card(card, validation=validation, source_text=joined)
    report_path = write_extraction_report(card, validation=validation)

    print(f"Event card: {json_path}")
    print(f"Report:     {report_path}")
    print(f"Valid:      {validation['valid']}")
    for err in validation.get("errors", []):
        print(f"  ERROR: {err}")
    for warn in validation.get("warnings", []):
        print(f"  WARN:  {warn}")
    print(f"Status:     {card.status}")
    print(f"Variables:  {[k for k, v in card.variable_mapping.model_dump().items() if v]}")

    return 0 if validation["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
