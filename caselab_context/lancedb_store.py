"""LanceDB storage adapter for CaseLab embeddings.

JSON embeddings.json remains a compatibility export; LanceDB is the ANN store
behind search() when available.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_TABLE = "caselab_docs"


def lancedb_dir(root: Path) -> Path:
    return root / "Data" / "caselab_context" / "lancedb"


def migrate_payload_to_lancedb(payload: dict[str, Any], *, db_path: Path) -> int:
    """Write docs (+ optional dense vectors) into a LanceDB table. Returns row count."""
    import lancedb
    import pyarrow as pa

    docs = payload.get("docs") or []
    dense = payload.get("dense_vectors")
    rows: list[dict[str, Any]] = []
    for index, doc in enumerate(docs):
        row = {
            "doc_id": str(doc.get("id") or doc.get("path") or index),
            "text": str(doc.get("text") or ""),
            "meta_json": json.dumps(doc, ensure_ascii=False),
        }
        if dense is not None and index < len(dense):
            row["vector"] = list(map(float, dense[index]))
        rows.append(row)

    db_path.mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(str(db_path))
    if not rows:
        return 0
    if "vector" in rows[0]:
        table = db.create_table(DEFAULT_TABLE, data=rows, mode="overwrite")
    else:
        # Sparse-only corpora: store docs without vector column for keyword fallback.
        table = db.create_table(DEFAULT_TABLE, data=rows, mode="overwrite")
    del table, pa
    return len(rows)


def search_lancedb(
    query_vector: list[float],
    *,
    db_path: Path,
    top_k: int = 5,
) -> list[dict[str, Any]] | None:
    """ANN search when a vector table exists; None if unavailable."""
    try:
        import lancedb
    except ImportError:
        return None
    if not db_path.exists():
        return None
    db = lancedb.connect(str(db_path))
    list_tables = getattr(db, "list_tables", None)
    raw = list_tables() if callable(list_tables) else db.table_names()
    if hasattr(raw, "tables"):
        raw_tables = list(raw.tables or [])
    elif isinstance(raw, (list, tuple, set)):
        raw_tables = list(raw)
    else:
        raw_tables = list(raw or [])
    names: set[str] = set()
    for item in raw_tables:
        if isinstance(item, str):
            names.add(item)
        else:
            names.add(str(getattr(item, "name", item)))
    if DEFAULT_TABLE not in names:
        return None
    table = db.open_table(DEFAULT_TABLE)
    if "vector" not in table.schema.names:
        return None
    hits = table.search(query_vector).limit(top_k).to_list()
    results: list[dict[str, Any]] = []
    for hit in hits:
        meta = json.loads(hit.get("meta_json") or "{}")
        score = hit.get("_distance")
        # LanceDB returns distance; convert to a descending similarity-like score.
        sim = 1.0 / (1.0 + float(score)) if score is not None else 0.0
        results.append({"score": round(sim, 4), **meta})
    return results
