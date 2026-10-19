# RB-006: Payment Provider Latency

> Status: Current synthetic runbook
> Version: 1.0
> Owner: Payments Reliability
> Applies to: Payment Service
> Last reviewed: 2026-10-16

## 1. Purpose

Use this procedure when requests to the external payment provider become slow,
time out, or return elevated error rates.

All metrics, provider responses, and examples are fictional.

## 2. Symptoms

- Payment authorization p95 latency exceeds 1.5 seconds for five minutes.
- Provider timeout rate exceeds 3%.
- Payment requests remain in an unknown or pending state longer than normal.
- Payment Service connection pools or request queues show increasing pressure.
- Provider errors rise while unrelated services remain healthy.

A timeout does not prove that the provider failed to process a payment.

## 3. Initial triage

1. Record the incident start time and affected payment operations.
2. Compare provider latency, timeout rate, error codes, and request volume with baseline.
3. Check Payment Service health, thread usage, connection pools, and queue depth.
4. Determine whether the issue affects one operation or all provider requests.
5. Check provider status information through the approved operational channel.
6. Identify whether recent deployment or configuration changes correlate with the issue.

Do not log payment credentials, card data, or other sensitive payment information.

## 4. Diagnosis

### Provider-side slowdown

Compare provider response latency and error codes with application-side timings.
Check whether failures occur across multiple application instances.

### Network or connection issue

Inspect connection establishment timeouts, DNS failures, TLS errors, and network
errors separately from provider application responses.

### Local resource exhaustion

Check whether thread pools, connection pools, or request queues are saturated.
A slow provider can occupy local resources and cause secondary failures.

### Retry amplification

Compare original request volume with retry volume. Excessive retries can increase
provider load and make recovery slower.

### Unknown payment outcome

Identify requests that timed out after submission but before a definitive response.
Reconcile their outcomes through the provider's approved status lookup or
reconciliation process before initiating another charge attempt.

## 5. Mitigation

1. If a recent deployment caused the issue, assess rollback safety.
2. Apply bounded timeouts and retry policies consistent with the provider contract.
3. Use exponential backoff and jitter where retries are appropriate.
4. Respect provider rate limits and use a circuit breaker if supported.
5. For uncertain payment outcomes, query or reconcile the existing transaction
   using its provider reference or supported idempotency mechanism.
6. Preserve pending states when the outcome is unknown; do not mark payments
   successful or failed without sufficient evidence.
7. Communicate with the provider owner when the incident appears external.

Never blindly retry a payment authorization whose outcome is unknown.

## 6. Verification

Observe for at least five minutes:

- Provider latency and timeout rate move toward baseline.
- Payment Service queues and resource usage recover.
- New payment outcomes are recorded consistently.
- Unknown transactions are reconciled safely.
- Retry volume remains bounded and does not amplify the incident.

## 7. Rollback and escalation

Rollback a recent change only when evidence supports it and rollback is safe.
Escalate unresolved or potentially duplicated transactions to the payments
incident owner. Follow the approved reconciliation procedure for financial
state discrepancies.

## 8. Closure notes

Record affected operations, provider latency and error trends, retry behavior,
unknown transaction count, reconciliation results, mitigation, and follow-up
actions. Keep sensitive payment data out of incident notes.
