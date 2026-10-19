# PM-002: Product Catalog Cache Stampede

> Incident ID: INC-2026-0521
> Date: 2026-05-21
> Severity: SEV-2
> Affected services: Catalog Service, API Gateway
> Status: Resolved
> Document type: Synthetic incident postmortem

## 1. Summary

On 2026-05-21, a popular product-category cache entry expired during a traffic
peak. A large number of requests simultaneously queried the underlying database
instead of reusing a cached response. Database read traffic increased sharply,
and catalog requests became slow or intermittently unavailable.

All incident details and metrics in this postmortem are fictional.

## 2. Customer impact

For approximately 19 minutes, 22% of catalog requests exceeded the latency target.
Some API Gateway requests returned HTTP 503 after their upstream timeouts expired.
Checkout remained operational, although customers experienced slower product
discovery.

No evidence indicated product data corruption.

## 3. Timeline

- 11:40 UTC — Catalog traffic increased ahead of a promotional campaign.
- 11:43 UTC — A heavily requested category cache entry expired.
- 11:44 UTC — Database read QPS rose to approximately four times its baseline.
- 11:47 UTC — Catalog p95 latency exceeded 1.8 seconds.
- 11:51 UTC — Responders identified synchronized cache misses for the same key.
- 11:56 UTC — The team enabled request coalescing for the affected category.
- 12:02 UTC — Database traffic and catalog latency approached normal levels.

## 4. Root cause

The affected cache entry expired for all application instances at approximately
the same time. Each instance independently loaded the same data from the database.
The absence of request coalescing allowed concurrent misses to multiply the work
required to refresh one popular entry.

## 5. Contributing factors

The category used a fixed time-to-live without expiration jitter. The service had
no per-key single-flight mechanism, and load testing did not simulate a popular
key expiring during peak traffic. Database read capacity was also limited by other
catalog queries.

## 6. Resolution

The team enabled request coalescing for the affected key and allowed one refresh
operation to populate the cache while concurrent callers shared its result.
Responders monitored cache hit ratio, database read traffic, and request latency.
The team did not flush the entire cache, which could have created a wider burst
of database requests.

The response followed `../runbooks/RB-002-redis-cache-stampede.md`.

## 7. Preventive actions

- Introduce expiration jitter for suitable cache entries.
- Add request coalescing for frequently accessed keys.
- Consider stale-while-revalidate for data whose freshness requirements permit it.
- Add load tests that expire popular keys under concurrent traffic.
- Alert on sudden drops in cache hit ratio combined with increased database QPS.

## 8. Lessons learned

A cache can fail operationally even when Redis is healthy. Simultaneous cache
misses can shift load to the database and create a cascading failure. Mitigation
should control duplicate refresh work rather than blindly clearing or enlarging
the cache.
