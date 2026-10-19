# PM-003: Order Event Consumer Backlog

> Incident ID: INC-2026-0618
> Date: 2026-06-18
> Severity: SEV-2
> Affected services: Notification Service, Order Service
> Status: Resolved
> Document type: Synthetic incident postmortem

## 1. Summary

On 2026-06-18, the Notification Service fell behind its Kafka order-event topic.
Incoming events continued arriving, but consumer throughput dropped after a
downstream email provider began responding slowly. Consumer lag increased until
order-confirmation notifications were delayed by approximately 24 minutes.

All incident details and metrics in this postmortem are fictional.

## 2. Customer impact

Customers received some order-confirmation emails late. Order creation and payment
processing remained operational. The incident did not indicate that Kafka had lost
events; the primary problem was delayed consumption.

## 3. Timeline

- 16:10 UTC — Notification consumer throughput began declining.
- 16:13 UTC — Consumer lag crossed the operational warning threshold.
- 16:17 UTC — Lag exceeded 80,000 messages and continued growing.
- 16:21 UTC — Responders identified elevated downstream email-provider latency.
- 16:27 UTC — The team reduced pressure on the provider using bounded concurrency.
- 16:34 UTC — Consumer throughput exceeded incoming event volume.
- 16:44 UTC — Consumer lag returned to the normal operating range.

## 4. Root cause

Each consumer worker performed a synchronous downstream email operation before
completing its event-processing path. Slow provider responses occupied workers
longer than expected. The resulting processing rate fell below the incoming event
rate, causing Kafka lag to accumulate.

## 5. Contributing factors

The notification path lacked a sufficiently strict downstream concurrency limit.
Alerts detected lag growth but did not initially correlate it with provider latency.
The team also lacked a documented threshold for scaling consumers versus reducing
downstream pressure.

## 6. Resolution

Responders confirmed that partitions were assigned and consumers were making
progress. They inspected processing latency, rebalance activity, error rates, and
provider response times. The team bounded downstream concurrency and allowed
consumers to drain the backlog at a sustainable rate.

The response followed `../runbooks/RB-003-kafka-consumer-backlog.md`. Consumer concurrency
was not increased blindly because additional consumers would not solve a bottleneck
caused by a constrained downstream provider.

## 7. Preventive actions

- Add alerts correlating consumer lag with processing latency and provider errors.
- Bound downstream request concurrency.
- Define safe consumer-scaling limits and partition constraints.
- Test backlog recovery under downstream latency and transient failures.
- Track the age of the oldest unprocessed event, not only total lag.

## 8. Lessons learned

Growing consumer lag indicates that processing capacity is insufficient for the
current incoming workload, but it does not identify the bottleneck by itself.
Scaling consumers can make a downstream dependency problem worse. Responders
must establish whether the constraint is partition parallelism, consumer resources,
processing logic, or an external dependency before choosing mitigation.
