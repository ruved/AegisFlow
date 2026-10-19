# Payment Service — Service Architecture

> Service ID: SVC-004
> Status: Current synthetic architecture
> Last reviewed: 2026-10-16
> System: AegisShop
> All systems, metrics, and incidents in this corpus are fictional.

## Responsibility

Payment Service manages payment attempts, communication with the external payment provider, payment status, and reconciliation. It records payment identifiers and idempotency keys so that repeated requests can be handled safely. It reports payment outcomes to Order Service, which maintains the corresponding order state.

Payment Service does not own the order lifecycle or inventory stock. Order Service owns order state, while Inventory Service owns stock reservations. A successful payment does not independently prove that the complete order workflow has finished.

## Dependencies and request flow

Order Service calls Payment Service as part of order processing. Payment Service communicates with the configured payment provider and records the result of each attempt. Provider responses may be successful, explicitly declined, failed before processing, or uncertain because a response timed out after the provider may already have processed the request.

When the result is uncertain, reconciliation checks the provider's authoritative transaction state before the application decides what should happen next. A timeout must not automatically be translated into a failed payment or trigger an unprotected second charge.

## Signals to inspect

Review provider latency, timeout rate, explicit decline rate, circuit-breaker state, request volume, retry counts, and payment outcomes awaiting reconciliation. Correlate evidence using payment IDs, order IDs, idempotency keys, and timestamps.

Distinguish three separate facts: the application received a timeout, the provider processed or did not process a payment, and Order Service updated the order state. Evidence for one fact does not automatically establish the other two.

## Operational safeguards

Use bounded timeouts, controlled retries, stable idempotency keys, and a documented reconciliation process. When provider latency rises, avoid increasing retry traffic without understanding the effect on the provider and local resources. If a payment outcome is unknown, suppress unsafe retries and reconcile before taking corrective action.

A circuit breaker can protect the application from a failing provider path, but an open circuit does not determine the outcome of requests already in flight. Preserve pending payment records for investigation and follow the current payment-provider runbook.

## Related corpus documents

- `architecture.md` — system-wide service inventory and assumptions.
- `dependency-map.md` — downstream dependencies and failure propagation.
- `../runbooks/RB-006-payment-provider-latency.md` — current provider-latency response procedure.
- `../postmortems/PM-006-payment-provider-slowdown.md` — incident involving uncertain payment outcomes.
- `../logs/payment-provider-timeouts.log.md` — timeout, retry suppression, and reconciliation evidence.

## Retrieval cautions

This is a synthetic architecture description, not live payment state. A timeout is not proof of failure, and a provider success is not proof that Order Service has already updated the order. Verify the payment ID and reconciliation result before recommending a retry or asserting the final state.
