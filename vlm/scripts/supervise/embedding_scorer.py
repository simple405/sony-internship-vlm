"""DashScope text-embedding scorer with a disk cache.

Used by evaluate_element_extraction.py to add semantic similarity as an
extra signal on top of keyword/Jaccard matching, so composite gold names
(e.g. "黑色过膝袜与棕色靴子") correctly match a pred that only covers part
of the composite (e.g. "黑色过膝袜").
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import requests

DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "text-embedding-v3"
BATCH_SIZE = 10  # DashScope text-embedding-v3 rejects batches larger than 10


class EmbeddingScorer:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        cache_path: Path | None = None,
        timeout: int = 60,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.cache_path = cache_path
        self.timeout = timeout
        self._cache: dict[str, list[float]] = {}
        if self.cache_path and self.cache_path.exists():
            try:
                self._cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._cache = {}

    def save_cache(self) -> None:
        if not self.cache_path:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self._cache, ensure_ascii=False), encoding="utf-8")

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        response = requests.post(
            f"{self.base_url}/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            data=json.dumps({"model": self.model, "input": texts}, ensure_ascii=False),
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        if "data" not in payload:
            raise RuntimeError(f"Embedding API error: {payload}")
        items = sorted(payload["data"], key=lambda item: item["index"])
        return [item["embedding"] for item in items]

    def precompute(self, texts: list[str]) -> None:
        """Embed any texts not already cached, then persist the cache."""
        unique_missing = list(dict.fromkeys(text for text in texts if text and text not in self._cache))
        for start in range(0, len(unique_missing), BATCH_SIZE):
            batch = unique_missing[start : start + BATCH_SIZE]
            vectors = self._embed_batch(batch)
            for text, vector in zip(batch, vectors):
                self._cache[text] = vector
        if unique_missing:
            self.save_cache()

    def similarity(self, a: str, b: str) -> float:
        if not a or not b:
            return 0.0
        vec_a = self._cache.get(a)
        vec_b = self._cache.get(b)
        if vec_a is None or vec_b is None:
            return 0.0
        dot = sum(x * y for x, y in zip(vec_a, vec_b))
        norm_a = math.sqrt(sum(x * x for x in vec_a))
        norm_b = math.sqrt(sum(x * x for x in vec_b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (norm_a * norm_b)
