# Inventory Service — Service Architecture

> Service ID: SVC-005
> Status: Current synthetic architecture
> Last reviewed: 2026-10-16
> System: AegisShop
> All systems, metrics, and incidents in this corpus are fictional.

## Responsibility

Inventory Service owns stock quantities and reservation operations for products sold through AegisShop. It checks whether sufficient stock is available, records reservations, and supports the lifecycle of holding, confirming, or releasing reserved stock according to the order workflow.

Inventory Service does not own product descriptions, payment transactions, or the overall order record. Catalog Service owns authoritative product information, Payment Service owns payment processing, and Order Service coordinates the order lifecycle.

## Dependencies and request flow

Order Service calls Inventory Service when an order requires stock reservation. Inventory Service updates its authoritative inventory records and returns the reservation result. The order workflow must account for reservation failures and duplicate requests rather than assuming that a request was processed exactly once.

Retries can occur when a caller times out after a reservation has already been recorded. If the reservation operation is not idempotent, repeated requests may create conflicting reservations or consume stock more than once. Concurrency control and stable idempotency keys are therefore important safeguards.

Catalog presence does not prove stock availability. Similarly, a successful reservation response does not, by itself, prove that payment succeeded or that the order has reached its final state.

## Signals to inspect

Review reservation request volume, successful and rejected reservations, duplicate request counts, inventory discrepancies, database transaction failures, lock waits, and reservation records that remain in intermediate states beyond their expected lifetime.

For a disputed order, trace the order ID, product ID, reservation ID, request timestamp, and idempotency key. Compare the authoritative inventory record with the associated reservation events and Order Service state. Distinguish a genuinely unavailable item from a reservation timeout or a duplicate-processing defect.

## Operational safeguards

Make reservation changes atomic and enforce the required invariants under concurrent requests. Use stable idempotency keys so retries do not create additional reservations. Define safe expiration and release behavior for reservations that are not completed, and ensure that delayed messages or repeated commands cannot incorrectly release confirmed stock.

Do not manually increase stock or delete reservation records simply to clear an alert. Establish the authoritative state first, preserve evidence, and follow a controlled recovery process.

## Related corpus documents

- `architecture.md` — system-wide service inventory and assumptions.
- `dependency-map.md` — cross-service dependencies and failure propagation.
- `../postmortems/PM-008-inventory-double-reservation.md` — conflicting reservation records after duplicate processing.
- `../postmortems/PM-006-payment-provider-slowdown.md` — a separate example of an uncertain downstream outcome.
- `../runbooks/RB-004-bad-deployment.md` — investigation of deployment regressions.

## Retrieval cautions

This document describes intended synthetic architecture, not current stock levels. Use logs and authoritative records to establish actual reservation state. Do not equate catalog availability with inventory availability, and do not infer payment or order completion from a reservation event alone.
