"""Bounded, thread-safe LRU and TTL caches for embeddings and retrieval (E3).

Provides:
- EmbeddingCache: keyed by normalized text hash + embedding-model version.
- RetrievalCache: keyed by normalized query hash + corpus version + filters.
- Automatic invalidation on corpus version changes and bounded growth control.
- Prometheus metrics recording and cache hit attributes for OpenTelemetry spans.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from aegisflow.config import EMBEDDING_MODEL
from aegisflow.metrics import record_cache_hit
from aegisflow.rag.ingest_state import CorpusManifest

logger = logging.getLogger("aegisflow.cache")

K = TypeVar("K")
V = TypeVar("V")

# Global experiment feature flags (can be toggled for ablation studies)
ENABLE_EMBEDDING_CACHE: bool = True
ENABLE_RETRIEVAL_CACHE: bool = True


@dataclass
class CacheEntry[V]:
    """Value with absolute expiration timestamp."""

    value: V
    expires_at: float


class BoundedLRUCache[K, V]:
    """Thread-safe bounded Least-Recently-Used (LRU) cache with per-item TTL."""

    def __init__(self, max_size: int = 1024, ttl_seconds: float = 3600.0) -> None:
        self.max_size = max(1, max_size)
        self.ttl_seconds = max(0.1, ttl_seconds)
        self._cache: OrderedDict[K, CacheEntry[V]] = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def get(self, key: K) -> V | None:
        """Retrieve item if present and unexpired, updating access recency."""
        now = time.monotonic()
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._misses += 1
                return None

            if entry.expires_at <= now:
                # Expired: evict and register miss
                del self._cache[key]
                self._misses += 1
                return None

            # Hit: mark recently used
            self._cache.move_to_end(key)
            self._hits += 1
            return entry.value

    def put(self, key: K, value: V) -> None:
        """Store item with TTL expiration, evicting oldest item if at capacity."""
        now = time.monotonic()
        expires_at = now + self.ttl_seconds
        with self._lock:
            if key in self._cache:
                self._cache[key] = CacheEntry(value=value, expires_at=expires_at)
                self._cache.move_to_end(key)
                return

            if len(self._cache) >= self.max_size:
                # Evict least recently used (first item)
                self._cache.popitem(last=False)

            self._cache[key] = CacheEntry(value=value, expires_at=expires_at)

    def delete(self, key: K) -> bool:
        """Remove an item explicitly from cache."""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def clear(self) -> None:
        """Remove all entries and reset stats."""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._cache)

    @property
    def hits(self) -> int:
        return self._hits

    @property
    def misses(self) -> int:
        return self._misses

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return (self._hits / total) if total > 0 else 0.0


# ---------------------------------------------------------------------------
# Embedding Cache
# ---------------------------------------------------------------------------


class EmbeddingCache:
    """Bounded LRU cache for embedding vectors.

    Keyed by SHA-256 of normalized text + embedding model version.
    """

    def __init__(self, max_size: int = 2048, ttl_seconds: float = 86400.0) -> None:
        self._lru: BoundedLRUCache[str, list[float]] = BoundedLRUCache(
            max_size=max_size, ttl_seconds=ttl_seconds
        )

    @staticmethod
    def make_key(text: str, model: str = EMBEDDING_MODEL) -> str:
        """Construct deterministic cache key from normalized text and model name."""
        normalized = " ".join(text.strip().split())
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return f"{model}:{digest}"

    def get(self, text: str, model: str = EMBEDDING_MODEL) -> list[float] | None:
        if not ENABLE_EMBEDDING_CACHE:
            return None
        key = self.make_key(text, model)
        vec = self._lru.get(key)
        if vec is not None:
            record_cache_hit("embedding")
        return vec

    def put(self, text: str, vector: list[float], model: str = EMBEDDING_MODEL) -> None:
        if not ENABLE_EMBEDDING_CACHE:
            return
        key = self.make_key(text, model)
        self._lru.put(key, vector)

    def get_many(
        self, texts: list[str], model: str = EMBEDDING_MODEL
    ) -> tuple[dict[int, list[float]], list[int]]:
        """Look up multiple texts.

        Returns:
            cached_hits: dict mapping original index -> cached vector
            missing_indices: list of indices that must be computed
        """
        if not ENABLE_EMBEDDING_CACHE:
            return {}, list(range(len(texts)))

        hits: dict[int, list[float]] = {}
        missing: list[int] = []

        for idx, text in enumerate(texts):
            vec = self.get(text, model)
            if vec is not None:
                hits[idx] = vec
            else:
                missing.append(idx)

        return hits, missing

    def put_many(
        self,
        texts: list[str],
        vectors: list[list[float]],
        model: str = EMBEDDING_MODEL,
    ) -> None:
        if not ENABLE_EMBEDDING_CACHE:
            return
        for text, vec in zip(texts, vectors, strict=True):
            self.put(text, vec, model)

    def clear(self) -> None:
        self._lru.clear()

    @property
    def size(self) -> int:
        return self._lru.size

    @property
    def hits(self) -> int:
        return self._lru.hits

    @property
    def misses(self) -> int:
        return self._lru.misses

    @property
    def hit_rate(self) -> float:
        return self._lru.hit_rate


# ---------------------------------------------------------------------------
# Retrieval Cache
# ---------------------------------------------------------------------------


class RetrievalCache:
    """Bounded LRU cache for hybrid retrieval results.

    Keyed by SHA-256 of normalized query + corpus version + filter params.
    Automatically invalidates results when the corpus version is bumped.
    """

    def __init__(self, max_size: int = 512, ttl_seconds: float = 3600.0) -> None:
        self._lru: BoundedLRUCache[str, list[dict[str, Any]]] = BoundedLRUCache(
            max_size=max_size, ttl_seconds=ttl_seconds
        )
        self._last_known_corpus_version: int | None = None

    @staticmethod
    def get_corpus_version(store_path: str | Path) -> int:
        """Read the current corpus version from the ingestion manifest."""
        manifest_path = Path(store_path) / "manifest.json"
        if manifest_path.exists():
            try:
                manifest = CorpusManifest.load(manifest_path)
                return manifest.corpus_version
            except Exception:
                pass
        return 0

    @classmethod
    def make_key(
        cls,
        query: str,
        corpus_version: int,
        k: int,
        rrf_constant: int,
        store_path: str | Path,
    ) -> str:
        """Construct deterministic key with corpus version and search parameters."""
        normalized = " ".join(query.strip().lower().split())
        query_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        store_str = Path(store_path).name
        return f"v{corpus_version}:{store_str}:k{k}:rrf{rrf_constant}:{query_hash}"

    def get(
        self,
        query: str,
        k: int,
        store_path: str | Path,
        rrf_constant: int = 60,
    ) -> list[dict[str, Any]] | None:
        """Look up cached retrieval results.

        Automatically detects corpus version changes and invalidates stale entries.
        """
        if not ENABLE_RETRIEVAL_CACHE:
            return None

        corpus_version = self.get_corpus_version(store_path)

        # If corpus version changed, purge entire retrieval cache
        if (
            self._last_known_corpus_version is not None
            and self._last_known_corpus_version != corpus_version
        ):
            logger.info(
                "Corpus version bumped from %s to %s; invalidating retrieval cache",
                self._last_known_corpus_version,
                corpus_version,
            )
            self._lru.clear()

        self._last_known_corpus_version = corpus_version

        key = self.make_key(query, corpus_version, k, rrf_constant, store_path)
        results = self._lru.get(key)
        if results is not None:
            record_cache_hit("retrieval")
            # Return deep copies marked with cache_hit=True
            return [{**item, "cache_hit": True} for item in results]
        return None

    def put(
        self,
        query: str,
        results: list[dict[str, Any]],
        k: int,
        store_path: str | Path,
        rrf_constant: int = 60,
    ) -> None:
        """Store retrieval results with current corpus version."""
        if not ENABLE_RETRIEVAL_CACHE:
            return

        corpus_version = self.get_corpus_version(store_path)
        self._last_known_corpus_version = corpus_version

        key = self.make_key(query, corpus_version, k, rrf_constant, store_path)
        # Store clean copies without transient metadata
        clean_results = [
            {k: v for k, v in item.items() if k != "cache_hit"} for item in results
        ]
        self._lru.put(key, clean_results)

    def invalidate_corpus(self) -> None:
        """Explicitly purge retrieval cache entries."""
        self._lru.clear()
        self._last_known_corpus_version = None

    def clear(self) -> None:
        self.invalidate_corpus()

    @property
    def size(self) -> int:
        return self._lru.size

    @property
    def hits(self) -> int:
        return self._lru.hits

    @property
    def misses(self) -> int:
        return self._lru.misses

    @property
    def hit_rate(self) -> float:
        return self._lru.hit_rate


# ---------------------------------------------------------------------------
# Global Singletons
# ---------------------------------------------------------------------------

_EMBEDDING_CACHE = EmbeddingCache()
_RETRIEVAL_CACHE = RetrievalCache()


def get_embedding_cache() -> EmbeddingCache:
    """Return the global embedding cache singleton."""
    return _EMBEDDING_CACHE


def get_retrieval_cache() -> RetrievalCache:
    """Return the global retrieval cache singleton."""
    return _RETRIEVAL_CACHE


def clear_all_caches() -> None:
    """Reset both embedding and retrieval caches."""
    _EMBEDDING_CACHE.clear()
    _RETRIEVAL_CACHE.clear()
