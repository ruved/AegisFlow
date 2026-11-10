# ADR-011: Prompt Prefix Stability and KV-Cache Reuse (E10)

- **Status:** Accepted
- **Date:** 2026-11-10
- **Context:** Week 9 D4 Stretch Optimization Experiment E10

## Context & Problem Statement

Modern LLM inference engines (such as llama.cpp and Ollama) employ Key-Value (KV) cache prefix matching. When consecutive requests share an identical prompt prefix, the engine skips prompt evaluation (prefill) for the matching tokens, immediately beginning response generation.

However, naive prompt designs frequently inject dynamic context (e.g. current timestamps, session UUIDs, dynamic user queries) at the top of the system prompt. This completely busts the KV prefix cache, forcing full prompt re-evaluation on every turn.

## Empirical Evaluation

We benchmarked streaming inference on `gemma3:4b` across 5 trials comparing:
1. **Unstable Prefix:** Dynamic timestamp and UUID prepended to the system prompt head.
2. **Stable Prefix:** Invariant system prompt and schema definitions placed first; dynamic user queries and evidence placed strictly in the user turn.

Results recorded in `results/prefix_stability.json`:

| Prompt Architecture | Mean TTFT (ms) | Mean Prompt Eval (ms) | Mean Total Duration (ms) |
| :--- | :---: | :---: | :---: |
| **Unstable Prefix** | 4,825.2 | 2,639.8 | 8,278.4 |
| **Stable Prefix** | **3,502.8** | **1,394.8** | **6,196.9** |
| **Delta / Speedup** | **-27.4%** | **-47.2%** | **-25.1%** |

### Key Findings:
- Keeping the system prompt prefix invariant reduced prompt evaluation time from 2,639.8 ms down to 1,394.8 ms (**47.2% faster prefill**).
- Time To First Token (TTFT) improved by **27.4%** (3,502.8 ms vs 4,825.2 ms).
- Total inference duration dropped by 2.08 seconds per generation.

## Decision

**Accept Prefix Stability as an Architectural Standard across all AegisFlow Prompts.**
1. All workflow system prompts (Planner, Analyst, Verifier, Reporter) must remain static and invariant.
2. Dynamic context (retrieved chunks, question texts, timestamps, session keys) must never be injected into system instructions; they must be structured strictly within the `user` turn or evidence blocks.
3. JSON output schema definitions (`format: schema.model_json_schema()`) must remain identical across invocations to ensure structural grammar stability.

## Consequences

- **Positive:** Up to 47.2% reduction in prompt prefill computation, 27.4% faster TTFT, and zero prompt drift.
- **Negative:** Prompt templates must adhere to strict separation between static instructions and dynamic context.
