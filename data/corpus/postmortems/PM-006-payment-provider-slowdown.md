# PM-006: External Payment Provider Slowdown

> Incident ID: INC-2026-0827
> Date: 2026-08-27
> Severity: SEV-1
> Affected services: Payment Service, Order Service
> Status: Resolved
> Document type: Synthetic incident postmortem

## 1. Summary

On 2026-08-27, an external payment provider experienced elevated response latency.
Payment Service requests began timing out while some provider operations continued
processing. The incident created a set of transactions whose final outcomes were
initially unknown. The team controlled retries and reconciled transaction states
before completing recovery.

All incident details and metrics in this postmortem are fictional.

## 2. Customer impact

Approximately 9% of payment attempts were delayed or entered a pending state during
the 31-minute incident. Some checkout flows required reconciliation before a final
status could be shown. The team found no confirmed duplicate charges attributable
to the incident.

## 3. Timeline

- 13:20 UTC — Provider response latency began increasing.
- 13:24 UTC — Payment timeout rate crossed 3%.
- 13:27 UTC — Payment Service queues and connection usage increased.
- 13:31 UTC — Responders identified a provider-side latency increase.
- 13:36 UTC — Retry volume was reduced and bounded.
- 13:43 UTC — The provider began returning to normal response times.
- 13:51 UTC — Pending transactions were reconciled through the approved process.

## 4. Root cause

The external provider took longer than the configured request timeout to respond.
Some requests had already reached the provider before the client timed out. Because
the response was not received, Payment Service could not safely infer whether each
operation had succeeded or failed.

## 5. Contributing factors

Retry behavior increased request volume during the slowdown. The operational
dashboard did not clearly separate provider response latency from local connection
wait time. Transaction reconciliation required coordination between payment and
order owners.

## 6. Resolution

Responders compared provider latency, timeout rates, and local resource utilization.
They bounded retries, used backoff where appropriate, and prevented unknown
transactions from being treated as confirmed failures. The team reconciled
transactions using the provider's supported status lookup and idempotency mechanisms.

The response followed `../runbooks/RB-006-payment-provider-latency.md`. No uncertain payment
was blindly resubmitted merely because the original request timed out.

## 7. Preventive actions

- Define bounded retry policies with backoff and jitter where appropriate.
- Track pending and unknown transaction outcomes separately.
- Use supported idempotency mechanisms for payment operations.
- Alert on provider latency, timeout rates, and local resource saturation.
- Document the reconciliation process and ownership for uncertain transactions.

## 8. Lessons learned

A client timeout describes what the client observed, not necessarily what the
provider completed. Safe recovery requires preserving uncertainty until there is
sufficient evidence. Idempotency and reconciliation are essential safeguards
against duplicate financial operations.
