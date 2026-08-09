"""Optional LanceDB backend for NLP VectorStore."""
from __future__ import annotations

import pytest
from nlp.chunking.chunk_schema import TextChunk
from nlp.embeddings.embedder import EmbeddingRecord
from nlp.embeddings.vector_store import VectorStore

pytest.importorskip("lancedb")


def test_vector_store_save_load_lancedb(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NLP_USE_LANCEDB", "1")
    store = VectorStore(index_dir=tmp_path)
    chunks = [
        TextChunk(
            chunk_id="c1",
            document_id="d1",
            text="funding stress in repo markets",
            parent_chunk_id="p1",
            parent_context_hash="sha256:abc",
        )
    ]
    records = [
        EmbeddingRecord(
            chunk_id="c1",
            document_id="d1",
            text_hash="h1",
            embedding=[0.1, 0.2, 0.3, 0.4],
        )
    ]
    store.add(records, chunks)
    store.save(name="unit")
    assert (tmp_path / "unit_lancedb").exists()

    loaded = VectorStore(index_dir=tmp_path)
    assert loaded.load(name="unit") is True
    assert loaded.size == 1
    hits = loaded.search([0.1, 0.2, 0.3, 0.4], top_k=1)
    assert hits
