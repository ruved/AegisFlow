# AegisFlow

A local-first AI engineering learning project. Week 1 builds a small RAG service,
creates a synthetic incident corpus and golden question set, and records an
initial evaluation. The repository currently implements a FastAPI RAG prototype;
the broader stateful agent-orchestration platform is still a project goal.

## Week 1 — Foundations, model spike, corpus, baseline

**Week goal:** establish a working RAG baseline and record first measured results.

**Week review:** the problem definition, local model comparison, 27-document
corpus, 30-question golden set, API, RAG modules, and evaluation runner are in the
repository. The measured E0 run completed, but its Chroma collection contains two
sample chunks rather than the `data/corpus` documents expected by the golden set.
So the pipeline and measurement are real, while corpus-level retrieval quality is
not yet established. The daily notes below distinguish shipped work from gaps.

### W1 D1 — Problem statement and environment

**Goal:** define the user problem and make the Python project buildable and
checkable.

**What is in the repository:**

- [docs/problem-statement.md](docs/problem-statement.md) identifies backend
  engineers as the user, describes workflow reliability and debugging pain, and
  defines success metrics for workflow success, latency, and trace coverage.
- Python is pinned to 3.12 in [.python-version](.python-version). Dependency
  metadata and the lockfile are in [pyproject.toml](pyproject.toml) and
  [uv.lock](uv.lock); Ruff, mypy, pytest, and pre-commit are configured.
- The [Makefile](Makefile) provides `make test`, `make lint`, `make eval`, and
  `make format`. Here, `make eval` runs the test suite; it does not run the
  golden-set model evaluation.
- [.pre-commit-config.yaml](.pre-commit-config.yaml) runs Ruff lint, Ruff format
  check, mypy, and pytest before commits.
- [docs/hardware.md](docs/hardware.md) records Windows 11, Python 3.12.4, an
  Intel i7-1360P, 13.73 GB RAM, and integrated Intel Iris Xe graphics. Dedicated
  VRAM/GPU use, runtime memory, and repeatable latency were not verified in that
  hardware note.

**What we learned / tradeoffs:** a lockfile makes installs more repeatable, and
pre-commit catches mistakes before they reach Git; both add tooling to learn and
can slow early commits. Local inference avoids a hosted API but makes model
quality and latency depend on the available machine.

**Status:** core setup and problem statement exist. The hardware note still marks
GPU, memory, and some runtime measurements as unverified.

### W1 D2 — Model spike

**Goal:** measure what the local machine can run and choose initial chat and
embedding models.

**What is in the repository:** [docs/model_comparison.md](docs/model_comparison.md)
records three-trial chat comparisons, an embedding check, a two-request
concurrency experiment, and a context-size comparison. The recorded chat results
were:

| Model | Median latency | Median generation speed | Structured outputs |
| --- | ---: | ---: | ---: |
| Gemma 3 4B | 4.97 s | 13.76 tokens/s | 3/3 |
| Qwen 3.5 4B Q4_K_M | 6.57 s | 11.75 tokens/s | 3/3 |
| Llama 3.1 8B | 6.47 s | 8.15 tokens/s | 3/3 |

The embedding sample used `nomic-embed-text:latest`, took 3.81 seconds, and
returned 768 dimensions. The initial configuration selects `gemma3:4b`,
`nomic-embed-text:latest`, and a 4096-token context in
[config.py](src/aegisflow/config.py).

**What we learned / tradeoffs:** smaller models use fewer resources and were
faster in this small spike, but this is not a broad reasoning-quality result.
The Qwen settings differed from the other chat models. The concurrency run was
slow, and the report warns that its sampled memory values may not represent total
model memory. Treat these as initial measurements, not production capacity claims.

**Status:** model decision and measurements are documented; GPU acceleration and
representative workflow quality still need validation.

### W1 D3 — Corpus v0

**Goal:** create realistic source material with distinct incidents, evidence
types, and conflicting guidance.

**What is in the repository:** [data/corpus/services.md](data/corpus/services.md)
indexes **27 Markdown files**: service architecture and dependency notes, seven
runbooks, eight postmortems, and two incident logs. It includes an explicitly
outdated database-pool runbook to test version and conflict awareness.

**What we learned / tradeoffs:** hand-authored synthetic material gives control
over incident details and avoids using model-written gold answers, but it takes
time to create. A varied corpus needs both direct evidence and distractors; a
retrieval score is meaningful only when queries and expected sources match the
indexed corpus.

**Status:** corpus v0 and its index exist. These documents are not the same as the
two sample documents currently in the default Chroma collection; see W1 D6.

### W1 D4 — Golden set v0

**Goal:** make a fixed, version-controlled set of questions to measure retrieval
and answer quality.

**What is in the repository:** [data/eval/golden_v0.jsonl](data/eval/golden_v0.jsonl)
contains 30 records: 20 single-hop, 5 multi-part, and 5 unanswerable. Each record
has an ID, question, key facts, expected document-and-section sources, and
difficulty. [test_golden_set.py](tests/test_golden_set.py) checks the schema,
distribution, unique IDs, source documents, and exact section headings.

**What we learned / tradeoffs:** source labels use document and section instead of
chunk IDs, so they survive later re-chunking but score more coarsely. The gold
answers are key facts rather than full reference paragraphs. The tests establish
dataset integrity; by themselves, they do not measure RAG quality.

**Status:** dataset and validation tests exist. Key facts still need human
application when grading generated answers.

### W1 D5 — Baseline RAG (E0)

**Goal:** connect ingestion, embeddings, vector search, and one grounded answer
generation call.

**What is in the repository:**

1. [ingest.py](src/aegisflow/rag/ingest.py) finds Markdown/text documents and
   passes them to fixed character windows in
   [chunking.py](src/aegisflow/rag/chunking.py) (800 characters, 100 overlap).
2. [embeddings.py](src/aegisflow/rag/embeddings.py) calls local Ollama using
   `nomic-embed-text:latest`.
3. [vector_store.py](src/aegisflow/rag/vector_store.py) persists explicit vectors
   in Chroma and searches with cosine distance.
4. [retrieval.py](src/aegisflow/rag/retrieval.py) embeds the question and returns
   dense top-k chunks.
5. [generation.py](src/aegisflow/rag/generation.py) sends retrieved context to
   `gemma3:4b` for one grounded response and includes source filenames. Empty
   retrieval returns an insufficient-evidence answer without generation.

**Important current gap:** ingestion defaults to `docs/rag_samples/`, which has
two sample Markdown documents. It does not default to `data/corpus/`. Ingestion
uses upsert but does not remove obsolete chunks when a source is deleted or
chunking changes. The collection used for E0 had only two chunks from
`architecture.md` and `ingestion.md`.

**CLI status:** the modules can be run directly:

```powershell
uv run python -m aegisflow.rag.ingest
uv run python -m aegisflow.rag.generation "question"
```

The planned `make ingest` and `make ask Q="..."` targets are not in the current
Makefile, and the configured `aegisflow` console command still prints a
placeholder greeting. Those workflows are not complete yet.

**What we learned / tradeoffs:** embeddings map text to vectors and cosine search
ranks nearby vectors; fixed windows are simple but can split ideas. Chroma is
local and easy to run, but dense retrieval can miss exact terms. The collection
checks its embedding model to avoid querying vectors built with a different
model.

**Status:** the RAG path works against the sample index. Full-corpus ingestion and
the requested Make/console workflows remain follow-up work.

### W1 D6 — Evaluation runner and baseline E0

**Goal:** repeatedly evaluate golden questions and record first measured
retrieval, latency, and token results.

**What is in the repository:** [evals/run_eval.py](evals/run_eval.py) invokes the
existing generation/retrieval path directly; it does not require the FastAPI
server. It defaults to three runs and `k=3`, writes one row per question to
[results/baseline_E0.csv](results/baseline_E0.csv), and records retrieved chunks,
source lists, per-run latency/failure details, and provider token usage when
available. Manual correctness fields start blank and are preserved when the CSV
is regenerated. Details and grading rubric: [devlog/W1_D6.md](devlog/W1_D6.md).

**Measured run:** `uv run python evals/run_eval.py --runs 3 --k 3`

| Metric | Result |
| --- | ---: |
| Questions / repetitions | 30 / 3 |
| Successful questions / failed runs | 30 / 0 |
| Mean source Recall@3 | 0.000 (25 eligible; 5 no-gold-source questions excluded) |
| Median across per-question median latency | 6,790.953 ms |
| P95 across per-question median latency | 13,040.563 ms |
| Average prompt / completion tokens | 287.167 / 33.067 |
| Manually graded answers | 0 |

**Interpretation:** the zero Recall@3 is expected for the collection that was
actually evaluated: all questions retrieved the same two sample sources, while
the gold set expects material from `data/corpus`. A representative Order Service
answer said the evidence was insufficient. The run proves the evaluation path
works; it does not establish retrieval quality over the full synthetic corpus.
Latency includes query embedding, Chroma retrieval, and generation. The first run
is included and can be affected by model loading. Model output and timing are not
deterministic.

**Status:** baseline CSV and measured devlog entry exist. Correctness remains
ungraded by a human or automated judge.

## Current API

- `GET /health` is process liveness and does not contact dependencies.
- `GET /ready` checks bounded Ollama and Chroma availability without model
  inference; it returns `503` when a dependency is unavailable.
- `POST /ask` accepts a non-empty question up to 4,000 characters and optional
  `top_k` from 1 through 10 (default 3).

Ollama request timeouts are 30 seconds for embeddings, 120 seconds for chat, and
2 seconds for readiness. API errors map invalid requests to `422`, unavailable
dependencies to `503`, inference timeouts to `504`, invalid dependency responses
to `502`, and configuration or unexpected failures to safe `500` responses.
Logs do not include full user questions or retrieved passages.

Example local API requests:

```powershell
curl.exe http://localhost:8000/health
curl.exe http://localhost:8000/ready
curl.exe -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"How does AegisFlow work?","top_k":3}'
```

## Run evaluation

From the repository root, with Ollama running and the selected Chroma collection
available:

```powershell
uv run python evals/run_eval.py
```

Defaults are `data/eval/golden_v0.jsonl`, three repetitions, `k=3`, the existing
`chroma_db` collection, and `results/baseline_E0.csv`. Options include
`--runs`, `--k`, `--dataset`, `--output`, and `--store`. The runner returns a
nonzero status for invalid datasets or failed evaluation runs. Recall is
source-level, not chunk-level recall. It does not automatically score the
semantic correctness of generated answers.

## Week review and next steps

The biggest gap is that the existing index does not contain the corpus used to
write the golden sources. First ingest `data/corpus` into a separate Chroma store
so the current local index remains untouched, then rerun E0 with the same models,
`k`, and repetitions. Compare Recall@3 and manually grade answers against their
retrieved evidence. After establishing that comparable baseline, the next planned
retrieval experiment is lexical search (for example FTS5) alongside dense search.

The project is still a RAG/API prototype: a general stateful workflow engine,
tool execution, and trace coverage from the original problem statement are not
implemented yet.
