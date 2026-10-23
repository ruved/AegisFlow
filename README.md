# \# AegisFlow

# 

# AI Agent Orchestration Platform

# 

# A stateful platform for orchestrating AI agents, executing tools safely, tracing workflows, and evaluating results.

## API health and error behavior

- `GET /health` is a liveness check for the API process. It does not contact dependencies.
- `GET /ready` performs bounded checks of local Ollama and Chroma availability without running embeddings or generation. It returns `200` when both are available and `503` with per-dependency statuses otherwise.
- `POST /ask` accepts a non-empty question up to 4,000 characters and optional `top_k` from 1 through 10 (default 3).

Ollama requests use socket timeouts configured in `src/aegisflow/config.py`: 30 seconds for embeddings, 120 seconds for chat generation, and 2 seconds for readiness. API errors use safe messages: validation `422`, unavailable local dependencies `503`, inference timeout `504`, invalid dependency response `502`, service configuration failure `500`, and unexpected errors `500`. Diagnostic logs omit submitted questions and retrieved content.

Example requests:

```powershell
curl.exe http://localhost:8000/health
curl.exe http://localhost:8000/ready
curl.exe -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"How does AegisFlow work?","top_k":3}'
```

## Golden-set evaluation (baseline E0)

Run the checked-in 30-question dataset directly through the local RAG services (no
FastAPI server is required):

```powershell
uv run python evals/run_eval.py
```

The default run performs three complete RAG calls per question with `k=3`, using
`data/eval/golden_v0.jsonl` and the existing `chroma_db` collection. Override the
repetitions, retrieval depth, dataset, output file, or collection path with
`--runs`, `--k`, `--dataset`, `--output`, and `--store`. For example:

```powershell
uv run python evals/run_eval.py --runs 3 --k 3
```

The runner writes `results/baseline_E0.csv`, with one sorted row per question,
full retrieved chunks, per-run outcomes, median latency, source-level Recall@k,
and provider token counts only when Ollama supplies them. Latency includes query
embedding, Chroma retrieval, and generation; the first run may include model
loading. Failed runs remain in the CSV and cause a nonzero exit status. Empty
gold-source questions are excluded from mean Recall@k. Recall is source-level,
so it does not measure the proportion of expected chunks or facts retrieved.

Answer correctness is intentionally not auto-graded. Fill in
`key_facts_covered`, `correctness_grade`, and `correctness_notes` in the CSV after
reviewing the answer and evidence. Grades use a 0–5 rubric: 0 incorrect or
unsupported; 1 mostly incorrect; 2 partly correct with important omissions; 3
mostly correct with minor omissions; 4 covers the expected key facts; 5 complete
and appropriately grounded. Reruns preserve those manual grading columns for
matching question IDs. The baseline is local and repeatable in configuration,
but model output and latency are not guaranteed to be deterministic.

