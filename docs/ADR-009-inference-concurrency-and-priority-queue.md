# ADR-009: Inference Concurrency Limiter and Priority Queue (E9)

- **Status:** Accepted
- **Date:** 2026-11-10
- **Context:** Week 9 D2 Optimization Experiment E9

## Context & Problem Statement

Unbounded concurrent calls to local LLM backends (such as Ollama or vLLM) cause memory exhaustion, context swapping, and catastrophic tail latency (p99 > 30 seconds). Furthermore, interactive user requests (e.g. active UI incident triages) risk being starved behind bulk background batch evaluations.

The objective of E9 was to establish:
1. Bounded concurrency (`asyncio.Semaphore(K)` and thread-safe acquisition).
2. A 3-tier priority queue: `INTERACTIVE` (0) > `NORMAL` (1) > `BATCH` (2).
3. Anti-starvation aging to prevent lower-priority requests from waiting indefinitely.
4. Independent instrumentation of queue wait duration vs inference execution time.

## Empirical Parameter Sweep

We evaluated concurrency slot bound $K \in \{1, 2, 4\}$ under a simulated mixed workload (20 requests with simulated generation work):

| Concurrency $K$ | Mean Latency (ms) | p50 Latency (ms) | p95 Latency (ms) | Throughput (req/s) |
| :---: | :---: | :---: | :---: | :---: |
| **K = 1** | 358.9 | 359.0 | 657.0 | 8.87 |
| **K = 2** (Selected) | **131.6** | **125.0** | **219.0** | **16.51** |
| **K = 4** | 71.9 | 63.0 | 110.0 | 37.93 |

### Analysis:
- $K=1$ strictly serializes all LLM calls, creating heavy head-of-line blocking and elevated p95 tail latency (657.0 ms).
- $K=2$ reduces p95 tail latency by **66.7%** (219.0 ms vs 657.0 ms) and nearly doubles throughput (16.51 req/s vs 8.87 req/s) while remaining safely within single-GPU VRAM limits.
- While $K=4$ offers further throughput gains for simulated work, under live Ollama 4B inference on desktop GPUs, $K \ge 4$ exceeds parallel context memory slots and triggers context thrashing.

## Decision

**Accept E9 with $K = 2$.**
1. Implement `InferenceLimiter` in [`src/aegisflow/concurrency.py`](file:///D:/cc/prep/aegisflow/src/aegisflow/concurrency.py) managing a thread-safe priority queue with $K=2$ concurrent execution slots.
2. Provide both `async acquire()` and synchronous `acquire_sync()` context managers.
3. Apply anti-starvation aging (requests waiting longer than 10 seconds automatically promote to higher priority).
4. Record Prometheus gauges `aegisflow_queue_depth` and span attribute `inference.queue_wait_ms`.

## Consequences

- **Positive:** Predictable tail latencies under burst load, zero out-of-memory crashes, guaranteed prioritization of interactive incident triages, and complete observability into queue wait times.
- **Negative:** Peak throughput is bounded to $K$ concurrent inference slots; excessive concurrent callers wait in queue rather than running in parallel.
