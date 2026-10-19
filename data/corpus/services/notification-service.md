# Notification Service — Service Architecture

> Service ID: SVC-006
> Status: Current synthetic architecture
> Last reviewed: 2026-10-16
> System: AegisShop
> All systems, metrics, and incidents in this corpus are fictional.

## Responsibility

Notification Service processes asynchronous events and sends customer-facing notifications, such as order confirmations and payment-status messages. It consumes relevant events from Kafka, prepares notification content, and communicates with configured email or messaging providers.

Notification Service does not own orders, payment transactions, or inventory records. Order Service owns the order lifecycle, and Payment Service owns payment processing. A notification is a downstream communication about business state; it is not the authoritative record of that state.

## Dependencies and event flow

Order-related events are published to Kafka and consumed by Notification Service. The service processes messages, applies notification rules, and calls the relevant outbound provider. Its operation depends on Kafka availability, consumer health, valid message formats, and the responsiveness of the external notification provider.

If the provider slows down, consumers may process messages more slowly and Kafka lag can rise. Increasing consumer concurrency without checking downstream capacity may create more provider requests, connection contention, or throttling. A backlog can therefore be caused by a downstream dependency rather than a Kafka broker failure.

A notification may also be delayed or duplicated during retries or message redelivery. Such behavior does not, by itself, establish that the underlying order or payment operation was repeated.

## Signals to inspect

Review consumer lag, message arrival rate, successful processing rate, processing latency, retry counts, dead-letter volume, consumer rebalances, and provider response latency. Compare the incoming event rate with the completed processing rate to determine whether the backlog is growing or shrinking.

Inspect representative message identifiers, event timestamps, partition distribution, and provider error responses. Distinguish a slow consumer from a slow outbound provider, a poison message, and repeated consumer rebalances before choosing a mitigation.

## Operational safeguards

Use bounded consumer concurrency and controlled retry policies. Preserve failed messages and enough metadata for investigation. Follow the established dead-letter and replay procedure rather than repeatedly reprocessing a problematic message without understanding its failure.

Before scaling consumers, verify that Kafka partitions, service resources, and downstream provider capacity can support the extra concurrency. Use idempotent handling where practical to reduce duplicate notification effects. Avoid declaring a business transaction failed solely because its notification is delayed.

## Related corpus documents

- `architecture.md` — system-wide service inventory and assumptions.
- `dependency-map.md` — cross-service dependencies and failure propagation.
- `../runbooks/RB-003-kafka-consumer-backlog.md` — current consumer-backlog response procedure.
- `../postmortems/PM-003-kafka-consumer-backlog.md` — provider latency caused Notification Service consumer lag.
- `../runbooks/RB-006-payment-provider-latency.md` — a separate example of downstream-provider latency.

## Retrieval cautions

This document describes intended synthetic architecture, not live queue health. Use metrics and logs to determine the actual bottleneck. Kafka lag is evidence of delayed consumption, not proof that Kafka itself is broken. A delayed notification is not proof that the associated order or payment failed.
