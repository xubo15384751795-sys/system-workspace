from __future__ import annotations

from workbench.paths import workspace_root as _workspace_root

from pydantic import BaseModel, Field

from nlp.chunking.chunk_schema import TextChunk
from nlp.embeddings.embedder import Embedder

ROOT = _workspace_root()


class TopicResult(BaseModel):
    topic_id: int
    label: str = ""
    keywords: list[str] = Field(default_factory=list)
    top_chunk_ids: list[str] = Field(default_factory=list)
    chunk_count: int = 0
    coherence_score: float = 0.0


class TopicModel:
    """Lightweight topic modeling over NLP chunks.

    Uses a two-stage approach:
    1. Embed chunks with Sentence-Transformers (or fallback)
    2. Cluster with UMAP + HDBSCAN, then extract keywords via c-TF-IDF

    Falls back to a simple TF-IDF + k-means approach if heavy deps
    (umap-learn, hdbscan) are not available.
    """

    def __init__(
        self,
        *,
        embedder: Embedder | None = None,
        min_topic_size: int = 3,
        n_topics: int | None = None,
    ) -> None:
        self.embedder = embedder or Embedder()
        self.min_topic_size = min_topic_size
        self.n_topics = n_topics

    def fit(self, chunks: list[TextChunk]) -> list[TopicResult]:
        if not chunks:
            return []
        texts = [c.text for c in chunks]
        try:
            return self._fit_bertopic(texts, chunks)
        except ImportError:
            return self._fit_fallback(texts, chunks)

    def _fit_bertopic(self, texts: list[str], chunks: list[TextChunk]) -> list[TopicResult]:
        from bertopic import BERTopic
        from bertopic.representation import KeyBERTInspired

        embeddings = self.embedder.embed(texts)
        representation_model = KeyBERTInspired()
        model = BERTopic(
            embedding_model=self.embedder._model,
            min_topic_size=self.min_topic_size,
            nr_topics=self.n_topics,
            representation_model=representation_model,
            calculate_probabilities=False,
            verbose=False,
        )
        topics, _ = model.fit_transform(texts, embeddings)
        return self._build_results(model, topics, chunks, texts)

    def _fit_fallback(self, texts: list[str], chunks: list[TextChunk]) -> list[TopicResult]:
        """TF-IDF + k-means fallback when BERTopic is not installed."""
        embeddings = self.embedder.embed(texts)
        n = len(texts)

        try:
            from sklearn.cluster import KMeans
            n_clusters = min(self.n_topics or max(3, n // self.min_topic_size), n)
            if n_clusters > n:
                n_clusters = max(1, n)
            if n_clusters < 2 and n >= 2:
                n_clusters = 2
            if n <= 1 or n_clusters <= 1:
                labels = [0] * n
            else:
                kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
                labels = kmeans.fit_predict(embeddings)
        except (ImportError, ValueError):
            labels = [0] * n

        results: list[TopicResult] = []
        topic_texts: dict[int, list[str]] = {}
        topic_chunks: dict[int, list[str]] = {}
        for i, label in enumerate(labels):
            topic_texts.setdefault(int(label), []).append(texts[i])
            topic_chunks.setdefault(int(label), []).append(chunks[i].chunk_id)

        for topic_id, t_texts in topic_texts.items():
            if topic_id == -1:
                continue
            keywords = _extract_keywords_tfidf(t_texts, top_n=8)
            topic_label = " ".join(keywords[:3]) if keywords else f"topic_{topic_id}"
            results.append(
                TopicResult(
                    topic_id=topic_id,
                    label=topic_label,
                    keywords=keywords,
                    top_chunk_ids=topic_chunks.get(topic_id, [])[:10],
                    chunk_count=len(t_texts),
                )
            )

        results.sort(key=lambda r: r.chunk_count, reverse=True)
        return results

    def _build_results(
        self, model, topic_ids: list[int], chunks: list[TextChunk], texts: list[str]
    ) -> list[TopicResult]:
        results: list[TopicResult] = []
        topic_info = model.get_topic_info()
        topic_chunks: dict[int, list[str]] = {}
        for i, tid in enumerate(topic_ids):
            topic_chunks.setdefault(int(tid), []).append(chunks[i].chunk_id)

        for _, row in topic_info.iterrows():
            tid = int(row["Topic"])
            if tid == -1:
                continue
            kw = row.get("Representation", [])
            if not kw:
                kw = row.get("Name", "").split("_")
            keywords = [str(k) for k in kw[:8]]
            results.append(
                TopicResult(
                    topic_id=tid,
                    label=" ".join(keywords[:3]) if keywords else f"topic_{tid}",
                    keywords=keywords,
                    top_chunk_ids=topic_chunks.get(tid, [])[:10],
                    chunk_count=int(row.get("Count", 0)),
                )
            )
        return results


def model_topics(
    chunks: list[TextChunk],
    *,
    min_topic_size: int = 3,
    n_topics: int | None = None,
) -> list[TopicResult]:
    model = TopicModel(min_topic_size=min_topic_size, n_topics=n_topics)
    return model.fit(chunks)


def _extract_keywords_tfidf(texts: list[str], *, top_n: int = 8) -> list[str]:
    import re
    from collections import Counter

    stopwords = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "in", "on", "at", "to", "for", "of", "and", "or", "but", "not",
        "this", "that", "these", "those", "it", "its", "with", "from",
        "by", "as", "has", "have", "had", "can", "may", "will", "would",
        "which", "who", "whom", "what", "when", "where", "how",
        "also", "than", "then", "now", "just", "very", "too", "so",
    }

    doc_freq: Counter = Counter()
    for text in texts:
        tokens = set(re.findall(r"\b[a-z]{3,}\b", text.lower()))
        doc_freq.update(tokens)

    all_terms: Counter = Counter()
    for text in texts:
        token_list = re.findall(r"\b[a-z]{3,}\b", text.lower())
        all_terms.update(t for t in token_list if t not in stopwords)

    total_docs = len(texts)
    scores: dict[str, float] = {}
    for term, tf in all_terms.items():
        df = doc_freq.get(term, 1)
        idf = max(0.0, __import__("math").log(total_docs / (1 + df)))
        scores[term] = tf * idf

    return [term for term, _ in sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_n]]
