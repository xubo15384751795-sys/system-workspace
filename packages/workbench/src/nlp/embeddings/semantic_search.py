from __future__ import annotations

from workbench.paths import workspace_root as _workspace_root

from pydantic import BaseModel, Field

from nlp.chunking.chunk_schema import TextChunk
from nlp.embeddings.embedder import DEFAULT_MODEL, Embedder
from nlp.embeddings.vector_store import VectorStore

ROOT = _workspace_root()


class SearchResult(BaseModel):
    chunk_id: str
    document_id: str
    text: str
    score: float
    section_title: str = ""
    parent_context_hash: str = ""
    metadata: dict = Field(default_factory=dict)


class SemanticSearcher:
    """Semantic search over chunked NLP documents.

    Wraps Embedder + VectorStore for query-by-meaning retrieval.
    Results are returned with chunk text and metadata for citation.
    """

    def __init__(
        self,
        *,
        vector_store: VectorStore | None = None,
        embedder: Embedder | None = None,
        model_name: str = DEFAULT_MODEL,
    ) -> None:
        self.store = vector_store or VectorStore(model_name=model_name)
        self.embedder = embedder or Embedder(model_name=model_name)

    def index_chunks(self, chunks: list[TextChunk], *, index_name: str = "nlp_chunks") -> None:
        records = self.embedder.embed_chunks(chunks)
        self.store.add(records, chunks)
        self.store.save(name=index_name)

    def search(
        self,
        query: str,
        *,
        top_k: int = 10,
        min_score: float = 0.0,
    ) -> list[SearchResult]:
        query_vec = self.embedder.embed_query(query)
        hits = self.store.search_with_scores(query_vec, top_k=top_k)
        results: list[SearchResult] = []
        for record, score in hits:
            if score < min_score:
                continue
            results.append(
                SearchResult(
                    chunk_id=record.chunk_id,
                    document_id=record.document_id,
                    text=self.store.get_chunk_text(record.chunk_id),
                    score=round(score, 4),
                )
            )
        return results

    def search_across(
        self,
        queries: list[str],
        *,
        top_k: int = 10,
        min_score: float = 0.0,
    ) -> dict[str, list[SearchResult]]:
        return {q: self.search(q, top_k=top_k, min_score=min_score) for q in queries}

    def load_index(self, name: str = "nlp_chunks") -> bool:
        return self.store.load(name)

    @property
    def index_size(self) -> int:
        return self.store.size


def search_similar(
    query: str,
    chunks: list[TextChunk],
    *,
    top_k: int = 10,
    min_score: float = 0.0,
    model_name: str = DEFAULT_MODEL,
) -> list[SearchResult]:
    """Convenience: build ephemeral index and search in one call.

    For repeated queries, construct a SemanticSearcher directly
    so the index is reused.
    """
    store = VectorStore(model_name=model_name)
    embedder = Embedder(model_name=model_name)
    records = embedder.embed_chunks(chunks)
    store.add(records, chunks)
    searcher = SemanticSearcher(vector_store=store, embedder=embedder)
    return searcher.search(query, top_k=top_k, min_score=min_score)
