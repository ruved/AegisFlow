# RB-002: Redis Cache Stampede

> Status: Current synthetic runbook
> Version: 1.0
> Owner: Catalog Reliability
> Applies to: Catalog Service
> Last reviewed: 2026-10-16

## 1. Purpose

Use this procedure when a burst of simultaneous cache misses causes increased
database load and elevated product-read latency.

All thresholds and examples in this document are fictional.

## 2. Symptoms

- Redis cache hit ratio drops below 60% for five minutes.
- Catalog database read traffic rises to more than twice its normal baseline.
- Product-read p95 latency exceeds 800 ms.
- PostgreSQL connection-pool utilization rises alongside cache misses.
- Logs show repeated cache misses for the same popular key.

A low cache hit ratio alone is not enough to confirm a cache stampede.

## 3. Initial triage

1. Record the incident start time and affected endpoints.
2. Compare Redis hit ratio, miss rate, evictions, and latency with the baseline.
3. Check database read QPS, CPU, connection utilization, and query latency.
4. Identify whether many requests target the same keys.
5. Check for a recent cache configuration change, deployment, or key-expiration event.

## 4. Diagnosis

### Simultaneous expiry

Check whether many popular keys expired within a narrow time window.
Look for a synchronized increase in misses and database reads.

### Eviction pressure

Inspect Redis memory usage and eviction counters. Determine whether memory
pressure is removing frequently used keys.

### Cache bypass or key mismatch

Compare cache-key construction across application versions. A key-format change
can make existing entries unreachable without Redis itself failing.

### Database slowdown

Check whether slow database queries are extending cache refill time and
causing concurrent requests to wait for the same data.

## 5. Mitigation

1. If a recent deployment introduced cache bypass or key mismatch, evaluate rollback.
2. If supported by the application, enable request coalescing so concurrent
   requests for the same key share one refill operation.
3. Use bounded, jittered TTLs where appropriate to reduce synchronized expiry.
4. Consider a controlled warm-up of known hot keys if the database has sufficient headroom.
5. If the database is saturated, apply approved traffic controls before triggering
   a large cache warm-up.

Do not flush the entire cache as a first response. This can increase database load.

## 6. Verification

Observe for at least five minutes after mitigation:

- Cache hit ratio trends toward its normal baseline.
- Database read traffic falls toward normal levels.
- Product-read latency improves.
- Connection-pool utilization and error rates decline.
- No large wave of refill errors appears.

Targets must be compared with the fictional service baseline, not assumed universal.

## 7. Rollback and escalation

Revert a cache configuration change if misses, latency, or database load worsen.
Escalate to the database owner if database saturation persists despite reduced
request amplification.

## 8. Closure notes

Record the suspected or confirmed trigger, affected keys or endpoints, cache and
database metrics, mitigation, verification results, and follow-up actions.
Mark the cause unconfirmed if evidence is insufficient.
