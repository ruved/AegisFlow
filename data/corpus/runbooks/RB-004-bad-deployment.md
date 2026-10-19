# RB-004: Bad Deployment

> Status: Current synthetic runbook
> Version: 1.0
> Owner: Release Engineering
> Applies to: All AegisShop services
> Last reviewed: 2026-10-16

## 1. Purpose

Use this procedure when service errors, latency, or failed requests increase
after a deployment or configuration change.

All release identifiers, thresholds, and examples are fictional.

## 2. Symptoms

- Error rate increases shortly after a release.
- p95 latency rises compared with the pre-deployment baseline.
- New exceptions appear in application logs.
- One application version fails while the previous version worked.
- Health checks fail or instances repeatedly restart.

Temporal correlation is evidence to investigate, not proof that a deployment
caused the incident.

## 3. Initial triage

1. Record the incident start time, service, environment, and release identifier.
2. Compare error rate, latency, traffic, and resource use before and after release.
3. Identify which instances or versions are affected.
4. Inspect deployment and configuration-change records.
5. Check dependencies before concluding that the application release is at fault.

## 4. Diagnosis

### Application regression

Look for new exceptions, failed assertions, or changed request behavior.
Compare the failing release with the last known healthy version.

### Configuration error

Check environment variables, timeout values, connection settings, feature flags,
and secrets references without exposing secret values.

### Dependency incompatibility

Inspect downstream errors, schema changes, API compatibility, and database
migration status.

### Capacity regression

Check CPU, memory, thread usage, connection pools, and request concurrency.
A new release may use more resources even when request volume is unchanged.

## 5. Mitigation

1. If evidence strongly links the incident to the release, assess rollback risk.
2. Confirm database migrations and message formats are compatible with the
   previous version before rolling back.
3. Follow the approved deployment rollback procedure.
4. If rollback is unsafe, disable a confirmed problematic feature through an
   approved feature flag or deploy a tested fix.
5. Avoid simultaneous unrelated configuration changes that make diagnosis harder.

## 6. Verification

After mitigation, observe for at least five minutes:

- Error rate approaches the pre-deployment baseline.
- p95 latency returns toward baseline.
- Health checks pass and restart frequency declines.
- Downstream dependencies recover.
- No data integrity or event-processing regression is observed.

## 7. Rollback and escalation

Stop the rollback if it introduces incompatible database or message formats.
Escalate to the release owner and incident lead if the cause remains uncertain,
the rollback fails, or data integrity may be affected.

## 8. Closure notes

Record the release identifier, change window, evidence, confirmed or suspected
cause, mitigation, verification results, and follow-up actions.
