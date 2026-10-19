# API Gateway — Service Architecture

> Service ID: SVC-001
> Status: Current synthetic architecture
> Last reviewed: 2026-10-16
> System: AegisShop
> All systems, metrics, and incidents in this corpus are fictional.

## Responsibility

The API Gateway is the public entry point for client requests to AegisShop. It validates incoming requests, applies authentication and request limits, forwards traffic to the appropriate backend service, and records request identifiers for tracing. It does not own product, order, inventory, or payment business data.

## Dependencies and request paths

The gateway routes catalog reads to Catalog Service, order operations to Order Service, product-search requests to Search Service, and other supported operations to their designated backend. The Order Service has its own downstream dependencies, including Payment Service and Inventory Service; the gateway should not bypass those service boundaries to perform business operations directly.

The gateway depends on reachable backend endpoints, correctly configured routing, valid service credentials, and compatible request and response contracts. A gateway timeout can indicate a slow backend, connection exhaustion, network trouble, or a gateway-side resource problem. A timeout alone does not establish which component caused the failure.

## Signals to inspect

During an incident, compare request rate, error rate, latency percentiles, upstream timeout counts, active connections, and per-backend health. Use correlation IDs to connect gateway events to backend logs. Compare affected routes and instances before concluding that the gateway itself is unhealthy.

A healthy gateway health check does not prove that every backend route is healthy. Likewise, a rising gateway error rate does not prove that the gateway deployment caused the errors.

## Operational safeguards

Use bounded connection pools and timeouts. Avoid unbounded retries because they can amplify load on a struggling dependency. Before changing routing or rolling back a gateway release, check whether the incident began with a backend change or a dependency failure. Preserve correlation IDs and relevant timestamps in incident notes.

## Related corpus documents

- `dependency-map.md` — service dependency relationships and failure propagation.
- `../runbooks/RB-004-bad-deployment.md` — diagnosis of deployment regressions.
- `../logs/order-db-pool-incident.log.md` — example of an upstream timeout associated with a database-acquisition timeout.
- `../services/architecture.md` — system-wide service inventory.

## Retrieval cautions

Treat this page as a synthetic architecture description, not runtime telemetry. Use incident logs for observed events and the current relevant runbook for remediation. Do not attribute an incident to the gateway solely because the client-visible error occurred there.
