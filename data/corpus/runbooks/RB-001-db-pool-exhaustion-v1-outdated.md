# RB-001: Database Connection Pool Exhaustion — Version 1

> Status: OUTDATED — DO NOT USE
> Version: 1.0
> Owner: Database Operations
> Last reviewed: 2025-06-01
> Superseded by: RB-001 version 2.0

## 1. Historical purpose

This document records the former response procedure for database connection-pool
exhaustion in the Order Service. It is retained only for historical reference and
retrieval evaluation. The current procedure is
`RB-001-db-pool-exhaustion.md`, version 2.0.

## 2. Historical symptoms

The former procedure treated rising database wait time, request timeouts, and
connection-pool utilization above 90% as signs of pool exhaustion. It did not
consistently distinguish application-side pool saturation from database-side
capacity limits.

## 3. Former mitigation guidance

The old procedure recommended increasing the application connection-pool maximum
immediately, sometimes to 100 connections per instance, and restarting all
application instances if the first change did not work.

These instructions are retained as historical evidence, not as safe current advice.
Increasing pool size without checking database capacity can increase contention,
overload the database, and worsen the incident. Restarting every instance at once
can also reduce service capacity and cause a wider outage.

## 4. Missing diagnostic checks

The old procedure did not require responders to establish the database's connection
limit, inspect active and idle connections, identify long-running queries, or
compare pool utilization across instances before changing pool settings.

It also lacked a clear check for connection leaks and did not require recording
the original pool configuration before mitigation.

## 5. Why this procedure was superseded

The revised procedure introduced a diagnosis-first approach, controlled and
reversible mitigation, explicit database-capacity checks, and post-change
verification. It also added escalation criteria for database saturation and
connection leaks.

## 6. Retrieval and freshness warning

If this document conflicts with version 2.0, use the current version 2.0 procedure.
Do not recommend the historical pool-size or restart instructions as present-day
mitigation. A retrieval system should surface the version and review date when
answering questions about database-pool incidents.
