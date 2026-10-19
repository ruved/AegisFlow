# Search Service — Service Architecture

> Service ID: SVC-007
> Status: Current synthetic architecture
> Last reviewed: 2026-10-16
> System: AegisShop
> All systems, metrics, and incidents in this corpus are fictional.

## Responsibility

Search Service provides product search and filtering for AegisShop. It maintains a derived search index built from authoritative catalog data and serves queries against that index. The index is optimized for retrieval and is not the source of truth for product descriptions, product existence, or inventory quantities.

Catalog Service owns authoritative product information. Inventory Service owns stock and reservation state. Search Service must not independently invent or override those authoritative records.

## Dependencies and data flow

The API Gateway routes search requests to Search Service. Catalog changes are published for downstream processing, and Search Service consumes those changes to update its index. A background reindex operation may also rebuild some or all of the derived index.

Search freshness depends on event publication, consumer processing, indexing throughput, and resource availability. A product update can be successfully stored in Catalog Service while the corresponding search document remains stale. A large reindex operation can compete with incremental updates and delay fresh data.

A missing search result therefore does not necessarily mean that the product is absent from the catalog. Likewise, a result returned by Search Service does not prove that the product is currently in stock.

## Signals to inspect

Review search request latency, error rate, query volume, indexing throughput, indexing failures, consumer lag, reindex progress, and the age of the most recently applied catalog change.

Investigate a specific product by comparing its authoritative catalog record, the relevant catalog-change event, consumer progress, and the indexed document. Determine whether the discrepancy originates in catalog data, event delivery, indexing, or query behavior before starting a reindex.

## Operational safeguards

Avoid running an unrestricted reindex during an active indexing backlog without estimating its impact on incremental updates. Prefer bounded reindex jobs, monitor resource use, and verify that incremental event processing continues to make progress.

Before rebuilding the index, preserve relevant progress and failure evidence. After recovery, validate a sample of changed products against authoritative catalog records. Do not use a successful reindex-job status alone as proof that every document is current.

## Related corpus documents

- `architecture.md` — system-wide service inventory and assumptions.
- `dependency-map.md` — cross-service dependencies and failure propagation.
- `catalog-service.md` — authoritative catalog data and update flow.
- `../postmortems/PM-007-search-index-lag.md` — reindex activity delayed incremental indexing.
- `../runbooks/RB-004-bad-deployment.md` — investigation of deployment regressions.

## Retrieval cautions

This document describes intended synthetic architecture, not live index freshness. Use incident evidence and indexing telemetry to establish what happened. Keep catalog state, indexed search state, and inventory state separate. Do not conclude that the catalog is unhealthy solely because a search result is missing.
