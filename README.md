# AegisFlow (v0.1 — Milestone 1)

**Model proposes; executor enforces; automated tests verify.**

AegisFlow is a local-first retrieval-augmented generation (RAG) and secure tool-using agent service for answering questions over a synthetic service-incident corpus. Milestone 1 (v0.1) delivers a shippable, secure tool-execution boundary with declarative policy enforcement, untrusted content delimitation, hashed audit logging, and an automated adversarial red-team evaluation suite.

---

## Architecture & Principles

AegisFlow establishes strict enforcement boundaries between untrusted components (model proposals, user inputs, retrieved corpus data) and execution:

```
┌─────────────────┐      Proposal      ┌────────────────────────────────────────────────────────┐
│  Model / LLM    │ ─────────────────> │               Central Tool Executor                    │
└─────────────────┘                    ├───────────┬──────────┬─────────┬───────────┬───────────┤
                                       │ Validate  │  Policy  │ Timeout │  Execute  │   Audit   │
                                       │ (Schema)  │ (Perms)  │ (Bound) │ (Handler) │ (Hashed)  │
                                       └───────────┴──────────┴─────────┴───────────┴───────────┘
```

1. **Typed Tool Registry (D1):** Tools are declared with strict Pydantic schemas (`extra="forbid"`), explicit risk levels (`low`, `high`), bounded timeouts (1.0–2.0s), and human approval flags (`requires_approval`). Unregistered tools and malformed arguments are rejected before execution.
2. **Centralized Policy & Audit (D2):** A single execution flow (`validate → policy → timeout → execute → audit`). Sensitive data and raw arguments are never persisted; calls are audited with SHA-256 argument digests, timestamps, decisions, and outcomes.
3. **Untrusted Content & Prompt Injection Defense (D3):** Retrieved documents and tool outputs are treated strictly as untrusted data, enclosed in `<UNTRUSTED_EVIDENCE>` delimiters, and flagged for instruction-like patterns without breaking legitimate runbooks. Tool permissions are enforced outside the prompt boundary.
4. **Automated Adversarial Red Team (D4):** Rate-based security suite testing 20 injection documents, 10 malicious argument variations, and 5 resource exhaustion prompts across 5 repetitions (175 total trials) with **0 policy bypasses**.
5. **Threat Model & Redaction (D5):** Complete mapping of OWASP Top 10 for Agentic Applications 2026 ([docs/threat_model.md](docs/threat_model.md)), pattern-based PII/secret log redaction, and API-key authentication (`X-API-Key`).
6. **Reproducible Demo & Tests (D6):** Full test suite with 126 tests passing, a 2-minute demo runner ([scripts/demo.py](scripts/demo.py)), and walkthrough ([docs/demo.md](docs/demo.md)).

---

## Quickstart & Setup

### Prerequisites
- Python 3.12+
- [uv](https://github.com/astral-sh/uv) (recommended package manager)
- (Optional) [Ollama](https://ollama.ai/) with `gemma3:4b` and `qwen2.5:3b` for live local LLM inference.

### Installation

```bash
git clone https://github.com/aegisflow/aegisflow.git
cd aegisflow
uv sync
```

Copy the environment configuration:

```bash
cp .env.example .env
```

To configure API key authentication for non-loopback clients:
```bash
# In .env or shell:
export AEGISFLOW_API_KEY="your-secret-api-key"
```

---

## Execution & How to Inspect a Cited Answer

### 1. Interactive 2-Minute Demo
Run the self-contained demonstration covering tool registry validation, policy enforcement, audit logs, injection mitigation, and cited answers:

```bash
uv run python scripts/demo.py
```
*(Add `--fast` for instant execution without pacing delays).*

### 2. Start the API Server
Launch the FastAPI application:

```bash
uv run uvicorn aegisflow.api:app --reload --port 8000
```

### 3. Inspect a Cited Answer (`POST /ask`)
Query the service to retrieve evidence and generate an answer with validated citations:

```bash
curl.exe -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"What caused the payment timeout?","top_k":3}'
```

Example verified response:
```json
{
  "answer": "The payment service timed out due to connection pool exhaustion after order-db failover [EV-001].",
  "sources": ["data/corpus/postmortems/incident-2024-03-12.md"],
  "citations": [
    {
      "claim": "The payment service timed out due to connection pool exhaustion",
      "evidence_id": "EV-001",
      "source": "incident-2024-03-12.md",
      "heading": "Root Cause"
    }
  ],
  "abstained": false,
  "missing": []
}
```

If evidence is insufficient, AegisFlow abstains honestly:
```json
{
  "answer": "I can't answer this reliably from the available evidence. Missing: current live metrics",
  "sources": [],
  "citations": [],
  "abstained": true,
  "missing": ["current live metrics"]
}
```

### 4. Propose and Execute Tools Centrally (`POST /v1/tools/propose`)
Ask the model to select a tool from the registry to address a goal:

```bash
curl.exe -X POST http://127.0.0.1:8000/v1/tools/propose \
  -H "Content-Type: application/json" \
  -d '{"goal":"Find logs about database pool exhaustion"}'
```

The proposal is re-validated through the central executor. If arguments are invalid, 1 retry is allowed. High-risk write tools (`simulate_write`) are denied unless explicit approval is provided by the host.

### 5. Persistent Workflows & Replay (`/v1/runs`)
Create a persistent, cancellable, checkpointed workflow run:

```bash
curl.exe -X POST http://127.0.0.1:8000/v1/runs \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: demo-run-1" \
  -d '{"question":"What caused the payment timeout?","top_k":3}'

# Stream real-time events:
curl.exe -N http://127.0.0.1:8000/v1/runs/<run-id>/events

# Inspect run status:
curl.exe http://127.0.0.1:8000/v1/runs/<run-id>
```

---

## Tool Registry & Security Details (Week 6)

### Registered Tools
| Tool | Risk | Timeout | Approval Required | Purpose |
|---|---|---|---|---|
| `search_logs` | `low` | 2.0s | `False` | Search incident logs for matching terms within path bounds. |
| `fetch_runbook` | `low` | 2.0s | `False` | Fetch verified runbook by ID (`RB-xxx`). Directory traversal rejected. |
| `get_service_deps` | `low` | 1.0s | `False` | Return dependency graph for a named service. |
| `query_metrics` | `low` | 1.0s | `False` | Return simulated service metrics (`latency_p95_ms`, `error_rate_pct`, `db_connections`). |
| `simulate_write` | `high` | 1.0s | `True` | Preview a configuration change; denied unless host grants approval. |

### Declarative Policy Configuration (`policy.yaml`)
Operator-level allow/deny rules, execution budgets, and approval overrides can be configured declaratively in `policy.yaml` without changing application code:
- **Global call ceiling:** `max_total_calls` hard budget per executor instance to prevent runaway loops or DoS attacks.
- **Per-tool controls:** `enabled: false` completely disables specific tools; `max_runs` sets per-tool invocation limits.
- **Approval overrides:** `require_approval_override: true` elevates low-risk tools to require explicit human approval.

### Automated Red Team Suite
Run the automated adversarial red-team suite:

```bash
# 1. Deterministic executor-level evaluation (default, CI safe):
uv run python evals/run_red_team.py --runs 5

# 2. Model-in-the-loop evaluation (requires Ollama):
uv run python evals/run_red_team.py --model-loop --model gemma3:4b --runs 1
```

Results are saved to [results/red_team_week6.json](results/red_team_week6.json):
- **100 Injection document attempts** (20 unique injection templates x 5 runs)
- **50 Malicious argument attempts** (10 boundary/traversal payloads x 5 runs)
- **25 Resource exhaustion attempts** (5 oversized/nested inputs x 5 runs)
- **Total proposals tested:** 175
- **Observed policy bypasses:** **0 (0.0% bypass rate)**
- **Report separation:** In model-loop mode, text-level compliance (whether the model yielded to injection) is reported separately from actual executor bypasses (which remain 0).

Audit entries for all attempts are recorded in `runtime/tool_audit_redteam.sqlite3` with SHA-256 argument hashes only.

### Threat Model
The full threat model is documented in [docs/threat_model.md](docs/threat_model.md), mapping controls against the OWASP Top 10 for Agentic Applications 2026:
- **ASI01 Agent Goal Hijack:** Prompt delimiters `<UNTRUSTED_EVIDENCE>` and executor-level authorization boundary.
- **ASI02 Tool Misuse & Exploitation:** Allowlisted typed registry, Pydantic strict validation, risk levels, human approval gates.
- **ASI03 Identity & Privilege Abuse:** API-key auth via `X-API-Key`, process runs with least privilege local identity.
- **ASI05 Unexpected Code Execution:** Zero arbitrary shell or code execution tools.
- **ASI08 Cascading Failures:** Step, token, deadline, per-request, and per-tool timeout budgets.

---

## Observability, UI & CI Quality Gates (Milestone 2)

### OpenTelemetry Distributed Tracing
AegisFlow instruments one coherent trace per run using standard GenAI semantic conventions:
- **Spans:** workflow run root (`trace_workflow_run`), workflow nodes (`trace_node`), structured LLM calls (`trace_llm_call`), hybrid retrieval (`trace_retrieval`), and tool executions (`trace_tool_execution`).
- **Semantic Attributes:** `gen_ai.request.model`, `gen_ai.usage.prompt_tokens`, `gen_ai.usage.completion_tokens`, `gen_ai.usage.total_tokens`, `tool.decision`, `tool.outcome`.
- **Trace Inspection Endpoint:**
  ```powershell
  curl -H "X-API-Key: test-secret-key-12345" http://127.0.0.1:8000/v1/runs/<run_id>/trace
  ```
  Returns a hierarchical tree with nested spans, durations, statuses, and GenAI token usage.

### Prometheus Metrics & Grafana Dashboard
Real-time system health metrics are exposed at `/metrics` (exempt from API key auth for scrapers):
- **Node Latency:** `aegisflow_node_duration_seconds` (histogram with buckets tuned from production latency data).
- **Concurrency & Queues:** `aegisflow_active_runs` and `aegisflow_queue_depth` (gauges).
- **Usage & Retries:** `aegisflow_tokens_total` (counter by model and token type), `aegisflow_workflow_retries_total` (counter by node), `aegisflow_cache_hits_total`, and `aegisflow_errors_total`.
- **Tool Decisions:** `aegisflow_tool_calls_total` and `aegisflow_tool_duration_seconds`.
- **Cardinatily Guarantee:** Strictly low-cardinality labels (zero `run_id` or question text in Prometheus label sets).
- **Dashboard:** Ready-to-import Grafana dashboard JSON available at [docs/grafana_dashboard.json](docs/grafana_dashboard.json).

### Streamlit Web Console
Launch the interactive web console:
```powershell
uv run streamlit run ui/app.py
```
- **Live Execution Tab:** Submit incident queries, adjust `top_k`, watch real-time node timeline with status badges, and trigger early cancellations.
- **Report & Evidence Panel:** Displays diagnosis, unknowns, and risk-labelled remediation steps (`[LOW]`, `[MEDIUM]`, `[HIGH]`). Clicking any cited claim highlights the exact supporting passage with character offsets computed relative to normalized text (eliminating highlight drift).
- **Run Inspector Tab:** Inspect hierarchical OpenTelemetry span trees with live durations and GenAI token breakdowns.
- **Tool Sandbox Tab:** Interactively test model tool proposals against the central execution boundary.

### CI Quality & Evaluation Gates
Automated GitHub Actions pipeline ([.github/workflows/ci.yml](.github/workflows/ci.yml)) protects against code and quality regressions:
- **Stages:** Linting (`ruff check`) → Formatting check (`ruff format --check`) → Static typecheck (`mypy src`) → Unit test suite (`pytest -v`) → CI Evaluation Gate (`evals/ci_eval_gate.py`).
- **GPU-Independent CI:** Evaluates pre-recorded fixture subset ([tests/fixtures/ci_eval_fixtures.json](tests/fixtures/ci_eval_fixtures.json)) to compute Recall@k and MRR against baseline thresholds.
- **Regression Detection:** Fails the PR build if retrieval quality degrades below baseline tolerance:
  ```powershell
  # Normal run (passes):
  uv run python evals/ci_eval_gate.py

  # Test deliberate regression (trips gate, exit code 1):
  uv run python evals/ci_eval_gate.py --simulate-regression
  ```

---

## Verification & Test Results

All quality, security, and observability checks pass cleanly:

```powershell
# Run the complete test suite (145 tests)
uv run pytest -v

# Code formatting and style
uv run ruff check .
uv run ruff format --check .

# Static type checking
uv run mypy src

# CI Quality Gate
uv run python evals/ci_eval_gate.py
```

### Current Status:
- **145/145 automated unit and integration tests passing.**
- **OpenTelemetry trace hierarchy and GenAI attributes:** 100% verified.
- **Prometheus metric cardinality & /metrics export:** 100% verified.
- **Streamlit UI citation offset highlighting & client:** 100% verified.
- **CI evaluation gate (baseline pass + simulated regression trip):** 100% verified.
- **0 policy bypasses** across 175 red-team adversarial attacks.
- **0 secret or PII leaks** in JSON logs.
- **Ruff linter and code formatter:** 100% compliant across 113 files.
- **Mypy static analysis:** Clean across 34 source modules.

---

## Go / No-Go Review

- **Core Goal:** Model proposes; executor enforces; automated tests verify. **[MET]**
- **Observability:** OpenTelemetry traces and Prometheus `/metrics` with Grafana dashboard. **[MET]**
- **Streamlit UI:** Live timeline, drift-free cited evidence highlighting, and trace inspector. **[MET]**
- **CI Quality Gate:** Deterministic, GPU-independent regression gate in GitHub Actions. **[MET]**
- **Decision:** **GO FOR MILESTONE 2 RELEASE**.

---

## Project Documentation
- [Threat Model](docs/threat_model.md)
- [Grafana Dashboard](docs/grafana_dashboard.json)
- [2-Minute Demo Script](docs/demo.md)
- [Recovery & Run Lifecycle](docs/recovery.md)
- [ADR-002: Hybrid Retrieval](docs/ADR-002-hybrid-retrieval.md)
- [ADR-003: Abstention and Grader Calibration](docs/ADR-003-abstention-and-grader.md)
- [ADR-004: Typed Workflow and E4 Results](docs/ADR-004-e4-workflow.md)
- [Hardware and Model Notes](docs/hardware.md)
- [W6 D1-D6 devlog](devlog/W6_D1-D6.md)
- [W7 D1-D6 devlog](devlog/W7_D1-D6.md)
