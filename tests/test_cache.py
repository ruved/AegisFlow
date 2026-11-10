"""Tests for bounded LRU, TTL, embedding, and retrieval caches (E3)."""

import time
from pathlib import Path

import pytest

from aegisflow.cache import (
    BoundedLRUCache,
    EmbeddingCache,
    RetrievalCache,
    clear_all_caches,
    get_embedding_cache,
    get_retrieval_cache,
)
from aegisflow.rag.embeddings import embed_texts
from aegisflow.rag.retrieval import retrieve


def test_bounded_lru_cache_eviction() -> None:
    cache: BoundedLRUCache[str, int] = BoundedLRUCache(max_size=3, ttl_seconds=60.0)

    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("c", 3)

    assert cache.get("a") == 1
    assert cache.get("b") == 2
    assert cache.get("c") == 3
    assert cache.size == 3

    # Accessing "a" makes it recently used; "b" and "c" follow
    assert cache.get("a") == 1

    # Adding "d" should evict least recently used ("b")
    cache.put("d", 4)
    assert cache.size == 3
    assert cache.get("b") is None
    assert cache.get("a") == 1
    assert cache.get("c") == 3
    assert cache.get("d") == 4


def test_bounded_lru_cache_ttl_expiration() -> None:
    cache: BoundedLRUCache[str, str] = BoundedLRUCache(max_size=5, ttl_seconds=0.1)

    cache.put("key1", "val1")
    assert cache.get("key1") == "val1"

    time.sleep(0.15)
    # Value should have expired
    assert cache.get("key1") is None
    assert cache.size == 0


def test_embedding_cache_get_many_partial_hits() -> None:
    cache = EmbeddingCache(max_size=10, ttl_seconds=60.0)
    cache.put("apple", [1.0, 0.0])
    cache.put("banana", [0.0, 1.0])

    texts = ["apple", "cherry", "banana", "date"]
    hits, missing = cache.get_many(texts)

    assert len(hits) == 2
    assert hits[0] == [1.0, 0.0]
    assert hits[2] == [0.0, 1.0]
    assert missing == [1, 3]


def test_retrieval_cache_invalidation_on_corpus_version_bump(tmp_path: Path) -> None:
    cache = RetrievalCache(max_size=10, ttl_seconds=60.0)

    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text('{"corpus_version": 1, "documents": {}}', encoding="utf-8")

    dummy_results = [{"chunk_id": "c1", "text": "hello"}]
    cache.put("test query", dummy_results, k=3, store_path=tmp_path)

    # First lookup matches version 1
    cached = cache.get("test query", k=3, store_path=tmp_path)
    assert cached is not None
    assert cached[0]["chunk_id"] == "c1"

    # Simulate re-ingestion bumping version to 2
    manifest_file.write_text('{"corpus_version": 2, "documents": {}}', encoding="utf-8")

    # Second lookup should miss and auto-invalidate the old version
    stale = cache.get("test query", k=3, store_path=tmp_path)
    assert stale is None


@pytest.mark.anyio
async def test_end_to_end_retrieval_caching() -> None:
    clear_all_caches()
    query = "When Order Service runs out of database connections"

    # First call: cold run
    r1 = await retrieve(query, k=2)
    assert len(r1) > 0
    assert not any(item.get("cache_hit", False) for item in r1)

    # Second call: warm run should hit retrieval cache
    t0 = time.perf_counter()
    r2 = await retrieve(query, k=2)
    dur_warm = time.perf_counter() - t0

    assert len(r2) == len(r1)
    assert any(item.get("cache_hit", False) for item in r2)
    assert r2[0]["chunk_id"] == r1[0]["chunk_id"]
    # Warm retrieval should return almost instantly (< 50ms)
    assert dur_warm < 0.1
