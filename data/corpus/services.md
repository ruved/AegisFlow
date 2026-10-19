# AegisShop Synthetic Incident Corpus — Index

> Corpus version: v0
> Last reviewed: 2026-10-19
> Purpose: Retrieval, evidence-grounding, incident diagnosis, and conflict-resolution tests for AegisFlow.
> Scope: All services, incidents, identifiers, timestamps, and operational examples in this corpus are fictional.

## 1. How to use this corpus

Use this index to locate relevant architecture, runbooks, postmortems, and log evidence. For an incident question, first identify the affected service and symptom, then retrieve the relevant current runbook and compare it with incident records. Use logs as evidence of recorded events, postmortems as historical explanations, and architecture notes as descriptions of intended system behavior.

Do not treat all documents as equally authoritative. Check status, version, review date, and the type of evidence a document provides. When sources disagree, identify the conflict explicitly rather than silently combining their claims.

## 2. System overview

AegisShop is a fictional e-commerce platform with seven services:

| Service | Primary responsibility | Important relationships |
|---|---|---|
| API Gateway | Request routing, authentication, limits, and upstream handling | Routes requests to backend services |
| Catalog Service | Authoritative product information | Publishes changes consumed by Search Service |
| Order Service | Order lifecycle and coordination | Depends on Payment Service and Inventory Service |
| Payment Service | Payment attempts and reconciliation | Communicates with an external payment provider |
| Inventory Service | Stock and reservation operations | Receives reservation requests from Order Service |
| Notification Service | Asynchronous customer notifications | Consumes Kafka events and calls notification providers |
| Search Service | Product search over a derived index | Depends on catalog-change delivery and indexing |

Read `services/architecture.md` for the system-wide overview and `services/dependency-map.md` for dependency relationships and example failure propagation. Individual service notes provide ownership boundaries, diagnostic signals, safeguards, and retrieval cautions.

## 3. Architecture documents

| Document | Coverage |
|---|---|
| `services/architecture.md` | Overall architecture and seven-service inventory |
| `services/dependency-map.md` | Dependencies, failure propagation, and diagnostic boundaries |
| `services/api-gateway.md` | Routing, upstream timeouts, and correlation IDs |
| `services/catalog-service.md` | Authoritative product data and catalog-change flow |
| `services/order-service.md` | Order lifecycle, downstream coordination, and idempotency |
| `services/payment-service.md` | Payment attempts, provider responses, and reconciliation |
| `services/inventory-service.md` | Stock reservations, concurrency, and duplicate requests |
| `services/notification-service.md` | Kafka consumption, delivery delays, and provider bottlenecks |
| `services/search-service.md` | Derived search index and freshness diagnosis |

These documents describe intended synthetic architecture. They do not establish current runtime health or the state of an individual transaction.

## 4. Runbooks

| Document | Status | Primary topic |
|---|---|---|
| `runbooks/RB-001-db-pool-exhaustion.md` | Current, v2.0 | Database connection-pool exhaustion and slow queries |
| `runbooks/RB-001-db-pool-exhaustion-v1-outdated.md` | Outdated historical version, v1.0 | Deliberately conflicting older database-pool guidance |
| `runbooks/RB-002-redis-cache-stampede.md` | Current, v1.0 | Synchronized cache expiration and database load |
| `runbooks/RB-003-kafka-consumer-backlog.md` | Current, v1.0 | Consumer lag, processing throughput, and downstream bottlenecks |
| `runbooks/RB-004-bad-deployment.md` | Current, v1.0 | Regressions introduced by deployments |
| `runbooks/RB-005-certificate-expiry.md` | Current, v1.0 | Certificate expiry and related TLS diagnosis |
| `runbooks/RB-006-payment-provider-latency.md` | Current, v1.0 | Provider latency, timeouts, and uncertain payment outcomes |

For operational recommendations, prefer the applicable current runbook. The outdated database-pool document is retained only to test version awareness and conflict handling; it must not be used as current operational guidance.

## 5. Postmortems

| Document | Incident theme |
|---|---|
| `postmortems/PM-001-db-pool-exhaustion.md` | Slow order-history queries exhausted the database connection pool |
| `postmortems/PM-002-cache-stampede.md` | Synchronized cache expiration produced a database load spike |
| `postmortems/PM-003-kafka-consumer-backlog.md` | Notification-provider latency contributed to Kafka consumer lag |
| `postmortems/PM-004-bad-deployment.md` | A deployment introduced a query regression |
| `postmortems/PM-005-certificate-expiry.md` | Certificate renewal did not reach the deployed service |
| `postmortems/PM-006-payment-provider-slowdown.md` | Provider slowdown created uncertain payment outcomes |
| `postmortems/PM-007-search-index-lag.md` | Reindex activity delayed incremental search updates |
| `postmortems/PM-008-inventory-double-reservation.md` | Duplicate processing led to conflicting reservation records |

Postmortems describe specific historical scenarios within this fictional environment. Their findings should not be generalized beyond the evidence they record.

## 6. Log evidence

| Document | Useful evidence |
|---|---|
| `logs/order-db-pool-incident.log.md` | Pool saturation, a correlated gateway timeout, slow queries, and post-mitigation metrics |
| `logs/payment-provider-timeouts.log.md` | Provider latency, a timeout, retry suppression, and later reconciliation |

Logs record events and identifiers; they are not complete explanations by themselves. Correlate timestamps and IDs across sources. Do not infer an unrecorded event or claim that one sample establishes system-wide behavior.

## 7. Intentional retrieval traps and conflicts

### Outdated versus current runbook

The current database-pool runbook is `runbooks/RB-001-db-pool-exhaustion.md`, version 2.0. The file `runbooks/RB-001-db-pool-exhaustion-v1-outdated.md` is explicitly marked outdated and superseded. If asked for current remediation, choose the current version and explain why the historical advice is not authoritative.

### Payment timeout versus payment outcome

A provider timeout does not prove that payment failed. In `logs/payment-provider-timeouts.log.md`, payment `pay-7712` later has a recorded reconciliation result of provider-confirmed success. Recommendations must distinguish an unknown outcome from a confirmed failure and must avoid blind retries.

### Catalog state versus search state

Catalog Service owns authoritative product information, while Search Service owns a derived index. A stale or missing search result does not, by itself, prove catalog data is missing or incorrect.

### Order state versus payment and inventory state

An order record, payment record, and inventory reservation are different pieces of state. Evidence that establishes one does not automatically establish the others.

### Consumer backlog versus broker failure

Kafka consumer lag can result from slow downstream processing or an external provider. Diagnose consumer throughput and dependency health before attributing a backlog to the broker itself.

### Logs versus root-cause explanation

Logs show recorded events. A postmortem provides an incident-specific analysis. Architecture notes describe intended relationships. Where appropriate evidence is missing, state the uncertainty rather than inventing a causal link.

## 8. Corpus quality and provenance

All documents in corpus v0 are synthetic and were authored for AegisFlow evaluation. They are not copied public postmortems or real production records, and the identifiers, dates, service names, metrics, and incidents are fictional.

The corpus deliberately includes related incidents, similar terminology, an outdated runbook, and distinct failure modes. These features support tests of retrieval precision, freshness awareness, contradiction handling, evidence citation, and safe operational reasoning.

Before using this corpus for evaluation, validate document counts, paths, headings, metadata, and internal references. Treat the corpus as versioned test data: changes to incident facts or remediation advice should be reviewed rather than silently overwritten.
