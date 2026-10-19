# Order Service — Service Architecture

> Service ID: SVC-003
> Status: Current synthetic architecture
> Last reviewed: 2026-10-16
> System: AegisShop
> All systems, metrics, and incidents in this corpus are fictional.

## Responsibility

Order Service owns the order lifecycle in AegisShop. It accepts order requests, persists order state, coordinates required downstream operations, and exposes order status to clients. It is responsible for maintaining a consistent order record, including whether payment is pending, confirmed, or failed and whether inventory reservation has succeeded.

Order Service does not own payment-provider records or inventory stock counts. Payment Service owns payment processing and reconciliation. Inventory Service owns stock reservation operations. These ownership boundaries are important during incidents.

## Dependencies and request flow

The API Gateway routes order requests to Order Service. Order Service persists order data in its database and coordinates with Payment Service and Inventory Service according to the order workflow. It may also publish order events used by downstream systems, including Notification Service.

A slow database query can exhaust the Order Service connection pool and cause requests to fail before downstream processing completes. A slow payment provider may leave a payment outcome unknown even after the request times out. An inventory reservation conflict may prevent an order from progressing even while payment and database dependencies are healthy.

These failures require different diagnosis paths. A client-visible order timeout alone does not identify which dependency caused the delay.

## Signals to inspect

Review order creation rate, successful and failed transitions, request latency, database pool utilization, database query latency, downstream call latency, and counts of orders remaining pending beyond their expected processing window.

Trace individual examples using order IDs, payment IDs, timestamps, and correlation IDs. Compare the order record with Payment Service reconciliation and Inventory Service reservation evidence before concluding that an order is paid, unpaid, reserved, or cancelled.

## Operational safeguards

Use stable idempotency keys for retried requests and ensure state transitions are safe under duplicate delivery. Do not blindly repeat a payment request when its outcome is unknown. Do not mark an order fully successful solely because the initial request was accepted. Recovery should reconcile authoritative payment and inventory state before applying corrective order transitions.

When the database pool is exhausted, investigate slow queries and connection usage before changing pool limits. Follow the current database-pool runbook rather than the retained outdated version.

## Related corpus documents

- `architecture.md` — system-wide service inventory and assumptions.
- `dependency-map.md` — failure propagation between services.
- `../runbooks/RB-001-db-pool-exhaustion.md` — current database pool incident procedure.
- `../runbooks/RB-001-db-pool-exhaustion-v1-outdated.md` — historical version retained for conflict and freshness testing.
- `../postmortems/PM-001-db-pool-exhaustion.md` — slow order-history queries exhausted the connection pool.
- `../postmortems/PM-008-inventory-double-reservation.md` — duplicate processing and conflicting inventory reservations.

## Retrieval cautions

This document describes intended synthetic architecture, not live system state. Use logs and incident evidence to establish what happened. Distinguish order state from payment state and inventory state, and never treat a timeout alone as proof of a completed or failed transaction.
