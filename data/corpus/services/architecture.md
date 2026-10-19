# AegisShop — Service Architecture

> Status: Synthetic training corpus
> Version: 1.0
> Purpose: Shared reference for AegisFlow retrieval and incident-analysis evaluation.
> All service names, incidents, metrics, identifiers, and configurations are fictional.

## 1. System overview

AegisShop is a fictional e-commerce platform. Customers browse products,
place orders, pay for purchases, and receive shipment updates.

The system contains seven services:

1. API Gateway
2. Catalog Service
3. Order Service
4. Payment Service
5. Inventory Service
6. Notification Service
7. Search Service

## 2. Service responsibilities

### API Gateway
Entry point for client traffic. Performs request routing, authentication
integration, rate limiting, and request correlation ID propagation.

### Catalog Service
Owns product descriptions, prices, and product metadata. Uses PostgreSQL
as its primary datastore and Redis for frequently accessed catalog data.

### Order Service
Owns order creation and order lifecycle state. Uses PostgreSQL and publishes
order events to Kafka. It calls Inventory and Payment during order processing.

### Payment Service
Coordinates payment authorization with a fictional external payment provider.
Stores payment status in PostgreSQL and publishes payment outcome events.

### Inventory Service
Tracks available stock and reservations. Uses PostgreSQL and consumes
order-related events from Kafka.

### Notification Service
Consumes order and payment events from Kafka and sends simulated email
and SMS notifications. Failed messages may be retried.

### Search Service
Serves product searches using a fictional search index. Receives catalog
change events and maintains an eventually consistent index.

## 3. Dependency map

Customer
  -> API Gateway
      -> Catalog Service -> PostgreSQL
                        -> Redis
      -> Search Service -> Search Index
      -> Order Service -> PostgreSQL
                       -> Inventory Service -> PostgreSQL
                       -> Payment Service -> External Payment Provider
                       -> Kafka
      -> Payment Service -> PostgreSQL
                         -> Kafka
Kafka
  -> Inventory Service
  -> Notification Service
  -> Search Service

## 4. Shared operational assumptions

- All services emit structured logs with timestamp, service, severity,
  environment, and correlation_id where applicable.
- Service-to-service calls have finite timeouts.
- Retries can amplify load if not bounded.
- Kafka consumers can fall behind when processing capacity is insufficient.
- Redis data can expire or be evicted; PostgreSQL remains authoritative
  for data owned by Catalog, Order, Payment, and Inventory.
- Search results may lag behind catalog updates.
- A successful HTTP response does not necessarily prove that an asynchronous
  downstream action has completed.

## 5. Corpus consistency rules

This document is the current architecture reference for the synthetic corpus.
Incident reports may describe historical behavior or obsolete configurations.
When two operational documents conflict, their timestamps and version status
must be considered rather than assuming the newest-looking value is correct.

Do not interpret any example service, host, incident, or metric as real
production infrastructure.
