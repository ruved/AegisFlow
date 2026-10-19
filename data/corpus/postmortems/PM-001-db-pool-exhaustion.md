# PM-001: Order Service Database Pool Exhaustion

> Incident ID: INC-2026-0412
> Date: 2026-04-12
> Severity: SEV-2
> Affected services: Order Service, API Gateway
> Status: Resolved
> Document type: Synthetic incident postmortem

## 1. Summary

On 2026-04-12, the Order Service experienced elevated request latency and
intermittent HTTP 5xx responses after database connection-pool utilization reached
100%. The API Gateway propagated some of the resulting failures to checkout users.
The incident lasted 28 minutes from initial alert to confirmed recovery.

All incident details and metrics in this postmortem are fictional.

## 2. Customer impact

Approximately 14% of checkout attempts failed or timed out during the incident.
Some customers retried their checkout requests, increasing application traffic.
The incident did not establish that any payment was duplicated; payment outcomes
were checked separately before affected orders were reconciled.

Catalog browsing and search remained available.

## 3. Timeline

- 14:02 UTC — Order Service database-pool utilization exceeded 90%.
- 14:05 UTC — Checkout p95 latency exceeded 2 seconds and the error-rate alert fired.
- 14:09 UTC — On-call engineer confirmed pool saturation across several instances.
- 14:14 UTC — Database inspection identified several long-running order queries.
- 14:19 UTC — A recently introduced query pattern was identified as the main contributor.
- 14:24 UTC — The query was disabled through a controlled configuration change.
- 14:30 UTC — Pool utilization and checkout latency returned toward baseline.

## 4. Root cause

A new order-history query introduced an inefficient filtering pattern. Under normal
traffic, its impact was limited. During a traffic increase, queries held database
connections longer than expected, exhausting the Order Service connection pool.

## 5. Contributing factors

The query change lacked a representative load test. Alerting detected pool
saturation but did not initially distinguish slow query execution from connection
leaks or database-wide capacity pressure. Checkout retries also increased load.

## 6. Resolution

The team disabled the problematic query path, inspected active database sessions,
and monitored pool utilization and latency. Engineers verified database health
before declaring recovery. They did not blindly increase the pool limit or restart
all application instances.

The response followed the diagnosis-first principles in the current
`../runbooks/RB-001-db-pool-exhaustion.md` runbook, version 2.0.

## 7. Preventive actions

- Add a query-plan review for the affected order-history path.
- Add a representative load test before enabling similar query changes.
- Improve alerts that distinguish pool saturation from slow database execution.
- Review retry behavior during checkout failures.
- Rehearse the current database-pool runbook during an operational exercise.

## 8. Lessons learned

Connection-pool saturation is a symptom, not necessarily the root cause. Increasing
pool size without checking database capacity can worsen contention. Responders
need query-level evidence and a reversible mitigation before changing connection
limits.
