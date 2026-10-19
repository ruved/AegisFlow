# Catalog Service — Service Architecture

> Service ID: SVC-002
> Status: Current synthetic architecture
> Last reviewed: 2026-10-16
> System: AegisShop
> All systems, metrics, and incidents in this corpus are fictional.

## Responsibility

Catalog Service owns the authoritative product catalog used by AegisShop. It manages product descriptions, category membership, product attributes, and catalog availability for read operations. It is the source of truth for catalog data; Search Service maintains a derived index optimized for text search and filtering.

Catalog Service does not own inventory reservations, order state, or payment state. A product appearing in the catalog does not guarantee that stock is available or that a purchase will succeed.

## Dependencies and data flow

The API Gateway routes catalog read and update requests to this service. Catalog Service persists authoritative product data in the catalog database. Catalog changes are published for downstream consumers, including Search Service, to update their derived index.

This creates an important distinction: a catalog update can succeed while the search index is temporarily behind. Search results may therefore show stale product text or omit a recently changed product even when the authoritative catalog is healthy. Search index lag should not automatically be diagnosed as catalog database failure.

## Signals to inspect

Review catalog request rate, error rate, latency percentiles, database query latency, connection-pool utilization, and update failures. For suspected search inconsistency, compare a product's authoritative catalog record, the catalog-change event, and the corresponding search-index update timestamp.

A healthy catalog read path does not prove that downstream indexing has completed. Conversely, a missing search result does not prove that the product was deleted from the source catalog.

## Operational safeguards

Avoid broad catalog writes or full reindex operations during an active database incident unless their impact is understood. Prefer a narrow, reproducible product identifier when investigating discrepancies. Check event publication and consumer progress before replaying changes, and use the established recovery procedure to avoid duplicate or out-of-order processing.

## Related corpus documents

- `architecture.md` — system-wide service inventory and assumptions.
- `dependency-map.md` — cross-service dependencies and propagation paths.
- `../postmortems/PM-007-search-index-lag.md` — a reindex operation that delayed incremental search updates.
- `../runbooks/RB-004-bad-deployment.md` — investigation of deployment regressions.

## Retrieval cautions

This is a synthetic architecture document, not proof of current runtime health. Use logs and incident evidence for observed behavior. Keep authoritative catalog state separate from derived search-index state, and do not infer stock availability from catalog presence.
