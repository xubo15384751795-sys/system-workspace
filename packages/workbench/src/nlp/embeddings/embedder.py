from __future__ import annotations

import hashlib
from pathlib import Path
from workbench.paths import workspace_root as _workspace_root
from typing import Optional

from pydantic import BaseModel, Field

from nlp.chunking.chunk_schema import TextChunk

ROOT = _workspace_root()
DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"


class EmbeddingRecord(BaseModel):
    chunk_id: str
    document_id: str
    embedding: list[float] = Field(default_factory=list)
    dimensions: int = 0
    model_name: str = DEFAULT_MODEL
    text_hash: str = ""

    def model_post_init(self, _ctx):
        self.dimensions = len(self.embedding)
        if not self.text_hash:
            self.text_hash = hashlib.sha256(
                self.chunk_id.encode("utf-8")
            ).hexdigest()[:16]


class Embedder:
    """Sentence-Transformers wrapper for chunk embedding.

    Uses BGE-small by default (384 dims) for a good balance of
    quality and speed. Falls back to a lightweight TF-IDF-style
    sparse representation if sentence-transformers is not installed,
    so the NLP layer remains usable without heavy dependencies.
    """

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self.model_name = model_name
        self._model: Optional[object] = None

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self._model is None:
            self._model = self._load_model()
        if self._model is None:
            return _fallback_embed(texts)
        embeddings = self._model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [vec.tolist() for vec in embeddings]

    def embed_chunks(self, chunks: list[TextChunk]) -> list[EmbeddingRecord]:
        texts = [chunk.text for chunk in chunks]
        vectors = self.embed(texts)
        records: list[EmbeddingRecord] = []
        for chunk, vec in zip(chunks, vectors):
            records.append(
                EmbeddingRecord(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    embedding=vec,
                    model_name=self.model_name,
                )
            )
        return records

    def embed_query(self, query: str) -> list[float]:
        return self.embed([query])[0]

    def _load_model(self) -> Optional[object]:
        try:
            from sentence_transformers import SentenceTransformer
            return SentenceTransformer(self.model_name)
        except ImportError:
            return None
        except Exception:
            return None


def embed_chunks(
    chunks: list[TextChunk],
    *,
    model_name: str = DEFAULT_MODEL,
) -> list[EmbeddingRecord]:
    embedder = Embedder(model_name=model_name)
    return embedder.embed_chunks(chunks)


def _fallback_embed(texts: list[str]) -> list[list[float]]:
    """Lightweight fallback: character n-gram overlap sketch (64-dim).

    This keeps the NLP layer functional without sentence-transformers.
    The quality is lower but sufficient for keyword-ish similarity.
    """
    import re
    dims = 64
    vectors: list[list[float]] = []
    for text in texts:
        clean = re.sub(r"\s+", " ", text.lower().strip())
        vec = [0.0] * dims
        for i in range(len(clean) - 2):
            bucket = hash(clean[i : i + 3]) % dims
            vec[bucket] += 1.0 / max(1, len(clean))
        norm = max(0.0001, sum(v * v for v in vec) ** 0.5)
        vectors.append([v / norm for v in vec])
    return vectors
