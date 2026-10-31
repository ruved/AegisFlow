# AegisFlow

AegisFlow is a local-first retrieval-augmented generation (RAG) prototype for answering questions over a synthetic service-incident corpus. The current work focuses on hybrid retrieval, parent-child chunking, cited answers, evidence sufficiency, abstention, and repeatable evaluation. It now includes a bounded typed multi-step workflow for experiments, but it is not a general workflow engine or tool-using agent platform.

## Current pipeline

1. **Ingest:** parse Markdown, text, logs, and HTML; split Markdown into heading-aware parent passages and smaller child matches; embed children with Ollama; store vectors in Chroma and text/parent metadata in SQLite FTS5.
2. **Retrieve:** run dense and lexical search concurrently, merge their rankings with reciprocal-rank fusion (RRF, constant 60), hydrate parent passages, and retain the matched child excerpt.
3. **Verify and answer:** apply initial retrieval gates (maximum RRF score 0.015 and best cosine distance 0.82), then ask Qwen 3.5 4B whether the matched evidence is sufficient. If not, return an abstention with missing information. If sufficient, Gemma 3 4B generates structured claims with validated evidence IDs.
4. **Serve:** FastAPI provides `/health`, `/ready`, `/ask`, and a persistent run API at `/v1/runs`. Run records, replayable SSE events, cancellation, and recovery are described in [recovery.md](docs/recovery.md).

The experimental LangGraph path separates planning, retrieval, evidence-only analysis, reporting, verification, and bounded retry/abstention. `RunState` is a `TypedDict`; each model node validates its JSON result with Pydantic. JSON logs carry `run_id`, node duration, reported or estimated token counts, and cache status. Workflow callers use `aegisflow.workflow.run_workflow`; LangGraph assembly stays in `workflow/graph.py`.

These score cutoffs are starting points, not calibrated production thresholds. The verifier's full E2 evaluation is currently blocked by slow/stalled local inference; see [ADR-003](docs/ADR-003-abstention-and-grader.md).

## Week 4 workflow and E4 evaluation

Run the bounded workflow for one question (Ollama and the W3 index must be available):

```powershell
uv run python -c "from aegisflow.workflow import run_workflow; print(run_workflow({'question': 'What caused the payment timeout?', 'store_path': 'chroma_db_w3'})['report'])"
```

Run the baseline-vs-workflow E4 evaluation on all 41 golden questions. Each completed case is saved immediately, so partial runs remain inspectable:

```powershell
uv run python evals/run_e4.py --store chroma_db_w3 --output results/E4_workflow.csv
```

Measure planner schema validity on the deterministic 15-question planning sample (10 single-hop and 5 multi-part):

```powershell
uv run python evals/evaluate_planner.py --model gemma3:4b
```

For a clearly labeled pilot or slice, pass `--limit N` or `--slice unanswerable`. The runner reports planner schema-valid rate, task completion (for unanswerables, a supported abstention counts as completion), citation precision/recall against gold source headings, abstention by dataset slice, latency, and per-node time/token breakdown. `results/E4_workflow.json` records the model and run budgets; CSV telemetry contains the per-node event details. Compare E4 completion and latency with matching IDs from the saved E1 CSV. The run and keep/drop decision are recorded in [ADR-004](docs/ADR-004-e4-workflow.md); a subset is a pilot, not a full-set result.

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

## Recorded Week 4 results

The planner-only check returned schema-valid, bounded plans on 15/15 questions (10 single-hop and 5 multi-part) with Gemma 3 4B; mean latency was 9.06 seconds. The end-to-end E4 pilot used three answerable and three unanswerable questions. It completed 0/3 answerable cases by gold-source citation and correctly abstained on 2/3 unanswerable cases. Its median latency was 92.3 seconds versus 28.1 seconds for the same E1 questions. See [ADR-004](docs/ADR-004-e4-workflow.md) for per-node timings, the decision, and limitations. The 41-question E4 run remains unmeasured; the pilot median projects about 63 minutes of local inference.

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

## Week 5: Run lifecycle and recovery

Start the API and create a managed workflow with an idempotency key:

```powershell
uv run uvicorn aegisflow.api:app
curl.exe -X POST http://127.0.0.1:8000/v1/runs -H "Content-Type: application/json" -H "Idempotency-Key: demo-1" -d '{"question":"What caused the payment timeout?","top_k":3}'
curl.exe -N http://127.0.0.1:8000/v1/runs/<run-id>/events
curl.exe http://127.0.0.1:8000/v1/runs/<run-id>
```

The same idempotency key returns the original run. Events have persistent sequence IDs and can be replayed with `Last-Event-ID`. Cancel a run with `POST /v1/runs/<run-id>/cancel`; resume a failed or cancelled run with `POST /v1/runs/<run-id>/resume`. Run records/events persist at `runtime/runs.sqlite3`; LangGraph checkpoints persist at `runtime/checkpoints.sqlite3`.

Recovery resumes from the last graph checkpoint and provides **at-least-once** execution: a node interrupted before its checkpoint can run again. Cancellation is cooperative, so a model request already in flight may finish before the run stops. SQLite is for a single local process. The tests cover idempotency, SSE reconnect replay, checkpoint resume after an injected retrieval failure, and cancellation before retrieval. The full six-scenario repeated fault campaign and captured crash-resume screencast remain outstanding. See [the recovery guide](docs/recovery.md) for the reproduction steps and guarantees.

Week 5 verification: 117 pytest tests passed; Ruff lint/format checks and mypy passed.

## Development checks

```powershell
uv run python -m pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src
```

The Week 4 verification passed 112 tests, Ruff lint and format checks, and mypy across 28 source files. `pyproject.toml` declares FastAPI, ChromaDB, and LangGraph as runtime dependencies.

## Project notes

- [Problem statement](docs/problem-statement.md)
- [Hardware and model notes](docs/hardware.md) and [model comparison](docs/model_comparison.md)
- [Chunking experiment](docs/chunking.md)
- [ADR-002: hybrid retrieval](docs/ADR-002-hybrid-retrieval.md)
- [ADR-003: abstention and grader calibration](docs/ADR-003-abstention-and-grader.md)
- [ADR-004: typed workflow and E4 results](docs/ADR-004-e4-workflow.md)
- [W4 D1-D6 devlog](devlog/W4_D1-D6.md)
- [W3 D4-D6 devlog](devlog/W3_D4-D6.md)
