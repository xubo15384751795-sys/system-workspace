"""LanceDB CaseLab store migrate/search smoke."""
from __future__ import annotations

from pathlib import Path

from caselab_context.lancedb_store import migrate_payload_to_lancedb, search_lancedb


def test_migrate_and_search_dense(tmp_path: Path):
    payload = {
        "docs": [
            {"id": "a", "text": "funding stress"},
            {"id": "b", "text": "relief rally"},
        ],
        "dense_vectors": [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
        ],
    }
    db_path = tmp_path / "lancedb"
    assert migrate_payload_to_lancedb(payload, db_path=db_path) == 2
    hits = search_lancedb([1.0, 0.0, 0.0], db_path=db_path, top_k=1)
    assert hits is not None
    assert hits[0]["id"] == "a"
