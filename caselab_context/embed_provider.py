"""Embedding providers for CaseLab context retrieval."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Callable

DEFAULT_OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
DEFAULT_EMBED_MODEL = os.environ.get("CASELAB_EMBED_MODEL", "nomic-embed-text")
DEFAULT_TIMEOUT = float(os.environ.get("CASELAB_EMBED_TIMEOUT", "120"))


def ollama_available(base_url: str = DEFAULT_OLLAMA_URL) -> bool:
    try:
        with urllib.request.urlopen(f"{base_url.rstrip('/')}/api/tags", timeout=2) as resp:
            return resp.status == 200
    except (OSError, urllib.error.URLError, TimeoutError, ValueError):
        return False


def embed_with_ollama(
    texts: list[str],
    *,
    model: str = DEFAULT_EMBED_MODEL,
    base_url: str = DEFAULT_OLLAMA_URL,
    timeout: float = DEFAULT_TIMEOUT,
) -> list[list[float]]:
    vectors: list[list[float]] = []
    endpoint = f"{base_url.rstrip('/')}/api/embeddings"
    for text in texts:
        payload = json.dumps({"model": model, "prompt": text}).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        embedding = data.get("embedding")
        if not isinstance(embedding, list) or not embedding:
            raise RuntimeError(f"Ollama returned empty embedding for model={model}")
        vectors.append([float(v) for v in embedding])
    return vectors


def default_embed_fn() -> Callable[[list[str]], list[list[float]]] | None:
    if not ollama_available():
        return None
    return lambda texts: embed_with_ollama(texts)
