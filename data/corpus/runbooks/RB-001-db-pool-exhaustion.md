# RB-001: Database Connection Pool Exhaustion

> Status: Current synthetic runbook
> Version: 2.0
> Owner: Platform Reliability
> Applies to: Order Service, Catalog Service, Payment Service, Inventory Service
> Last reviewed: 2026-10-15
> Severity guide: SEV-2 unless customer impact or data integrity requires escalation

## 1. Purpose

Use this runbook when a service cannot obtain database connections quickly
enough to process requests. This can cause rising latency, request timeouts,
and connection acquisition failures.

This procedure is synthetic training material, not a real production policy.

## 2. Symptoms

Investigate this runbook when one or more conditions occur:

- Database connection-pool utilization remains above 85% for five minutes.
- Connection acquisition wait time exceeds 500 ms at the p95.
- Database-related request errors exceed 2% for five minutes.
- Request latency rises while available connections approach zero.
- Logs contain messages such as "connection acquisition timeout".

Thresholds are illustrative alerting defaults for this fictional system.

## 3. Initial triage

1. Record the incident start time, affected service, environment, and correlation IDs.
2. Check request error rate, p95 latency, active connections, idle connections,
   pending acquisition requests, and acquisition timeout counts.
3. Determine whether one service or several services show pool pressure.
4. Check for a recent deployment, traffic spike, slow query, or downstream slowdown.
5. Check database CPU, active queries, locks, and connection limits before
   increasing any pool configuration.

Do not assume that high pool utilization alone proves a database outage.

## 4. Diagnosis

### Pool exhaustion caused by slow queries

Compare query duration, active-query count, and connection hold time.
Identify the affected query fingerprints and inspect query plans using
approved read-only diagnostics.

### Connection leak or long-held transaction

Compare checked-out connections with request volume and transaction duration.
Inspect application traces for connections held after the request completes.

### Traffic spike

Compare incoming request rate with normal traffic and database capacity.
Check whether a cache miss spike or retry storm increased database demand.

### Database saturation

Inspect CPU, lock waits, I/O latency, and database connection limits.
If the database is saturated, increasing application pool sizes may worsen
the incident.

## 5. Mitigation order

1. If a recent deployment correlates with the incident, evaluate rollback
   using the service deployment procedure.
2. Reduce unnecessary request amplification by applying approved rate limits
   or disabling a confirmed nonessential expensive operation.
3. If a known expensive query is responsible, use an approved mitigation
   for that query and verify its effect.
4. Increase the connection pool only when database headroom and the database
   connection limit have been verified.
5. If the database is saturated, coordinate with the database owner before
   changing concurrency or query behavior.

Do not restart all service instances or increase pool sizes blindly.

## 6. Verification

After each mitigation, observe for at least five minutes:

- Connection utilization trends downward and remains below 75%.
- p95 acquisition wait falls below 200 ms.
- Database-related error rate falls below 1%.
- Request latency and error rate recover without a new increase in database load.

These are fictional operational targets, not universal production thresholds.

## 7. Rollback and escalation

Undo a configuration change if database saturation, errors, or latency worsens.
Escalate to the database owner if active queries, locks, or database limits
remain the dominant bottleneck.

Escalate to the incident lead if customer impact persists after two mitigation
attempts or if data integrity may be affected.

## 8. Closure notes

Record the confirmed cause, affected service, time window, evidence, mitigation,
verification results, and follow-up actions. If the cause remains uncertain,
mark it as unconfirmed rather than guessing.
