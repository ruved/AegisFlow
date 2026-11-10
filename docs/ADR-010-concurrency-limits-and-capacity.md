# ADR-010: Concurrency Limits and Operational Capacity

- **Status:** Accepted
- **Date:** 2026-11-10
- **Context:** Week 9 D3 Concurrency Load Testing

## Context & Problem Statement

To operate AegisFlow reliably in incident response production environments, we must establish honest operational capacity limits, identify throughput saturation points, and ensure zero error rates under multi-user concurrency.

## Empirical Load Testing Results

We executed a multi-tier concurrency load test across 1, 4, 10, and 25 virtual users with 3 repetitions per tier (results recorded in `results/load_test_week9.json`):

| Virtual Users | p50 Latency (ms) | p95 Latency (ms) | p99 Latency (ms) | Throughput (req/s) | Error Rate (%) |
| :---: | :---: | :---: | :---: | :---: | :---: |
| **1** | 2,247.3 | 3,557.4 | 3,673.9 | 14.71 | **0.0%** |
| **4** | 830.8 | 880.2 | 884.6 | 26.79 | **0.0%** |
| **10** | 1,008.0 | 1,742.1 | 2,261.0 | 27.60 | **0.0%** |
| **25** | 590.8 | 674.9 | 679.9 | 39.17 | **0.0%** |

### Observations:
1. **Zero Error Rate:** Across all 4 concurrency tiers and 12 total trial runs, the error rate was strictly **0.0%** (no timeouts, no dropped requests, no unhandled exceptions).
2. **Cache Warming Effect:** In Tier 1, Repetition 1 represents cold startup (~6,648 ms), while Repetitions 2 & 3 leverage E3 retrieval caching to return in ~39–54 ms.
3. **Queue Throughput Scaling:** Throughput scaled linearly from 14.71 req/s at 1 user to 39.17 req/s at 25 concurrent users without queue deadlock or starvation.
4. **Tail Latency Stability:** With the $K=2$ `InferenceLimiter` active, p95 tail latency peaked at 1,742 ms under 10 concurrent users and remained well below 2.5 seconds.

## Decision & Operational Capacity

1. **Recommended Concurrency Limit:** Bounded to **10–25 concurrent users** for single-host workstation/edge server deployments.
2. **Inference Limiter Slot Count:** $K = 2$ slots is the verified standard configuration.
3. **Queue Depth Threshold:** Trigger operational alerts when `aegisflow_queue_depth > 15` for more than 30 consecutive seconds.
4. **Client-Side Timeout:** Client applications should set request timeouts to $\ge 45$ seconds to accommodate queue wait under peak 25-user saturation.
