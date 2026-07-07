from __future__ import annotations

import json
from pathlib import Path
from workbench.paths import workspace_root as _workspace_root
from typing import Optional

from nlp.chunking.chunk_schema import TextChunk
from nlp.embeddings.embedder import DEFAULT_MODEL, Embedder, EmbeddingRecord

ROOT = _workspace_root()
DEFAULT_INDEX_DIR = ROOT / "Data" / "nlp" / "embeddings"


class VectorStore:
    """FAISS-backed vector index for NLP chunks.

    Stores embeddings and provides nearest-neighbour lookup.
    Falls back to a brute-force numpy index if FAISS is not installed.
    """

    def __init__(
        self,
        *,
        index_dir: Path | None = None,
        model_name: str = DEFAULT_MODEL,
    ) -> None:
        self.index_dir = index_dir or DEFAULT_INDEX_DIR
        self.model_name = model_name
        self._index: Optional[object] = None
        self._records: list[EmbeddingRecord] = []
        self._chunk_texts: dict[str, str] = {}

    def add(self, records: list[EmbeddingRecord], chunks: list[TextChunk]) -> None:
        if not records:
            return
        self._records.extend(records)
        for chunk in chunks:
            self._chunk_texts[chunk.chunk_id] = chunk.text
        if self._index is None:
            self._index = self._create_index([r.embedding for r in self._records])
        else:
            new_vectors = [r.embedding for r in records]
            self._add_to_index(new_vectors)

    def search(self, query_vector: list[float], *, top_k: int = 10) -> list[tuple[int, float]]:
        if self._index is None or not self._records:
            return []
        return self._search_index(query_vector, top_k=top_k)

    def search_with_scores(
        self,
        query_vector: list[float],
        *,
        top_k: int = 10,
    ) -> list[tuple[EmbeddingRecord, float]]:
        results = self.search(query_vector, top_k=top_k)
        return [
            (self._records[idx], float(score))
            for idx, score in results
            if 0 <= idx < len(self._records)
        ]

    def save(self, name: str = "nlp_chunks") -> Path:
        self.index_dir.mkdir(parents=True, exist_ok=True)
        if self._index is not None:
            self._save_index(self.index_dir / name)
        meta_path = self.index_dir / f"{name}_meta.json"
        meta = {
            "model_name": self.model_name,
            "num_records": len(self._records),
            "records": [
                {"chunk_id": r.chunk_id, "document_id": r.document_id, "text_hash": r.text_hash}
                for r in self._records
            ],
            "chunk_texts": self._chunk_texts,
        }
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.index_dir / name

    def load(self, name: str = "nlp_chunks") -> bool:
        meta_path = self.index_dir / f"{name}_meta.json"
        if not meta_path.exists():
            return False
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        self._chunk_texts = meta.get("chunk_texts", {})
        index_path = self.index_dir / name
        if self._index_exists(index_path):
            self._index = self._load_index(index_path)
        self.model_name = meta.get("model_name", self.model_name)
        return True

    @property
    def size(self) -> int:
        return len(self._records)

    def get_chunk_text(self, chunk_id: str) -> str:
        return self._chunk_texts.get(chunk_id, "")

    # -- internal index ops (FAISS or brute-force numpy) --

    def _create_index(self, vectors: list[list[float]]):
        try:
            import faiss
            import numpy as np
            arr = np.array(vectors, dtype=np.float32)
            dim = arr.shape[1]
            index = faiss.IndexFlatIP(dim)
            index.add(arr)
            return index
        except ImportError:
            return _NumpyIndex(vectors)

    def _add_to_index(self, vectors: list[list[float]]) -> None:
        if self._index is None:
            self._index = self._create_index(vectors)
            return
        try:
            import faiss
            import numpy as np
            arr = np.array(vectors, dtype=np.float32)
            self._index.add(arr)
        except ImportError:
            if isinstance(self._index, _NumpyIndex):
                self._index.add(vectors)

    def _search_index(self, query_vector: list[float], *, top_k: int) -> list[tuple[int, float]]:
        try:
            import faiss
            import numpy as np
            q = np.array([query_vector], dtype=np.float32)
            scores, indices = self._index.search(q, min(top_k, self._index.ntotal))
            return [
                (int(indices[0][i]), float(scores[0][i]))
                for i in range(len(indices[0]))
                if indices[0][i] >= 0
            ]
        except (ImportError, AttributeError):
            if isinstance(self._index, _NumpyIndex):
                return self._index.search(query_vector, top_k=top_k)
            return []

    def _save_index(self, path: Path) -> None:
        try:
            import faiss
            faiss.write_index(self._index, str(path))
        except (ImportError, AttributeError):
            if isinstance(self._index, _NumpyIndex):
                self._index.save(path)

    def _load_index(self, path: Path):
        try:
            import faiss
            return faiss.read_index(str(path))
        except ImportError:
            return _NumpyIndex.load(path)

    def _index_exists(self, path: Path) -> bool:
        return path.exists() or Path(str(path) + ".npz").exists()


class _NumpyIndex:
    """Brute-force cosine similarity index (no FAISS dependency)."""

    def __init__(self, vectors: list[list[float]] | None = None) -> None:
        import numpy as np
        self.vectors = np.array(vectors or [], dtype=np.float32)

    def add(self, vectors: list[list[float]]) -> None:
        import numpy as np
        new = np.array(vectors, dtype=np.float32)
        if self.vectors.size == 0:
            self.vectors = new
        else:
            self.vectors = np.concatenate([self.vectors, new], axis=0)

    def search(self, query_vector: list[float], *, top_k: int) -> list[tuple[int, float]]:
        import numpy as np
        if self.vectors.size == 0:
            return []
        q = np.array(query_vector, dtype=np.float32)
        scores = np.dot(self.vectors, q)
        top_indices = np.argsort(scores)[::-1][:top_k]
        return [(int(i), float(scores[i])) for i in top_indices if scores[i] > 0]

    @property
    def ntotal(self) -> int:
        return self.vectors.shape[0]

    def save(self, path: Path) -> None:
        import numpy as np
        np.savez_compressed(str(path) + ".npz", vectors=self.vectors)

    @classmethod
    def load(cls, path: Path):
        import numpy as np
        data = np.load(str(path) + ".npz")
        obj = cls()
        obj.vectors = data["vectors"]
        return obj


def build_index(
    chunks: list[TextChunk],
    *,
    index_dir: Path | None = None,
    model_name: str = DEFAULT_MODEL,
    index_name: str = "nlp_chunks",
) -> VectorStore:
    embedder = Embedder(model_name=model_name)
    records = embedder.embed_chunks(chunks)
    store = VectorStore(index_dir=index_dir, model_name=model_name)
    store.add(records, chunks)
    store.save(name=index_name)
    return store
