from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Workbench" / "src"))

from nlp.ingestion import load_document

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Ingest a document into the NLP layer.")
    parser.add_argument("path", help="Path to source document")
    args = parser.parse_args()
    md_path, manifest = load_document(args.path)
    print(f"Converted: {md_path}")
    print(f"Manifest:  {manifest.document_id} ({manifest.conversion_status})")
