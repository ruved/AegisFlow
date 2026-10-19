# Order Service Database Pool Incident Logs

> Incident ID: INC-2026-0412
> Service: Order Service
> Environment: production-simulated
> All timestamps, identifiers, and log entries are fictional.

## Log excerpt

```text
2026-04-12T14:02:11Z INFO  service=order-service instance=order-03 event=pool_metrics active=48 idle=2 max=50
2026-04-12T14:03:04Z WARN  service=order-service instance=order-02 event=pool_threshold active=49 idle=1 max=50
2026-04-12T14:04:19Z ERROR service=order-service instance=order-02 event=db_acquire_timeout duration_ms=2000 correlation_id=req-a81f
2026-04-12T14:05:02Z WARN  service=api-gateway event=upstream_timeout upstream=order-service duration_ms=3000 correlation_id=req-a81f
2026-04-12T14:07:45Z INFO  service=order-service instance=order-01 event=pool_metrics active=50 idle=0 max=50
2026-04-12T14:09:17Z WARN  service=database event=slow_query query_group=order_history duration_ms=1840
2026-04-12T14:12:31Z WARN  service=database event=slow_query query_group=order_history duration_ms=2115
2026-04-12T14:14:08Z INFO  service=incident-response event=investigation_note finding=long_running_order_history_queries
2026-04-12T14:19:42Z INFO  service=order-service event=config_change change=disable_order_history_query actor=oncall
2026-04-12T14:24:10Z INFO  service=order-service instance=order-02 event=pool_metrics active=31 idle=19 max=50
2026-04-12T14:30:05Z INFO  service=api-gateway event=health_check status=healthy
```

## Evidence interpretation

- Pool utilization reached its configured maximum before mitigation.
- The gateway timeout sharing correlation ID `req-a81f` links an upstream failure to a database-acquisition timeout.
- Slow `order_history` queries support the root cause documented in PM-001.
- Pool metrics improved after the problematic query path was disabled.
- These logs do not prove that every failed request had the same cause.

## Retrieval cautions

Use timestamps and correlation IDs to connect evidence. Do not infer missing events or claim that a log entry proves more than it records. Consult the current database-pool runbook for remediation; the historical version is retained only for comparison.
