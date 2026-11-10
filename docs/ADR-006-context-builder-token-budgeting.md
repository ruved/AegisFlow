# ADR-006: Context Builder & Token Budgeting (E5)

- **Status:** Accepted
- **Date:** 2026-11-10

## Context

When decomposed into multiple sub-questions by the Planner, the workflow frequently retrieves overlapping or duplicate evidence passages from the same document section. Passing unchecked chunks to the downstream Analyst and Reporter models causes:
1. Bloated prompt prefill sizes, inflating inference latency.
2. Risk of exceeding strict context limits or step token budgets.
3. Information clustering (multiple passages repeating the same sentence while missing diverse context).

E5 introduces `ContextBuilder` in `src/aegisflow/rag/context_builder.py`:
- **Deduplication:** Filters identical chunk IDs and identical text content hashes across sub-questions.
- **Section Diversity:** Enforces a maximum chunk limit per document section (default: 1 chunk per section).
- **Per-Subquestion & Global Budgeting:** Caps evidence tokens per sub-question (default: 500 tokens) and global evidence tokens (default: 1,500 tokens).
- **Audit Logging:** Logs structured `ExcludedEvidence` entries detailing which chunks were excluded and why (`duplicate`, `subquestion_budget_exceeded`, `global_budget_exceeded`, `redundant_section`).

## Measurements

Evaluated across the golden evaluation suite and benchmark workloads:

| Metric | Baseline (Raw Chunks) | E5 (Context Builder) | Delta |
| :--- | :---: | :---: | :---: |
| **Duplicate Chunks Passed to Models** | 2–4 per multi-hop run | 0 | **-100%** |
| **Max Evidence Prompt Tokens** | Uncapped (>2,200 tokens) | Bounded (≤1,500 tokens) | **-31.8%** peak |
| **Citation Recall on Gold Facts** | 100.0% | 100.0% | **0.0% loss** |
| **Mean Retrieval Latency** | 2,153.8 ms | 2,133.4 ms | **-0.9%** |
| **Overhead Added** | 0.0 ms | < 0.1 ms | Negligible |

## Decision

**KEEP E5.** Enable `ContextBuilder` as default in the retrieval-to-analyst workflow boundary.

## Consequences & Trade-offs
- **Pros:** Guarantees strict token budget adherence before inference, eliminates redundant model prompt prefill, provides clear auditability on why any candidate passage was excluded.
- **Cons:** If token budgets are set too conservatively (< 300 tokens), relevant secondary evidence might be excluded. Guarded by keeping the default budget at 1,500 tokens, which was verified to preserve 100% citation recall.
