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

### Automated Red Team Suite
Run the automated adversarial red-team suite:

```bash
uv run python evals/run_red_team.py --runs 5
```

Results are saved to [results/red_team_week6.json](results/red_team_week6.json):
- **100 Injection document attempts** (20 unique injection templates x 5 runs)
- **50 Malicious argument attempts** (10 boundary/traversal payloads x 5 runs)
- **25 Resource exhaustion attempts** (5 oversized/nested inputs x 5 runs)
- **Total proposals tested:** 175
- **Observed policy bypasses:** **0 (0.0% bypass rate)**

Audit entries for all attempts are recorded in `runtime/tool_audit_redteam.sqlite3` with SHA-256 argument hashes only.

### Threat Model
The full threat model is documented in [docs/threat_model.md](docs/threat_model.md), mapping controls against the OWASP Top 10 for Agentic Applications 2026:
- **ASI01 Agent Goal Hijack:** Prompt delimiters `<UNTRUSTED_EVIDENCE>` and executor-level authorization boundary.
- **ASI02 Tool Misuse & Exploitation:** Allowlisted typed registry, Pydantic strict validation, risk levels, human approval gates.
- **ASI03 Identity & Privilege Abuse:** API-key auth via `X-API-Key`, process runs with least privilege local identity.
- **ASI05 Unexpected Code Execution:** Zero arbitrary shell or code execution tools.
- **ASI08 Cascading Failures:** Step, token, deadline, per-request, and per-tool timeout budgets.

---

## Verification & Test Results

All quality and security checks pass cleanly:

```powershell
# Run the complete test suite (126 tests)
uv run pytest -q

# Code formatting and style
uv run ruff check .
uv run ruff format --check .

# Static type checking
uv run mypy src
```

### Milestone 1 Status:
- **126/126 automated unit and integration tests passing.**
- **0 policy bypasses** across 175 red-team adversarial attacks.
- **0 secret or PII leaks** in JSON logs (tested against API keys, passwords, Bearer tokens, AWS keys, emails).
- **Ruff linter and code formatter:** 100% compliant across 102 files.
- **Mypy static analysis:** Clean across 32 source modules.

---

## Go / No-Go Review

- **Core Goal:** Model proposes; executor enforces; automated tests verify. **[MET]**
- **Tool Registry:** 5 registered tools with typed JSON schemas and risk metadata. **[MET]**
- **Policy & Audit:** Centralized enforcement flow with hashed argument digests. **[MET]**
- **Injection Boundary:** Untrusted data delimitation and executor-level safety. **[MET]**
- **Adversarial Red Team:** Automated runner with 0 policy bypasses across 175 attempts. **[MET]**
- **Threat Model & Redaction:** OWASP mapping and proven secret redaction. **[MET]**
- **Decision:** **GO FOR v0.1 RELEASE**. Prioritized security enforcement boundaries and test reliability over speculative agentic capabilities.

---

## Project Documentation
- [Threat Model](docs/threat_model.md)
- [2-Minute Demo Script](docs/demo.md)
- [Recovery & Run Lifecycle](docs/recovery.md)
- [ADR-002: Hybrid Retrieval](docs/ADR-002-hybrid-retrieval.md)
- [ADR-003: Abstention and Grader Calibration](docs/ADR-003-abstention-and-grader.md)
- [ADR-004: Typed Workflow and E4 Results](docs/ADR-004-e4-workflow.md)
- [Hardware and Model Notes](docs/hardware.md)
