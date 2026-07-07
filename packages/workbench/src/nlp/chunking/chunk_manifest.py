from __future__ import annotations

import json
from pathlib import Path
from workbench.paths import workspace_root as _workspace_root

from nlp.chunking.chunk_schema import ChunkManifest, TextChunk

ROOT = _workspace_root()
DATA_NLP = ROOT / "Data" / "nlp"


def write_chunk_manifest(
    document_id: str,
    chunks: list[TextChunk],
    *,
    manifest_id: str = "",
) -> Path:
    out_dir = DATA_NLP / "chunks"
    out_dir.mkdir(parents=True, exist_ok=True)

    mid = manifest_id or f"chunk_manifest_{document_id}"
    manifest = ChunkManifest(manifest_id=mid, document_id=document_id, chunks=chunks)
    out_path = out_dir / f"{mid}.json"
    out_path.write_text(
        manifest.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    return out_path
