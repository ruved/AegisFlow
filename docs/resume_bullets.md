# AegisFlow Verified Resume Bullets

Evidence-backed, interview-ready resume bullets derived from verified implementation code, benchmark CSVs, and load testing results.

---

### Machine Learning Systems / AI Platform Engineer

- **Architected AegisFlow**, an enterprise-grade agentic incident copilot and hybrid RAG service coordinating LangGraph state workflows (`Planner -> Retrieve -> Analyst -> Verifier -> Reporter`) with persistent SQLite checkpointing and zero-data-loss resume.
- **Engineered an Out-of-Band Security & Policy Enforcement Boundary** for agent tool execution with strict Pydantic schema validation (`extra="forbid"`), cryptographic SHA-256 audit trails, and automated adversarial red-team testing with **0 policy bypasses** across 105 attack vectors.
- **Optimized LLM Inference & TTFT by 27.4%** (3,502.8 ms vs 4,825.2 ms) and slashed prompt evaluation duration by **47.2%** through prompt prefix invariance and KV-cache reuse on local edge models (`gemma3:4b`).
- **Designed Bounded LRU + TTL Embedding and Retrieval Caches** with monotonic corpus version invalidation, driving repeat retrieval latency down from 2,130 ms to **0.17 ms** and reducing mixed-workload query latency by **19.7%–20.1%**.
- **Implemented Concurrency Inference Limiter with Priority Queue**, utilizing bounded $K=2$ execution slots and anti-starvation aging to cut p95 tail latency by **66.7%** (219.0 ms vs 657.0 ms) under burst loads while achieving **0.0% error rate** at 39.2 req/s throughput across 25 concurrent users.
- **Conducted Systematic Ablation Studies & Architectural Trade-off Analyses**, empirically dropping extractive sentence pruning (+26ms net latency penalty) and multi-model cascading (2,372.6 ms model swapping delay), documenting decisions across 7 formal Architectural Decision Records (ADRs 005–011).
- **Established Full Observability & CI Quality Gates**, instrumenting GenAI OpenTelemetry spans, Prometheus metrics, and automated GitHub Actions regression testing preventing retrieval quality degradation on an unseen hold-out dataset (Recall@3: 0.762, MRR: 0.857).

---

### Compact / One-Liner Variations

- **Agent Architecture:** *Built a local-first incident copilot using LangGraph and hybrid RAG, implementing out-of-band policy boundaries and automated red-team suites achieving 0 policy bypasses across 105 injection vectors.*
- **Performance Optimization:** *Reduced LLM TTFT by 27.4% and prefill time by 47.2% via prompt prefix stabilization, while bounded LRU caching cut repeat retrieval to 0.17 ms (-19.7% mixed query latency).*
- **Concurrency & Reliability:** *Developed a priority queue inference limiter with anti-starvation aging, reducing p95 tail latency by 66.7% and sustaining 39.2 req/s with 0% errors across 25 concurrent users.*
