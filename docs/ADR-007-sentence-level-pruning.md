# ADR-007: Sentence-Level Pruning Trade-offs (E6)

- **Status:** Rejected / Dropped
- **Date:** 2026-11-10

## Context

E6 investigates extractive context compression: segmenting retrieved evidence passages into sentences, embedding each sentence with the query, and retaining only sentences exceeding an embedding cosine similarity threshold plus a 1-sentence neighbor window. Exact technical identifiers (UUIDs, error codes, version strings) are preserved, and unsuitable content (code blocks, log files) is excluded.

The architectural hypothesis was that compressing evidence text would reduce prompt token prefill and thus decrease total generation latency.

## Measurements

We conducted an empirical threshold sweep (`evals/sweep_pruning.py`) across gold corpus documents (`golden_v0.jsonl`), testing similarity thresholds from 0.45 to 0.85:

| Threshold | Compression Ratio | Gold Fact Recall | Sentence Embedding Cost | Prefill Savings | Net Latency Impact |
| :---: | :---: | :---: | :---: | :---: | :---: |
| **0.45** | 0.99 | 100.0% | 17,262.6 ms (cold load) | 1.7 ms | **+17,260.9 ms (slower)** |
| **0.55** | 0.88 | 100.0% | 55.6 ms | 29.6 ms | **+26.0 ms (slower)** |
| **0.65** | 0.40 | 87.0% | 54.3 ms | 141.4 ms | **-87.1 ms (recall loss!)** |
| **0.75** | 0.23 | 87.0% | 50.2 ms | 182.5 ms | **-132.3 ms (recall loss!)** |
| **0.85** | 0.20 | 80.0% | 52.4 ms | 188.7 ms | **-136.3 ms (recall loss!)** |

In the full ablation study (`evals/run_ablation.py`):
- `E5 Only (ContextBuilder)`: Mean Latency 2,133.4 ms (-0.9%), 100% citation recall, 0 ms embedding overhead.
- `E5 + E6 (Builder + Pruning)`: Mean Latency 2,165.5 ms (+0.5%), added latency without quality improvement.

## Decision

**DROP E6 in default pipeline.** Keep `ENABLE_SENTENCE_PRUNING = False`.

### Rationale:
1. **Unfavorable Latency Equation on Edge Models:** Generating embeddings for 5–15 individual sentences per chunk costs ~50–60 ms in Ollama, whereas saving 200 prompt tokens saves only ~10–25 ms of prefill time on local 4B models. The net latency is negative (+26 ms slower) at recall-safe thresholds.
2. **Quality Risk:** At compression thresholds high enough to achieve net latency savings (≥ 0.65), citation recall degraded from 100% to 87% and 80%, dropping critical facts required for verified incident remediation.
3. **E5 Superiority:** E5 Context Builder achieves token budgeting and deduplication with zero embedding overhead and zero recall loss.
