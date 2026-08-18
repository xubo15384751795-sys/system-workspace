from __future__ import annotations

import hashlib
import logging
from typing import Any, Optional, cast

from pydantic import BaseModel, Field
from workbench.paths import workspace_root as _workspace_root

from nlp.chunking.chunk_schema import TextChunk

ROOT = _workspace_root()
DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
logger = logging.getLogger(__name__)


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
        self._backend_status: dict[str, object] = {
            "backend": "uninitialized",
            "fallback": False,
            "error": None,
        }

    @property
    def backend_status(self) -> dict[str, object]:
        """Return the last embedding backend outcome without exception details."""
        return dict(self._backend_status)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self._model is None:
            self._model = self._load_model()
        if self._model is None:
            self._set_fallback_status("model_unavailable")
            return _fallback_embed(texts)
        try:
            model = cast(Any, self._model)
            embeddings = model.encode(
                texts,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        except Exception as exc:  # noqa: BLE001 - optional backend has explicit fallback
            self._set_fallback_status(type(exc).__name__)
            logger.warning("Embedding backend failed; using hash fallback: %s", type(exc).__name__)
            return _fallback_embed(texts)
        self._backend_status = {
            "backend": "sentence_transformers",
            "fallback": False,
            "error": None,
        }
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
            return cast(object, SentenceTransformer(self.model_name))
        except ImportError:
            logger.info("Embedding backend unavailable; using hash fallback: dependency_missing")
            return None
        except Exception as exc:  # noqa: BLE001 - optional backend has explicit fallback
            logger.warning("Embedding backend load failed; using hash fallback: %s", type(exc).__name__)
            return None

    def _set_fallback_status(self, error: str) -> None:
        self._backend_status = {
            "backend": "hash_fallback",
            "fallback": True,
            "error": error,
        }


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
