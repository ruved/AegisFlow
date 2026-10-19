# RB-003: Kafka Consumer Backlog

> Status: Current synthetic runbook
> Version: 1.0
> Owner: Event Platform
> Applies to: Inventory Service, Notification Service, Search Service
> Last reviewed: 2026-10-16

## 1. Purpose

Use this procedure when Kafka consumer lag increases and downstream processing
falls behind incoming event production.

All metrics, thresholds, topics, and examples are fictional.

## 2. Symptoms

- Consumer lag increases continuously for five minutes.
- Event processing delay exceeds the service objective.
- The oldest unprocessed event becomes progressively older.
- Notification delivery or search-index freshness deteriorates.
- Consumer logs show repeated processing failures or rebalances.

Consumer lag alone does not prove that Kafka brokers are unhealthy.

## 3. Initial triage

1. Identify the affected topic, consumer group, and downstream service.
2. Compare incoming event rate with successful processing rate.
3. Inspect lag per partition, consumer health, rebalance frequency, and error rate.
4. Check whether a deployment, traffic spike, or dependency slowdown preceded the lag.
5. Inspect dead-letter or retry queues if the consumer uses them.

## 4. Diagnosis

### Production rate exceeds consumption capacity

Compare the rate of newly produced events with the rate of completed processing.
Determine whether the imbalance is temporary or sustained.

### Poison message or repeated processing failure

Inspect error logs for a recurring event identifier or payload failure.
Check whether retries repeatedly prevent progress on a partition.

### Consumer dependency slowdown

Check database latency, external API latency, and connection-pool pressure.
A slow downstream dependency can reduce event processing throughput.

### Rebalances or unhealthy consumers

Inspect consumer restarts, group membership changes, partition assignment,
and processing duration relative to configured polling limits.

## 5. Mitigation

1. If lag began after a consumer deployment, evaluate rollback.
2. If a poison message is confirmed, follow the approved dead-letter or quarantine
   procedure; do not silently discard business events.
3. If downstream dependencies are saturated, address that bottleneck before
   increasing consumer concurrency.
4. Increase consumer capacity only after checking partition count, dependency
   capacity, and ordering requirements.
5. Apply bounded retries and backoff where repeated failures are causing load.
6. Preserve enough event metadata to investigate delayed or failed processing.

Do not blindly increase consumers when partition count or database capacity
limits useful parallelism.

## 6. Verification

Observe the consumer group for at least five minutes:

- Processing throughput meets or exceeds incoming throughput.
- Lag decreases consistently.
- Oldest-event age improves.
- Processing errors and rebalance frequency return toward baseline.
- Downstream services do not become overloaded by the recovery.

## 7. Rollback and escalation

Revert a concurrency or configuration change if downstream errors, database
pressure, or rebalance frequency worsens. Escalate if lag continues growing
despite processing throughput meeting the expected operating capacity.

## 8. Closure notes

Record the affected topic and consumer group, lag trend, event rates, root cause
or uncertainty, mitigation, and verification evidence. Document any quarantined
events and their recovery plan.
