"""Build TF-IDF embeddings from Paper index."""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from caselab_context.embeddings_core import build_tfidf, save_embeddings
from caselab_context.index_paper import INDEX_PATH, build_index, load_index, write_index

EMBEDDINGS_PATH = Path(__file__).resolve().parents[1] / "Data" / "caselab_context" / "embeddings.json"


def build_from_index(records: list[dict]) -> dict:
    return build_tfidf(records)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build note embeddings for context retrieval.")
    parser.add_argument("--reindex", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    records = build_index() if args.reindex or not INDEX_PATH.exists() else load_index()
    if args.reindex:
        write_index(records)
    payload = build_from_index(records)
    payload["built_at"] = datetime.now(UTC).isoformat()
    save_embeddings(EMBEDDINGS_PATH, payload)
    summary = {"count": len(records), "embeddings_path": str(EMBEDDINGS_PATH)}
    if args.json:
        print(json.dumps(summary, indent=2))
        return
    print(f"Built embeddings for {summary['count']} notes -> {EMBEDDINGS_PATH}")


if __name__ == "__main__":
    main()
