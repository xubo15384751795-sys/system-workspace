"""Optional backend failures remain visible and fall back explicitly."""
from __future__ import annotations

import json

from nlp.cases.case_registry import CaseProfile, CaseRegistry
from nlp.cases.case_similarity import CaseSimilarityEngine
from nlp.chunking.chunk_schema import TextChunk
from nlp.embeddings.embedder import Embedder, EmbeddingRecord
from nlp.embeddings.vector_store import VectorStore


def _record() -> tuple[EmbeddingRecord, TextChunk]:
    chunk = TextChunk(
        chunk_id="c1",
        document_id="d1",
        text="funding stress in repo markets",
    )
    record = EmbeddingRecord(
        chunk_id="c1",
        document_id="d1",
        text_hash="h1",
        embedding=[0.1, 0.2, 0.3, 0.4],
    )
    return record, chunk


def test_embedder_reports_hash_fallback(monkeypatch) -> None:
    embedder = Embedder()
    monkeypatch.setattr(embedder, "_load_model", lambda: None)

    vectors = embedder.embed(["funding stress"])

    assert vectors
    assert embedder.backend_status == {
        "backend": "hash_fallback",
        "fallback": True,
        "error": "model_unavailable",
    }


def test_vector_store_persists_local_index_when_lancedb_fails(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NLP_USE_LANCEDB", "1")
    store = VectorStore(index_dir=tmp_path)
    record, chunk = _record()
    store.add([record], [chunk])
    monkeypatch.setattr(store, "_save_lancedb", lambda name: False)

    store.save(name="unit")

    metadata = json.loads((tmp_path / "unit_meta.json").read_text(encoding="utf-8"))
    assert metadata["backend"] in {"faiss", "numpy"}
    assert store.backend_status["backend"] in {"faiss", "numpy"}
    assert store.backend_status["fallback"] is True
    assert store.backend_status["error"] == "lancedb_unavailable"

    loaded = VectorStore(index_dir=tmp_path)
    assert loaded.load(name="unit") is True
    assert loaded.size == 1
    assert loaded.backend_status["backend"] in {"faiss", "numpy"}
    assert loaded.backend_status["fallback"] is True
    assert loaded.backend_status["error"] == "lancedb_unavailable"


def test_vector_store_reports_lancedb_exception_and_falls_back(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NLP_USE_LANCEDB", "1")
    store = VectorStore(index_dir=tmp_path)
    record, chunk = _record()
    store.add([record], [chunk])

    def fail(_name: str) -> bool:
        raise RuntimeError("backend-specific detail must not become status text")

    monkeypatch.setattr(store, "_save_lancedb", fail)
    store.save(name="unit")

    assert store.backend_status["fallback"] is True
    assert store.backend_status["error"] == "RuntimeError"


def test_case_similarity_reports_graph_fallback() -> None:
    registry = CaseRegistry()
    registry.add(CaseProfile(case_id="case_a", case_name="case_a", variable_vector={"S": 1.0}))

    class FailingGraph:
        def graph_similarity(self, _left, _right) -> float:
            raise RuntimeError("graph detail must not become status text")

    engine = CaseSimilarityEngine(registry, graph_embedder=FailingGraph())
    graph = object()
    engine.find_similar(
        variable_vector={"S": 1.0},
        query_graph=graph,
        case_graphs={"case_a": graph},
    )

    assert engine.backend_status["graph"] == {
        "backend": "graph_embedder",
        "fallback": True,
        "error": "RuntimeError",
    }
