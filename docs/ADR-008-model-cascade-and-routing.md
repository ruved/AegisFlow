# ADR-008: Model Cascade and Node Routing (E7)

- **Status:** Rejected (Dropped for single-GPU/desktop environments)
- **Date:** 2026-11-10
- **Context:** Week 9 D1 Optimization Experiment E7

## Context & Problem Statement

In multi-node LLM agent workflows, different tasks have differing reasoning demands:
- The **Planner** and **Verifier** generate structured schemas with constrained JSON grammars.
- The **Analyst** and **Reporter** synthesize long-form narrative explanations, citations, and risk-rated incident remediations.

The hypothesis in E7 was that routing Planner and Verifier to a smaller, faster model (e.g. `qwen3.5:4b` or a quantized 2B/4B model) while keeping the primary model (`gemma3:4b`) for Analyst and Reporter would reduce overall workflow latency and VRAM footprint.

## Empirical Evaluation

We benchmarked candidate models across 5 test queries and measured model residency and swapping overhead using Ollama on the local host:

| Candidate Model | Node Role | Schema Validity | Mean Latency | Error / Retries |
| :--- | :--- | :---: | :---: | :---: |
| `gemma3:4b` (Baseline) | Planner / Verifier | **100%** (5/5) | **11,118.5 ms** | 0 retries |
| `qwen3.5:4b` | Planner / Verifier | **0%** (0/5) | 70,119.8 ms | Max retries exceeded |

### Model Swap Delay Benchmark
When alternating between `gemma3:4b` and `qwen3.5:4b` across sequential workflow steps:
- **Mean Model Swap Overhead:** **2,372.6 ms** per transition.
- In a single-GPU/unified memory environment (Ollama default), loading and unloading model weights into VRAM invalidates the KV cache and adds ~2.4 seconds to every node transition.
- Furthermore, smaller candidate models exhibited severe schema drift and hallucinated non-existent properties, triggering costly workflow fallback retries.

## Decision

**Reject E7 (Model Cascade).**
1. We keep a single unified, high-performing model (`gemma3:4b`) resident in memory across all graph nodes (Planner, Analyst, Verifier, Reporter).
2. Per-node model override parameters (`AEGISFLOW_PLANNER_MODEL`, `AEGISFLOW_VERIFIER_MODEL`) remain available in `src/aegisflow/config.py` as an opt-in capability for environments with multiple dedicated GPUs (`OLLAMA_MAX_LOADED_MODELS >= 2`).
3. For standard local and edge deployments, model cascading is disabled by default.

## Consequences

- **Positive:** Zero model swap delays, 100% schema compliance, stable VRAM footprint, and maximal prompt KV-cache reuse.
- **Negative:** Planner and Verifier use the same compute capacity as Analyst/Reporter rather than a smaller footprint.
