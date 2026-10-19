# PM-008: Inventory Double Reservation

> Incident ID: INC-2026-0917
> Date: 2026-09-17
> Severity: SEV-1
> Affected services: Inventory Service, Order Service
> Status: Resolved
> Document type: Synthetic incident postmortem

## 1. Summary

On 2026-09-17, two concurrent checkout requests attempted to reserve the final
unit of a popular product. A retry of one request was also processed without
correctly recognizing the original reservation. The inventory reservation path
allowed inconsistent reservation records, temporarily reporting more reserved
units than were available.

All incident details and metrics in this postmortem are fictional.

## 2. Customer impact

A small number of orders received conflicting reservation outcomes. Some orders
were held for reconciliation, and affected customers experienced delayed
confirmation. The team paused new reservations for the affected SKU while
reconciling inventory records. No inventory quantity was silently corrected
without checking reservation and order evidence.

## 3. Timeline

- 18:00 UTC — Promotional traffic increased for a low-stock product.
- 18:03 UTC — Two checkout requests attempted to reserve the final unit.
- 18:04 UTC — A client retry reused an operation whose original outcome was unclear.
- 18:06 UTC — Reservation records disagreed with the available quantity.
- 18:10 UTC — Responders paused new reservations for the affected SKU.
- 18:17 UTC — The team compared order IDs, reservation IDs, and event history.
- 18:29 UTC — Inconsistent records were reconciled and guarded reservations resumed.

## 4. Root cause

The reservation operation did not enforce the stock check and decrement as one
atomic operation. Concurrent requests could both observe the same available
quantity before either reservation was fully recorded. In addition, the retry
path did not consistently deduplicate requests using a stable idempotency key.

## 5. Contributing factors

The concurrency test suite did not simulate simultaneous requests for the final
unit. Reservation uniqueness was not enforced consistently at the persistence
boundary. Event replay tests also failed to verify that processing the same
reservation command twice produced only one effective reservation.

## 6. Resolution

Responders temporarily restricted new reservations for the affected SKU. They
reconciled reservation records against orders and event history, then restored
availability based on verified state. The fix introduced an atomic conditional
reservation operation and deduplication using a stable operation identifier.

The team verified that replaying the same command did not create an additional
reservation and that concurrent requests could not reserve more units than were
available.

## 7. Preventive actions

- Make the stock check and reservation update atomic.
- Enforce appropriate uniqueness constraints at the persistence boundary.
- Deduplicate retried commands using stable idempotency keys.
- Add concurrency tests for the final available unit.
- Test event replay and duplicate delivery explicitly.
- Alert on impossible inventory and reservation invariants.

## 8. Lessons learned

Retries and concurrent requests are normal distributed-system behavior, not rare
exceptions. Application-level checks alone are insufficient when concurrent
operations can observe the same state. Correctness requires atomic state changes,
stable idempotency keys, and reconciliation procedures for inconsistent records.
