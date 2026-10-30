# Chunk-size comparison (W3 D2)

## Setup

Compared three parent/child targets on the same 27-document `data/corpus` and all
30 cases in `data/eval/golden_v0.jsonl` (25 answerable questions, 34 gold sections).
Each run used the same cached query embeddings, concurrent dense and FTS5 retrieval,
RRF with `k=60`, nine candidate children per retriever, then the top three distinct
parents. Parent text was mapped back to gold Markdown sections.

The settings were 600/125, 800/175, and 1000/225 approximate tokens for
parent/child. The token estimate is consistently four characters per token. Prompt
tokens below count the assembled user prompt, including retrieved text, source labels,
the question, and prompt framing; they exclude the fixed system prompt.

## Results

| Parent / child target | Parents indexed | Child chunks | Recall@3 | Evidence hit rate | Approx. prompt tokens mean / median |
|---:|---:|---:|---:|---:|---:|
| 600 / 125 | 254 | 330 | 0.287 | 32% (8/25) | 454.8 / 422.5 |
| **800 / 175** | **254** | **274** | **0.333** | **40% (10/25)** | **435.4 / 408.5** |
| 1000 / 225 | 254 | 265 | 0.373 | 44% (11/25) | 445.1 / 425.5 |

Recall@3 is macro-averaged section recall over the 25 answerable questions. Evidence
hit rate is the share of answerable questions with at least one gold section in the
retrieved parent context. It is a retrieval proxy: this experiment did not generate
answers or verify model-written citations.

## Decision

Keep **800/175** as the default. The 1000/225 setting scored 0.040 higher macro
Recall@3 and found evidence for one more answerable question, but used about 10 more
approximate prompt tokens on average. That is a small difference on a 25-question set;
800/175 also stays within the planned 150–200 child-token range. The 1000/225 setting
indexed 9 fewer children, so its index is marginally smaller; the measured prompt
cost and small-set uncertainty favor retaining 800/175 for now.

All three settings produced 254 parents. On this corpus, heading-defined sections
already fit under the tested parent targets, so the results mainly distinguish child
size; they do not show a meaningful parent-size effect. The golden set is small, and
the 4-point evidence difference is one question. Keep the choice provisional and
recheck it on the larger baseline-v2 set after corpus or chunking changes.

## Reproduction

Run from the project root:

```powershell
uv run python evals/compare_chunking.py
```

The script caches each question embedding across settings, stores local indexes under
the Git-ignored `chroma_db_chunking/`, and writes per-question outcomes to
`results/chunking_comparison.csv`. It reuses unchanged indexes on a later run.
