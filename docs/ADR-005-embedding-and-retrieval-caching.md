# ADR-005: Embedding & Retrieval Caching (E3)

- **Status:** Accepted
- **Date:** 2026-11-10

## Context

In production usage and repeated incident investigation, on-call engineers frequently submit identical questions, rephrased queries, and overlapping sub-questions. Without caching, each query incurs:
1. Dense vector embedding overhead via the local Ollama `/api/embed` endpoint.
2. Hybrid Chroma vector search + SQLite FTS5 lexical search.
3. Parent context hydration and reciprocal rank fusion.

E3 introduces two bounded in-memory LRU + TTL caches in `src/aegisflow/cache.py`:
- `EmbeddingCache`: Keyed by `f"{model}:{sha256(normalized_text)}"`. Bounded to 2,048 entries with 24-hour TTL.
- `RetrievalCache`: Keyed by `f"v{corpus_version}:{store}:{k}:rrf{rrf_constant}:{sha256(normalized_query)}"`. Bounded to 512 entries with 1-hour TTL.

Both caches expose Prometheus metrics (`aegisflow_cache_hits_total`) and propagate cache hit attributes into OpenTelemetry spans. Crucially, when corpus re-ingestion bumps `corpus_version` in the manifest, stale retrieval cache entries are automatically bypassed and invalidated without requiring manual cache flush.

## Measurements

Evaluated across the 10-query mixed benchmark workload (`BM-001` to `BM-010`):

| Configuration | Mean Latency | p95 Latency | Cache Hit Rate | Net Latency Delta |
| :--- | :---: | :---: | :---: | :---: |
| **Baseline (No Cache)** | 2,153.8 ms | 2,188.0 ms | 0.0% | 0.0% |
| **E3 (Embedding + Retrieval Cache)** | 1,729.3 ms | 2,179.0 ms | 20.0% | **-19.7%** |

On repeat queries hitting the cache directly:
- Retrieval latency dropped from **~2,130 ms down to 0.17 ms** (>99.9% reduction).
- Zero remote or local embedding calls were made on repeated text.
- Re-ingestion invalidation was verified in `tests/test_cache.py`: bumping `corpus_version` from 1 to 2 immediately purged stale cached results and triggered clean re-retrieval.

## Decision

**KEEP E3.** Adopt embedding and retrieval caching as default in the production pipeline.

## Consequences & Trade-offs
- **Pros:** ~20% reduction in average latency on mixed workloads, instant (<1ms) responses on repeated queries, zero GPU/CPU cycles wasted on redundant embeddings.
- **Cons:** In-memory footprint of ~10 MB for 2,048 embedding vectors and 512 retrieved chunk sets. Mitigated by strict LRU bounds and monotonic corpus-version keys preventing stale reads.
