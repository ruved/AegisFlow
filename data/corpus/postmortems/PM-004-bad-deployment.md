# PM-004: Order Service Deployment Regression

> Incident ID: INC-2026-0709
> Date: 2026-07-09
> Severity: SEV-2
> Affected services: Order Service, API Gateway
> Status: Resolved
> Document type: Synthetic incident postmortem

## 1. Summary

On 2026-07-09, a new Order Service release increased checkout errors and request
latency. The release changed the order-validation path and introduced an additional
database lookup for each checkout request. The regression appeared shortly after
deployment and was resolved through a controlled rollback.

All incident details and metrics in this postmortem are fictional.

## 2. Customer impact

Approximately 11% of checkout requests failed or exceeded the latency target
during the 17-minute incident. Catalog and Search services remained healthy.
The team checked order state before retrying affected operations to avoid creating
duplicate orders.

## 3. Timeline

- 09:00 UTC — Order Service version 2.8.0 deployment began.
- 09:04 UTC — The first new instances became healthy.
- 09:07 UTC — Checkout p95 latency increased above 2 seconds.
- 09:10 UTC — HTTP 5xx responses increased beyond the alert threshold.
- 09:13 UTC — Responders correlated the regression with version 2.8.0.
- 09:17 UTC — Rollback to version 2.7.4 began.
- 09:24 UTC — Error rates and latency returned toward baseline.

## 4. Root cause

Version 2.8.0 introduced an extra database lookup in the synchronous checkout
validation path. The query was not covered by representative load testing. Under
production traffic, it increased database work per checkout and extended request
latency enough to cause upstream timeouts.

## 5. Contributing factors

The deployment dashboard showed instance health but did not clearly compare
checkout latency by application version. The release test suite validated
functional correctness but did not detect the performance regression. Rollback
ownership was unclear during the first few minutes.

## 6. Resolution

Responders compared latency and error rates between old and new versions, verified
that database and external dependencies were not independently failing, and
initiated a controlled rollback. They monitored deployment health and checkout
metrics until the old version was stable.

The response followed `../runbooks/RB-004-bad-deployment.md`. The team did not restart all
instances indiscriminately because the evidence pointed to a version-specific
regression.

## 7. Preventive actions

- Add version-level latency and error-rate comparisons to deployment dashboards.
- Include representative load tests for checkout validation changes.
- Define a clear rollback owner for production releases.
- Use progressive rollout with automatic rollback thresholds where supported.
- Record the exact application version in incident evidence.

## 8. Lessons learned

A service becoming unhealthy immediately after a deployment is strong evidence,
but not proof, that the release caused the incident. Responders should correlate
the timing with version-specific metrics and dependency health, then choose a
controlled rollback when the evidence supports it.
