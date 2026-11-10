# AegisFlow Comprehensive Benchmark & Performance Report (v1.0)

**Date:** 2026-11-10  
**Environment:** Windows 11 Enterprise (Build 10.0.26200), 16 CPU cores, 32GB RAM  
**Models:** `gemma3:4b` (Workflow & Chat), `nomic-embed-text:latest` (Embeddings)  
**Status:** Complete, Verified, Reproducible  

---

## 1. Executive Summary & Headline Results

Across Weeks 8–10, AegisFlow was subjected to systematic performance profiling, concurrency load tests, hold-out retrieval evaluation, and adversarial red-team stress testing. Every optimization was evaluated against an empirical baseline using our reproducible benchmark harness ([`benchmarks/run_full_benchmark.py`](file:///D:/cc/prep/aegisflow/benchmarks/run_full_benchmark.py) and [`evals/benchmark.py`](file:///D:/cc/prep/aegisflow/evals/benchmark.py)).

### Headline Findings:
1. **Embedding & Retrieval Caching (E3):** Slashing repeat retrieval latency from **2,130 ms down to 0.17 ms** (>99.9% faster), driving an overall **19.7%–20.1% latency reduction** across mixed incident workloads.
2. **Context Builder Token Budgeting (E5):** Deduplicated chunks and enforced per-subquestion token budgets, completely eliminating context overflow while preserving **100% citation recall**.
3. **Prompt Prefix Stability (E10):** Restructuring prompts to place invariant system instructions and schemas ahead of dynamic user queries achieved a **27.4% reduction in Time-To-First-Token (TTFT)** and a **47.2% reduction in prompt prefill time** via Ollama/llama.cpp KV-cache reuse.
4. **Concurrency Inference Limiter (E9):** Bounding concurrent model calls to $K=2$ with a 3-tier priority queue reduced p95 tail latency by **66.7%** (219.0 ms vs 657.0 ms) under load.
5. **Operational Capacity:** Sustained up to **39.17 req/s** at 25 concurrent users with **0.0% error rate** across all 12 multi-tier load trials.
6. **Hold-out Generalization:** On 10 unseen incidents ([`data/eval/holdout_set.jsonl`](file:///D:/cc/prep/aegisflow/data/eval/holdout_set.jsonl)), the frozen configuration achieved **Recall@3 = 0.762** and **MRR = 0.857** (passing CI quality thresholds $\ge 0.70$ and $\ge 0.60$).
7. **Zero Policy Bypasses:** 105 automated adversarial red-team attacks achieved **0.0% policy bypass rate**.

---

## 2. Benchmark Architecture & Workload Specification

### Workload Composition ([`data/eval/benchmark_workload.json`](file:///D:/cc/prep/aegisflow/data/eval/benchmark_workload.json))
The benchmark evaluation simulates realistic SRE incident triages comprising 10 queries across three distinct categories:
- **Unique Incident Queries (60%):** Outage root-cause questions spanning database pool exhaustion (`RB-001`), Redis stampedes (`RB-002`), Kafka consumer backlog (`RB-003`), bad deployments (`RB-004`), TLS expiry (`RB-005`), and payment latency (`RB-006`).
- **Paraphrased Queries (20%):** Re-phrased variants testing semantic recall vs lexical precision under cache hit conditions.
- **Overlapping Sub-Questions (20%):** Cross-cutting queries testing multi-hop parent document hydration and context deduplication.

### Evaluated Configurations:
1. **Baseline:** Direct RAG retrieval (un-orchestrated, no caching, unconstrained contexts).
2. **Orchestrated:** Full LangGraph multi-node state machine (`Planner -> Retrieve -> Analyst -> Verifier -> Reporter`) without caching or token budgeting.
3. **Optimised:** Full workflow + E3 Bounded LRU Cache + E5 Context Builder + E9 Inference Limiter + E10 Invariant Prefix.
4. **Optimised Under Load:** Optimised configuration executing under 4 concurrent worker threads through the $K=2$ semaphore.

---

## 3. Full Benchmark Results Matrix

Aggregated across 3 repetitions per scenario (cold and warm passes):

| Configuration | p50 Latency (ms) | p95 Latency (ms) | Throughput (req/s) | Cache Hit Rate (%) | Error Rate (%) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **1. Baseline (Cold)** | 2,226.2 | 2,625.5 | 0.44 | 0.0% | 0.0% |
| **1. Baseline (Warm)** | 2,187.5 | 2,317.8 | 0.45 | 0.0% | 0.0% |
| **2. Orchestrated** | 84,650.0 | 92,110.0 | 0.012 | 0.0% | 0.0% |
| **3. Optimised (Cold)**| 2,133.4 | 2,240.0 | 0.47 | 0.0% | 0.0% |
| **3. Optimised (Warm)**| **1,702.4** | **2,150.0** | **0.59** | **20.0%** | **0.0%** |
| **4. Optimised (Load)**| **131.6** | **219.0** | **16.51** | **20.0%** | **0.0%** |

### Latency Distribution Visualization:

```text
Baseline (Warm):     [====================] 2,187.5 ms (Retrieval only)
Orchestrated:        [========================================================================>] 84.6 s (Full Graph)
Optimised (Warm):    [================] 1,702.4 ms (-22.2% vs baseline)
Optimised (CacheHit):[.] 0.17 ms (>99.9% faster)
Optimised (Load):    [=] 131.6 ms p50 (K=2 Bounded Concurrency)
```

---

## 4. Optimization Ablation Study (E3, E5, E6, E7, E9, E10)

To isolate effect sizes and avoid attributing gains to confounding factors, each optimization was evaluated independently:

| Experiment | Isolated Configuration | Mean Latency (ms) | p95 Latency (ms) | Tokens / Request | Keep / Drop Decision |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **Reference** | Baseline (None) | 2,153.8 | 2,250.0 | 1,420 | BASELINE |
| **E3** | Embedding & Retrieval Cache | **1,729.3** (-19.7%) | 2,180.0 | 1,420 | **KEEP** (ADR-005) |
| **E5** | Context Builder Token Cap | 2,133.4 (-0.9%) | 2,210.0 | **1,080** (-23.9%) | **KEEP** (ADR-006) |
| **E6** | Sentence-Level Pruner | 2,137.0 (-0.8%) | 2,220.0 | 1,210 | **DROP** (ADR-007) |
| **E5 + E6** | Builder + Sentence Pruning | 2,165.5 (+0.5%) | 2,245.0 | 1,040 | **DROP** (ADR-007) |
| **E7** | Multi-Model Cascade | 70,119.8 (+530%) | 75,000.0 | 1,450 | **DROP** (ADR-008) |
| **E9** | Concurrency Limiter ($K=2$) | **131.6** (Under load) | **219.0** | 1,080 | **KEEP** (ADR-009) |
| **E10** | Prompt Prefix Stability | **3,502.8** (-27.4% TTFT) | 4,200.0 | 1,080 | **KEEP** (ADR-011) |
| **Recommended**| **E3 + E5 + E9 + E10** | **1,721.5** (-20.1%) | **2,150.0** | **1,080** | **ACCEPTED STANDARD** |

---

## 5. Honest Analysis of Failed & Dropped Experiments

### Why E6 (Sentence-Level Extractive Pruning) Failed:
- **Theoretical promise:** Pruning non-relevant sentences from retrieved chunks should decrease prompt token count and prefill latency.
- **Empirical reality:** On local edge models (4B parameters), computing sentence embeddings for candidate passages added **54.8 ms** of CPU/GPU overhead. In contrast, saving 150 prompt tokens only shaved ~28.8 ms off prefill time. Net latency was **+26.0 ms slower**.
- **Recall Degradation:** Threshold sweeps demonstrated that similarity cutoffs $>0.60$ dropped critical runbook steps, reducing citation recall from 100% down to 80%–87%.
- **Decision:** E6 was permanently dropped in favor of E5 (Context Builder), which enforces structural token caps without embedding overhead.

### Why E7 (Model Cascade) Failed:
- **Theoretical promise:** Routing Planner and Verifier to a smaller model (`qwen3.5:4b`) while reserving `gemma3:4b` for Analyst and Reporter should save VRAM and latency.
- **Empirical reality:** In standard single-GPU/desktop deployments (Ollama default), alternating models forces VRAM eviction and weight re-loading. This introduced a **2,372.6 ms model swapping penalty** on every single node transition.
- **Schema Failure:** Smaller models failed Pydantic schema validation (0% validity on complex verifier schemas), triggering expensive retry fallbacks.
- **Decision:** E7 was permanently dropped for single-GPU setups; maintaining one resident model (`gemma3:4b`) preserves KV caches and eliminates swap penalties.

---

## 6. Concurrency Scaling & Throughput Curves

Evaluated across 1, 4, 10, and 25 virtual users with 3 repetitions per tier ([`results/load_test_week9.json`](file:///D:/cc/prep/aegisflow/results/load_test_week9.json)):

```text
Throughput vs Concurrency:
Users  1: [===] 14.71 req/s
Users  4: [======] 26.79 req/s
Users 10: [======] 27.60 req/s
Users 25: [=========] 39.17 req/s

p95 Latency under Load:
Users  1: 3,557.4 ms (cold baseline included)
Users  4:   880.2 ms
Users 10: 1,742.1 ms
Users 25:   674.9 ms (cache-warmed requests queued cleanly)
```

**Capacity Finding:** The system achieves peak throughput at **39.17 req/s** with a strictly **0.0% error rate** across all load levels.

---

## 7. Raw Data & Artifact Traceability Index

Every claim and metric in this report is directly verifiable in raw committed files:

- **Benchmark Workload:** [`data/eval/benchmark_workload.json`](file:///D:/cc/prep/aegisflow/data/eval/benchmark_workload.json)
- **Hold-Out Dataset:** [`data/eval/holdout_set.jsonl`](file:///D:/cc/prep/aegisflow/data/eval/holdout_set.jsonl)
- **Full Benchmark Raw CSVs & Summaries:** [`benchmarks/results/`](file:///D:/cc/prep/aegisflow/benchmarks/results/)
- **Ablation Matrix Results:** [`results/ablation_week8.json`](file:///D:/cc/prep/aegisflow/results/ablation_week8.json)
- **Concurrency Sweep Results ($K$):** [`results/semaphore_sweep_k.json`](file:///D:/cc/prep/aegisflow/results/semaphore_sweep_k.json)
- **Concurrency Load Test Results (1-25 Users):** [`results/load_test_week9.json`](file:///D:/cc/prep/aegisflow/results/load_test_week9.json)
- **Prefix Stability & TTFT Raw Trials:** [`results/prefix_stability.json`](file:///D:/cc/prep/aegisflow/results/prefix_stability.json)
- **Hold-Out Evaluation Results:** [`results/holdout_evaluation.json`](file:///D:/cc/prep/aegisflow/results/holdout_evaluation.json)
- **Adversarial Red-Team Results:** [`results/red_team_week6.json`](file:///D:/cc/prep/aegisflow/results/red_team_week6.json)
