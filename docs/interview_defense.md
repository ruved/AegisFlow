# AegisFlow Technical Interview Defense & Architectural Analysis

This document compiles the evidence-backed defense of AegisFlow's architecture, security boundaries, RAG pipeline, workflow orchestration, performance optimizations, and honest post-mortem analyses of dropped experiments.

---

## 1. System Architecture & Security Boundary

### Q: Why did you choose a centralized `ToolExecutor` instead of giving the LLM direct access to tools or LangChain agent toolkits?
**Defense:**
- **Principle:** *Model proposes; executor enforces; automated tests verify.*
- An LLM output is fundamentally untrusted text. In vanilla agent frameworks, tool calls execute with the process's full ambient permissions.
- AegisFlow implements an out-of-band security boundary:
  1. **Strict Pydantic Validation:** Every tool proposal must match a registered schema (`extra="forbid"`). Unknown tools or unexpected parameters are rejected immediately before invocation.
  2. **Declarative Risk Policies:** Tools are tagged `low` or `high` risk. Read-only actions (like log search) execute under timeout limits (1.0–2.0s); state-mutating actions (like `simulate_write`) require explicit out-of-band operator approval.
  3. **Cryptographic Auditing:** Every proposal is logged to SQLite with a SHA-256 hash of its parameters, the policy evaluation result, and the execution duration. Raw sensitive arguments are never persisted.
  4. **Adversarial Red-Team Suite:** Verified over 105 automated prompt injections and path-traversal attacks (`evals/run_red_team.py`) with **0 policy bypasses** (0.0% failure rate).

---

## 2. Hybrid Retrieval & Evidence Grounding

### Q: Why hybrid retrieval over pure vector search?
**Defense:**
- Vector embeddings excel at semantic similarity ("system running out of memory"), but fail on exact identifier lookups ("RB-001", "pay-7712", "order-01", "SEV-1").
- Lexical search (SQLite FTS5 BM25) excels at exact keyword matching, but fails on paraphrased queries.
- We combined dense vector embeddings (`nomic-embed-text`) with SQLite FTS5 using Reciprocal Rank Fusion (RRF, $k=60$):
  $$RRF(d) = \sum_{m \in \{dense, lexical\}} \frac{1}{60 + rank_m(d)}$$
- **Measured Result:** Hybrid retrieval achieved **Recall@3 of 0.762** and **MRR of 0.857** on our unseen hold-out incident set (`data/eval/holdout_set.jsonl`), outperforming dense-only search.

---

## 3. Workflow Orchestration & Crash Recovery

### Q: Why LangGraph instead of standard ReAct loops or autogen?
**Defense:**
- **Deterministic State Graph:** Unconstrained agent loops risk infinite wandering, token exhaustion, and silent hallucination drift.
- AegisFlow coordinates specialized nodes: `Planner -> Retrieve -> Analyst -> Verifier -> Reporter`.
- **Loop & Drift Prevention:** The graph enforces step bounds ($\le 14$ steps), token budget limits ($\le 6000$ tokens), and history loop detection (aborting if identical evidence is queried twice).
- **Crash Recovery & Resume:** Backed by SQLite persistence (`SqliteSaver`). When interrupted, passing the `run_id` resumes execution from the exact last successful node snapshot without re-running expensive prior steps.

---

## 4. Performance Optimizations & Empirical Trade-Offs

### Q: Walk me through the optimizations you tested. Which ones worked?
**Defense:**
Every optimization was measured against an empirical baseline using our reproducible benchmark harness (`evals/benchmark.py`):

1. **E3 — Embedding & Retrieval Caching (Accepted, ADR-005):**
   - Thread-safe Bounded LRU + TTL cache with monotonic corpus version invalidation.
   - **Measured Impact:** Repeat retrieval latency dropped from ~2,130 ms to **0.17 ms**. Overall mixed-workload latency decreased by **19.7%–20.1%**.
2. **E5 — Context Builder Token Budgeting (Accepted, ADR-006):**
   - Enforces per-subquestion token caps, global context budgets, and section diversity deduplication.
   - **Measured Impact:** Prevented prompt token explosion while maintaining **100% citation recall**.
3. **E9 — Inference Semaphore & Priority Queue (Accepted, ADR-009):**
   - Bounded concurrency with $K=2$ execution slots and a 3-tier priority queue (`INTERACTIVE` > `NORMAL` > `BATCH`) with anti-starvation aging (10s threshold).
   - **Measured Impact:** Reduced p95 tail latency by **66.7%** (219.0 ms vs 657.0 ms) under load.
4. **E10 — Prompt Prefix Stability (Accepted, ADR-011):**
   - Maintained invariant system prompts and output schemas to maximize Ollama/llama.cpp KV-cache prefix reuse.
   - **Measured Impact:** Reduced Time-To-First-Token (TTFT) by **27.4%** (3,502.8 ms vs 4,825.2 ms) and prompt prefill time by **47.2%** (1,394.8 ms vs 2,639.8 ms).

---

## 5. Honest Post-Mortem of Failed / Dropped Experiments

### Q: Did any optimization experiments fail? Why?
**Defense:**
We strictly rejected optimizations that did not deliver measurable net improvements:

1. **E6 — Sentence-Level Extractive Pruning (Dropped, ADR-007):**
   - *Hypothesis:* Splitting retrieved chunks into sentences, embedding them, and keeping only high-similarity sentences would shrink prompt size and speed up inference.
   - *Measurement:* Sentence splitting and embedding overhead took ~55 ms, while prompt prefill savings on a 4B model was only ~29 ms (net latency was **+26 ms slower**).
   - *Quality Degradation:* At thresholds aggressive enough to yield tokens savings ($\ge 0.65$), citation recall degraded from 100% down to 80%–87%.
   - *Decision:* **Dropped.** E5 (Context Builder) achieved cleaner prompt bounds without the latency penalty or recall drop.

2. **E7 — Model Cascade & Per-Node Routing (Dropped, ADR-008):**
   - *Hypothesis:* Route Planner and Verifier to a fast 2B/4B model (`qwen3.5:4b`) while reserving `gemma3:4b` for Analyst and Reporter.
   - *Measurement:* On desktop/single-GPU hardware, swapping models in Ollama introduced a **2,372.6 ms swap penalty** on every node transition.
   - *Schema Drift:* The smaller candidate model exhibited 0% schema compliance on complex Pydantic verifier schemas, triggering fallback retry loops.
   - *Decision:* **Dropped.** Maintaining a single resident model (`gemma3:4b`) in memory avoided swap delays and guaranteed 100% schema compliance.

---

## 6. Operational Capacity Limits & Concurrency

### Q: What is the maximum throughput and capacity of this service?
**Defense:**
- We executed multi-tier concurrency tests (`evals/load_test.py`) across 1, 4, 10, and 25 virtual users (3 repetitions each):
  - **1 User:** 14.7 req/s
  - **4 Users:** 26.8 req/s
  - **10 Users:** 27.6 req/s
  - **25 Users:** 39.2 req/s
- **Error Rate:** Exactly **0.0%** across all 12 concurrency trials.
- **Declared Safe Capacity:** 10–25 concurrent users per single-GPU instance. Beyond 25 users, requests are queued predictably by the $K=2$ limiter rather than crashing the GPU with out-of-memory errors.
