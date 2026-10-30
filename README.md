# AegisFlow

AegisFlow is a local-first retrieval-augmented generation (RAG) prototype for answering questions over a synthetic service-incident corpus. The current work focuses on hybrid retrieval, parent-child chunking, cited answers, evidence sufficiency, abstention, and repeatable evaluation. It is not yet a general workflow engine or tool-using agent platform.

## Current pipeline

1. **Ingest:** parse Markdown, text, logs, and HTML; split Markdown into heading-aware parent passages and smaller child matches; embed children with Ollama; store vectors in Chroma and text/parent metadata in SQLite FTS5.
2. **Retrieve:** run dense and lexical search concurrently, merge their rankings with reciprocal-rank fusion (RRF, constant 60), hydrate parent passages, and retain the matched child excerpt.
3. **Verify and answer:** apply initial retrieval gates (maximum RRF score 0.015 and best cosine distance 0.82), then ask Qwen 3.5 4B whether the matched evidence is sufficient. If not, return an abstention with missing information. If sufficient, Gemma 3 4B generates structured claims with validated evidence IDs.
4. **Serve:** FastAPI provides `/health`, `/ready`, and `/ask`. Ask responses include `answer`, `sources`, `citations`, `abstained`, and `missing`.

These score cutoffs are starting points, not calibrated production thresholds. The verifier's full E2 evaluation is currently blocked by slow/stalled local inference; see [ADR-003](docs/ADR-003-abstention-and-grader.md).

## Corpus and golden set

- `data/corpus/` contains 27 synthetic Markdown documents: service descriptions, runbooks, postmortems, and incident logs.
- `data/eval/golden_v0.jsonl` contains 41 questions: 20 single-hop, 5 multi-part, 10 unanswerable, and 6 conflicting-document cases.
- Gold sources identify document and heading rather than chunk IDs so they remain useful after chunking changes.

The current default ingestion input is `docs/rag_samples/`; explicitly pass `data/corpus` for corpus experiments. Example:

```powershell
uv run python -m aegisflow.rag.ingest --docs data/corpus --store chroma_db_w3
```

The `chroma_db_w3/` index is local and ignored by Git. It contains 254 parent passages and 274 child matches for the current corpus/configuration. Rebuild it with the command above when the index is absent or stale.

## Run retrieval evaluation

With Ollama running and the corpus index built:

```powershell
uv run eval-retrieval --dataset data/eval/golden_v0.jsonl --corpus data/corpus --store chroma_db_w3 --k 3
```

This reports section-level Recall@k, MRR, and nDCG for dense, lexical, and fused retrieval. The earlier dense-versus-hybrid retrieval experiment is documented in [ADR-002](docs/ADR-002-hybrid-retrieval.md), with per-question data in `results/E1_retrieval_comparison.csv`.

## Run answer evaluation

Run E1 without the verifier and E2 with it, using the same dataset, index, `k`, and repetition count:

```powershell
uv run python evals/run_eval.py --dataset data/eval/golden_v0.jsonl --runs 1 --k 3 --store chroma_db_w3 --no-verifier --output results/baseline_E1_answer.csv
uv run python evals/run_eval.py --dataset data/eval/golden_v0.jsonl --runs 1 --k 3 --store chroma_db_w3 --output results/baseline_E2_answer.csv
```

When both result files exist, summarize abstention, citation precision/recall, threshold tradeoffs, and create a 20-answer human-review sheet:

```powershell
uv run python evals/report_answer_quality.py --e1 results/baseline_E1_answer.csv --e2 results/baseline_E2_answer.csv
```

To summarize the currently available E1 result only:

```powershell
uv run python evals/report_answer_quality.py --e1 results/baseline_E1_answer.csv --output results/baseline_E1_answer_quality.json
```

The report's retrieval evidence-hit rate is a correctness proxy, not a human correctness grade. Enter binary human labels in `results/judge_human_review.csv` after it is generated, then rerun the report to calculate raw agreement and Cohen's kappa.

## Recorded answer results

The full E1 run completed all 41 questions: 30 generations succeeded and 11 failed structured-answer validation after retry. Source Recall@3 was 0.500; median per-question latency was 19.482 seconds and P95 was 46.261 seconds. Without the verifier, the generator abstained on 8/10 unanswerables and 0/31 answerables. Citation precision/recall were 0.200/0.111 using exact source-heading matches.

At the initial RRF cutoff of 0.015, the score gate alone still accepted every tuning-set unanswerable and 80% of the held-out unanswerables. The measured tuning/held-out curve is in [abstention_tradeoff.svg](results/abstention_tradeoff.svg); numbers and run configuration are in `results/baseline_E1_answer_quality.json` and `results/baseline_v2_config.json`.

The 41-question E2 run and two 20-question retries did not produce output CSVs because local inference stalled. E2 verifier performance, citation metrics, and judge-human agreement are therefore not measured yet. The recorded E1 refusal rate is not verifier performance.

## API response shape

A verified answer returns structured, server-validated citation references. If evidence is insufficient, the response includes an explicit refusal and a short `missing` list, for example:

```json
{
  "answer": "I can't answer this reliably from the available evidence. Missing: current live metrics",
  "sources": [],
  "citations": [],
  "abstained": true,
  "missing": ["current live metrics"]
}
```

The FastAPI application object is `aegisflow.api:app`. Health and readiness behavior, request bounds, timeouts, and safe error mapping are implemented in [api.py](src/aegisflow/api.py).

## Development checks

```powershell
uv run python -m pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src
```

The last recorded verification passed 105 tests, Ruff, and mypy across 19 source files. The project manifest currently declares FastAPI but does not yet declare every runtime package imported by the application (including ChromaDB); a clean-environment dependency audit remains necessary.

## Project notes

- [Problem statement](docs/problem-statement.md)
- [Hardware and model notes](docs/hardware.md) and [model comparison](docs/model_comparison.md)
- [Chunking experiment](docs/chunking.md)
- [ADR-002: hybrid retrieval](docs/ADR-002-hybrid-retrieval.md)
- [ADR-003: abstention and grader calibration](docs/ADR-003-abstention-and-grader.md)
- [W3 D4-D6 devlog](devlog/W3_D4-D6.md)
