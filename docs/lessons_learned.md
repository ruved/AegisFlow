# AegisFlow Engineering Lessons Learned (v1.0)

Key architectural, operational, and performance lessons learned during the design, benchmarking, and hardening of AegisFlow.

---

## 1. Security Boundaries Cannot Exist Inside the Prompt
- **The Pitfall:** Many LLM agent architectures rely on prompt engineering ("You are an ethical assistant; do not execute harmful commands") or post-generation output parsing to guard tools.
- **The Reality:** Any instruction placed inside the prompt context can be overridden by sophisticated adversarial injections (e.g. delimiters spoofing, multi-lingual bypasses, indirect injection from retrieved documents).
- **The Solution:** Treat all model outputs and corpus passages as fundamentally untrusted. Enforce permissions, tool schemas, approval gates, and argument redaction strictly **out-of-band** in a deterministic runtime (`ToolExecutor`), outside the model's reach.

---

## 2. Theoretical Token Savings Often Increase Net Latency
- **The Pitfall:** In E6 (Sentence-Level Pruning), the hypothesis was that stripping non-relevant sentences from retrieved chunks would shrink prompts and speed up inference.
- **The Reality:** For local 4B models, sentence tokenization and embedding calculation added **~55 ms** of CPU overhead, while saving 150 prompt tokens only reduced prefill time by **~29 ms**. Net latency was **26 ms slower**, and citation recall degraded by up to 20%.
- **Lesson:** *Never optimize prompt token counts without measuring total end-to-end wall-clock latency.* Fast structural budgeting (E5 Context Builder) is far superior to iterative neural compression on the critical path.

---

## 3. Model Swapping Penalties Dominate Edge Deployments
- **The Pitfall:** In E7 (Model Cascade), we sought to route Planner and Verifier to a smaller model (`qwen3.5:4b`) and reserve `gemma3:4b` for Analyst and Reporter.
- **The Reality:** On single-GPU or shared-memory desktop environments, switching models forces Ollama/llama.cpp to unload weights from VRAM and reload new weights. This added a **2,372.6 ms swap penalty** to every node transition, completely destroying performance.
- **Lesson:** In resource-constrained or single-GPU environments, maintaining a single resident model in memory yields lower latency, zero swap overhead, and 100% schema consistency. Multi-model cascades are only viable when multiple GPUs can host all models simultaneously.

---

## 4. Unbounded Concurrency Destroys LLM Tail Latency
- **The Pitfall:** Handling incoming agent requests by spawning unbounded asynchronous tasks (`asyncio.create_task`) causes memory thrashing, context swapping, and catastrophic tail latency (p99 > 30s) under traffic spikes.
- **The Reality:** Bounding concurrency via an explicit semaphore ($K=2$) paired with a 3-tier priority queue (`INTERACTIVE` > `NORMAL` > `BATCH`) and anti-starvation aging reduced p95 tail latency by **66.7%** (219ms vs 657ms) and maintained a **0.0% error rate** across 25 concurrent users.
- **Lesson:** Queueing requests outside the inference engine is vastly more stable and predictable than overwhelming the engine's internal compute scheduler.

---

## 5. Invariant Prompt Prefixes Yield Free Speedups
- **The Pitfall:** Prepending dynamic metadata (e.g. session IDs, current timestamps, runtime variables) to the head of system prompts invalidates the LLM's KV prefix cache on every request.
- **The Reality:** Restructuring prompts so that static system instructions and JSON schemas form an invariant prefix at the head—with dynamic context placed strictly in user turns—reduced Time-To-First-Token (TTFT) by **27.4%** and prefill duration by **47.2%**.
- **Lesson:** Prompt KV-cache prefix stability is a zero-cost optimization with massive latency benefits across local and hosted LLM backends.
