# ADR-002: Keep hybrid retrieval for the RAG retrieval layer

- **Status:** Accepted for retrieval; generation default remains unchanged pending answer-quality evaluation.
- **Date:** 2026-10-30
- **Decision owners:** AegisFlow project

## Context

Dense retrieval captures semantic similarity but can miss exact identifiers and
service names. SQLite FTS5 supplies lexical matches, and Reciprocal Rank Fusion
(RRF) combines ranked lists without comparing their incompatible distance and
BM25 score scales.

The existing `results/baseline_E0.csv` was not a valid comparison set: its
Chroma collection held only two chunks from `docs/rag_samples`, while the golden
set expects `data/corpus`. We therefore measured a fresh dense baseline and
hybrid run on the same index and queries.

## Experiment

- Dataset: 30 golden questions; 25 answerable questions and 34 gold
  `(document, section)` targets. The 5 unanswerable questions are excluded from
  retrieval metric means.
- Corpus: 27 documents from `data/corpus`, 146 chunks, indexed in
  `chroma_db_eval` with the same default 800-character chunks and 100-character
  overlap. The unchanged rerun processed 27 unchanged documents and embedded
  zero chunks.
- Embedding model: `nomic-embed-text:latest`.
- Systems: E0 is dense-only. E1 fuses the same dense and lexical rankings with
  RRF constant 60.
- Candidate settings: 3 and 5 for each retriever. To keep the tuning bounded,
  each question was retrieved once at 5; the top 3 prefixes were then scored at
  3. This preserves each retriever's exact top-3 ordering while avoiding a
  second query-embedding call.
- Metrics: section Recall@k, MRR, and nDCG@k. Recall counts distinct gold
  sections. A chunk crossing headings can satisfy multiple sections for Recall,
  but remains one ranked result for nDCG. A “win” or “loss” below means fused
  section Recall was higher or lower than dense for that question; equal recall
  is a tie even if the hit section identities differ.

## Results

Macro averages over the 25 answerable questions:

| Candidate k | Retriever | Recall@k | MRR | nDCG@k |
|---:|---|---:|---:|---:|
| 3 | Dense (E0) | 0.480 | 0.407 | 0.406 |
| 3 | Lexical | 0.507 | 0.473 | 0.450 |
| 3 | Fused (E1) | **0.547** | 0.407 | 0.426 |
| 5 | Dense (E0) | 0.580 | 0.435 | 0.449 |
| 5 | Lexical | 0.573 | **0.483** | 0.483 |
| 5 | Fused (E1) | **0.660** | 0.471 | **0.502** |

At k=3, E1 gained 0.067 absolute section Recall over E0, while MRR was tied.
At k=5, E1 gained 0.080 Recall, 0.036 MRR, and 0.053 nDCG over E0. Lexical
retrieval alone had the highest MRR at both cutoffs; fusion retained its exact
match benefit while improving the overall Recall and nDCG at k=5.

| Slice | Questions | Dense R@3 | Fused R@3 | Dense R@5 | Fused R@5 |
|---|---:|---:|---:|---:|---:|
| `single_hop` | 20 | 0.525 | **0.625** | 0.625 | **0.725** |
| `multi_part` | 5 | **0.300** | 0.233 | 0.400 | 0.400 |
| `unanswerable` | 5 | — | — | — | — |

Section-recall wins and losses against E0:

- **k=3:** wins G002 and G019; loss G024; 22 ties and 5 unanswerable cases.
  G002 gained the order database-pool incident log section; G019 gained the
  Payment Service responsibility section. G024 lost the Search Service
  dependencies section for a multi-part catalog/search question.
- **k=5:** wins G002 and G010; no losses; 23 ties and 5 unanswerable cases.
  G010 gained the RB-005 mitigation section. Per-question hit sets and metrics
  for all cases are in [`E1_retrieval_comparison.csv`](../results/E1_retrieval_comparison.csv).

Concurrent retrieval latency at candidate k=5 had a 2,184.6 ms dense median and
a 2,186.1 ms dense-plus-lexical median (paired median difference: 1.6 ms). The
nearest-rank P95 was 2,283.9 ms dense and 2,284.8 ms hybrid. This is one local
run, not a hardware-independent latency claim.

## Decision

Keep hybrid retrieval. Use candidate k=5 for retrieval comparisons and recall-
sensitive use: it had the best fused Recall and nDCG, no per-question Recall
losses against dense, and near-identical latency in this run. Keep the
API's current default top-k at 3 until answer quality and prompt-context effects
are measured; this experiment evaluates retrieval only and makes no claim about
generated-answer correctness.

The multi-part slice is small (5 questions) and fused k=3 regressed there. Keep
reviewing per-question differences as the golden set grows; do not tune beyond
the two tested settings from these results alone.

## Reproduction

```powershell
uv run python -m aegisflow.rag.ingest --docs data/corpus --store chroma_db_eval
uv run eval-retrieval-experiment --store chroma_db_eval --ks 3 5
```
