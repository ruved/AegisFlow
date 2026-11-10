# AegisFlow v1.0 Demo Walkthrough Guide

This guide accompanies the reproducible 4-minute demo runner ([`scripts/demo_v1.py`](file:///D:/cc/prep/aegisflow/scripts/demo_v1.py)) and the live interactive Streamlit UI ([`src/aegisflow/ui.py`](file:///D:/cc/prep/aegisflow/src/aegisflow/ui.py)).

---

## Quick Demo Invocation

Run the complete 6-part terminal walkthrough:
```powershell
uv run python scripts/demo_v1.py --fast
```

Or launch the interactive web interface:
```powershell
uv run streamlit run src/aegisflow/ui.py
```

---

## 4-Minute Walkthrough Structure

### Part 1: Problem & Architectural Boundary (0:00 – 0:45)
- **The Challenge:** Autonomous AI agents with direct tool access run shell commands and file mutations under ambient process permissions, exposing production environments to prompt injection and uncontrolled side effects.
- **AegisFlow Solution:** An out-of-band security boundary:
  - Strict Pydantic schema validation (`extra="forbid"`).
  - Centralized policy engine (`low` vs `high` risk classification).
  - Out-of-band operator approval for state mutations (`simulate_write`).
  - SHA-256 hashed audit log preventing credential leakage.

### Part 2: Live Multi-Step Workflow Execution (0:45 – 1:30)
- **Deterministic State Graph:** Coordinated via LangGraph (`Planner -> Retrieve -> Analyst -> Verifier -> Reporter`).
- **Safety Bounds:** Enforces maximum step count ($\le 14$), token budget ($\le 6000$), and query cycle detection.
- **Trace Tree:** Every node emits an OpenTelemetry span with GenAI semantic attributes (`gen_ai.usage.prompt_tokens`, `gen_ai.usage.completion_tokens`, duration).

### Part 3: Cited Evidence & Grounding Panel (1:30 – 2:15)
- **Exact Passage Grounding:** Citations link claims to specific source markdown documents and sections in `data/corpus/`.
- **Drift-Free Highlighting:** Exact character offset calculation relative to displayed clean text ensures highlighting never drifts across client reruns.
- **Verification Gate:** Verifier node inspects citations and rejects reports that make unsupported claims.

### Part 4: State Checkpointing & Crash Recovery (2:15 – 2:50)
- **SQLite Checkpointing:** Every node commit is snapshotted to `runtime/demo_checkpoints.sqlite3`.
- **Zero-Loss Resumption:** If an SRE incident copilot process is interrupted by a worker SIGTERM, network drop, or container restart, passing `--resume` re-hydrates the exact last valid state without re-planning or repeating expensive LLM calls.

### Part 5: Security Policy Enforcement (2:50 – 3:30)
- **Automated Adversarial Testing:** Evaluates injection documents, path traversals (`../../etc/shadow`), and resource exhaustion prompts.
- **Demonstrated Result:** 0 policy bypasses across 105 attack vectors.

### Part 6: Optimisation Ablation Results (3:30 – 4:00)
- **E3 Caching:** Repeat retrieval drops from 2,130 ms to **0.17 ms** (-19.7% mixed latency).
- **E5 Context Builder:** Subquestion token caps eliminate duplicate chunks while maintaining **100% citation recall**.
- **E10 Prefix Stability:** Invariant system prefixes cut TTFT by **27.4%** and prompt prefill duration by **47.2%**.
- **E9 Concurrency Limiter:** $K=2$ semaphore cuts p95 tail latency by **66.7%** under concurrent load.
