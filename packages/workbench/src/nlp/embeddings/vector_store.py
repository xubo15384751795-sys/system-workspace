from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional, cast

from workbench.paths import workspace_root as _workspace_root

from nlp.chunking.chunk_schema import TextChunk
from nlp.embeddings.embedder import DEFAULT_MODEL, Embedder, EmbeddingRecord

ROOT = _workspace_root()
DEFAULT_INDEX_DIR = ROOT / "Data" / "nlp" / "embeddings"
LANCEDB_TABLE = "nlp_chunks"
logger = logging.getLogger(__name__)


def _prefer_lancedb() -> bool:
    raw = os.environ.get("NLP_USE_LANCEDB", "auto").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    if raw in {"1", "true", "yes", "on"}:
        return True
    try:
        import lancedb  # noqa: F401
    except ImportError:
        return False
    return True


class VectorStore:
    """Vector index for NLP chunks.

    Preference order when saving/searching:
      1. LanceDB when available (``NLP_USE_LANCEDB=auto|1``)
      2. FAISS when installed
      3. Brute-force numpy fallback
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
        self._backend: str = "memory"
        self._backend_status: dict[str, object] = {
            "backend": "memory",
            "fallback": False,
            "error": None,
        }

    @property
    def backend_status(self) -> dict[str, object]:
        """Return the last index backend outcome without backend payloads."""
        return dict(self._backend_status)

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
        self._backend = "memory"
        self._backend_status = {"backend": "memory", "fallback": False, "error": None}
        lancedb_preferred = _prefer_lancedb() and bool(self._records)
        if lancedb_preferred:
            try:
                lancedb_saved = self._save_lancedb(name)
            except Exception as exc:  # noqa: BLE001 - optional backend has explicit fallback
                lancedb_saved = False
                self._backend_status["error"] = type(exc).__name__
                logger.warning("LanceDB save failed; using local index fallback: %s", type(exc).__name__)
            if lancedb_saved:
                self._backend = "lancedb"
                self._backend_status = {"backend": "lancedb", "fallback": False, "error": None}
            else:
                self._backend_status["fallback"] = True
                self._backend_status["error"] = self._backend_status["error"] or "lancedb_unavailable"

        if self._backend != "lancedb" and self._index is not None:
            self._save_index(self.index_dir / name)
            self._backend = "faiss" if not isinstance(self._index, _NumpyIndex) else "numpy"
            self._backend_status["backend"] = self._backend
        meta_path = self.index_dir / f"{name}_meta.json"
        meta = {
            "model_name": self.model_name,
            "num_records": len(self._records),
            "backend": self._backend,
            "backend_status": self.backend_status,
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
        self.model_name = meta.get("model_name", self.model_name)
        self._records = [
            EmbeddingRecord(
                chunk_id=str(record.get("chunk_id") or ""),
                document_id=str(record.get("document_id") or ""),
                text_hash=str(record.get("text_hash") or ""),
                model_name=self.model_name,
            )
            for record in meta.get("records", [])
            if isinstance(record, dict)
        ]
        persisted_status = meta.get("backend_status")
        if isinstance(persisted_status, dict):
            self._backend_status = {
                "backend": str(persisted_status.get("backend") or "uninitialized"),
                "fallback": bool(persisted_status.get("fallback", False)),
                "error": (
                    str(persisted_status["error"])
                    if persisted_status.get("error") is not None
                    else None
                ),
            }
        else:
            self._backend_status = {"backend": "uninitialized", "fallback": False, "error": None}
        if meta.get("backend") == "lancedb":
            try:
                lancedb_loaded = self._load_lancedb(name)
            except Exception as exc:  # noqa: BLE001 - optional backend has explicit fallback
                lancedb_loaded = False
                self._backend_status["error"] = type(exc).__name__
                logger.warning("LanceDB load failed; using local index fallback: %s", type(exc).__name__)
            if lancedb_loaded:
                self._backend = "lancedb"
                self._backend_status = {"backend": "lancedb", "fallback": False, "error": None}
                return True
            self._backend_status["fallback"] = True
            self._backend_status["error"] = self._backend_status["error"] or "lancedb_unavailable"
        index_path = self.index_dir / name
        if self._index_exists(index_path):
            self._index = self._load_index(index_path)
            self._backend = "faiss" if not isinstance(self._index, _NumpyIndex) else "numpy"
            self._backend_status["backend"] = self._backend
            return True
        self._backend = "memory"
        self._backend_status["backend"] = "memory"
        self._backend_status["error"] = self._backend_status["error"] or "index_missing"
        return False

    def _lancedb_dir(self, name: str) -> Path:
        return self.index_dir / f"{name}_lancedb"

    def _save_lancedb(self, name: str) -> bool:
        try:
            import lancedb
        except ImportError:
            return False
        rows = []
        for record in self._records:
            rows.append(
                {
                    "chunk_id": record.chunk_id,
                    "document_id": record.document_id,
                    "text_hash": record.text_hash,
                    "text": self._chunk_texts.get(record.chunk_id, ""),
                    "vector": list(map(float, record.embedding)),
                }
            )
        if not rows:
            return False
        db_path = self._lancedb_dir(name)
        db_path.mkdir(parents=True, exist_ok=True)
        db = lancedb.connect(str(db_path))
        db.create_table(LANCEDB_TABLE, data=rows, mode="overwrite")
        return True

    def _load_lancedb(self, name: str) -> bool:
        try:
            import lancedb
        except ImportError:
            return False
        db_path = self._lancedb_dir(name)
        if not db_path.exists():
            return False
        db = lancedb.connect(str(db_path))
        list_tables = getattr(db, "list_tables", None)
        raw = list_tables() if callable(list_tables) else getattr(db, "table_names", lambda: [])()
        if hasattr(raw, "tables"):
            raw_tables = list(raw.tables or [])
        elif isinstance(raw, (list, tuple, set)):
            raw_tables = list(raw)
        else:
            raw_tables = list(raw or [])
        names = {
            item if isinstance(item, str) else str(getattr(item, "name", item))
            for item in raw_tables
        }
        if LANCEDB_TABLE not in names:
            return False
        table = db.open_table(LANCEDB_TABLE)
        rows = table.to_pandas().to_dict(orient="records")
        self._records = []
        for row in rows:
            vector = row.get("vector")
            if vector is None:
                embedding: list[float] = []
            else:
                embedding = [float(x) for x in list(vector)]
            self._records.append(
                EmbeddingRecord(
                    chunk_id=str(row.get("chunk_id") or ""),
                    document_id=str(row.get("document_id") or ""),
                    text_hash=str(row.get("text_hash") or ""),
                    embedding=embedding,
                )
            )
            if row.get("text"):
                self._chunk_texts[str(row["chunk_id"])] = str(row["text"])
        if self._records:
            self._index = self._create_index([r.embedding for r in self._records])
        return bool(self._records)

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
            import numpy as np
            arr = np.array(vectors, dtype=np.float32)
            cast(Any, self._index).add(arr)
        except ImportError:
            if isinstance(self._index, _NumpyIndex):
                self._index.add(vectors)

    def _search_index(self, query_vector: list[float], *, top_k: int) -> list[tuple[int, float]]:
        if isinstance(self._index, _NumpyIndex):
            return self._index.search(query_vector, top_k=top_k)
        try:
            import numpy as np
            q = np.array([query_vector], dtype=np.float32)
            index = cast(Any, self._index)
            scores, indices = index.search(q, min(top_k, int(index.ntotal)))
            return [
                (int(indices[0][i]), float(scores[0][i]))
                for i in range(len(indices[0]))
                if indices[0][i] >= 0
            ]
        except (ImportError, AttributeError) as exc:
            self._backend_status = {
                "backend": self._backend,
                "fallback": False,
                "error": type(exc).__name__,
            }
            logger.warning("Vector search backend failed; returning no hits: %s", type(exc).__name__)
            return []

    def _save_index(self, path: Path) -> None:
        if isinstance(self._index, _NumpyIndex):
            self._index.save(path)
            return
        try:
            import faiss
            faiss.write_index(self._index, str(path))
        except ImportError as exc:
            raise RuntimeError("FAISS backend is unavailable for a non-NumPy index") from exc

    def _load_index(self, path: Path):
        if not path.exists() and Path(str(path) + ".npz").exists():
            return _NumpyIndex.load(path)
        try:
            import faiss
            return faiss.read_index(str(path))
        except ImportError as exc:
            raise RuntimeError("FAISS backend is unavailable for the persisted index") from exc

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
        return int(self.vectors.shape[0])

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
