# PM-007: Search Index Lag After Reindexing

> Incident ID: INC-2026-0903
> Date: 2026-09-03
> Severity: SEV-3
> Affected services: Search Service, Catalog Service
> Status: Resolved
> Document type: Synthetic incident postmortem

## 1. Summary

On 2026-09-03, product updates took longer than expected to appear in search results.
The Catalog Service successfully persisted product changes, but the Search Service
processed indexing events more slowly than they arrived. A scheduled reindexing
operation increased resource contention and extended the indexing delay.

All incident details and metrics in this postmortem are fictional.

## 2. Customer impact

For approximately 42 minutes, some product searches returned stale prices,
availability descriptions, or product metadata. Direct catalog reads continued
returning current source data. No evidence indicated that the source catalog records
had been lost.

## 3. Timeline

- 10:00 UTC — A scheduled search reindexing job started.
- 10:07 UTC — Indexing throughput fell below the incoming event rate.
- 10:12 UTC — The oldest unprocessed indexing event exceeded ten minutes.
- 10:18 UTC — Responders correlated the lag with reindexing resource consumption.
- 10:25 UTC — The team throttled the reindexing job.
- 10:34 UTC — Incremental indexing throughput exceeded incoming event volume.
- 10:42 UTC — Index lag returned to the normal operating range.

## 4. Root cause

The reindexing job competed with incremental indexing workers for CPU and storage
resources. As a result, the Search Service could not apply product-change events
at the rate they arrived. The source database remained healthy, but the search
projection became increasingly stale.

## 5. Contributing factors

The reindexing job had no strict resource budget. Alerts emphasized search request
latency and did not adequately emphasize the age of the oldest unapplied event.
The team had not tested a large reindex under realistic concurrent update traffic.

## 6. Resolution

Responders confirmed that the source catalog was current and that indexing events
were still being produced. They inspected consumer throughput, event age, indexing
errors, and resource utilization. They throttled reindexing and allowed incremental
workers to catch up before confirming search freshness.

The team did not restart the Catalog Service or treat the issue as database
unavailability because source reads and writes remained healthy.

## 7. Preventive actions

- Track indexing lag and the age of the oldest unapplied event.
- Set resource budgets for bulk reindexing jobs.
- Test reindexing under concurrent catalog updates.
- Alert when incremental indexing throughput remains below event arrival rate.
- Provide a documented method to verify search freshness against source records.

## 8. Lessons learned

Search is a derived projection of catalog data, so source-of-truth health does not
guarantee search freshness. Responders must distinguish event-delivery failure,
indexing throughput limits, and source-data problems before selecting mitigation.
A bulk reindex should not starve normal incremental updates.
