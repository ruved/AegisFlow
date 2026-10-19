# AegisShop — Service Dependency Map

> Status: Synthetic training corpus
> Version: 1.0
> Companion document: services/architecture.md

## 1. Direct dependencies

| Service | Depends on | Dependency type | Potential failure impact |
|---|---|---|---|
| API Gateway | Catalog Service | Synchronous HTTP | Product details may fail or time out |
| API Gateway | Search Service | Synchronous HTTP | Search requests may fail or time out |
| API Gateway | Order Service | Synchronous HTTP | Order creation may fail or time out |
| Catalog Service | PostgreSQL | Database | Product reads or updates may fail |
| Catalog Service | Redis | Cache | Higher database load or stale cached data |
| Order Service | PostgreSQL | Database | Order reads and writes may fail |
| Order Service | Inventory Service | Synchronous HTTP | Stock reservation may fail or time out |
| Order Service | Payment Service | Synchronous HTTP | Payment authorization may fail or time out |
| Order Service | Kafka | Event publishing | Downstream order processing may be delayed |
| Payment Service | External Payment Provider | External HTTP | Payment outcomes may be delayed or unavailable |
| Payment Service | PostgreSQL | Database | Payment state persistence may fail |
| Payment Service | Kafka | Event publishing | Payment notifications may be delayed |
| Inventory Service | PostgreSQL | Database | Stock reads and reservations may fail |
| Inventory Service | Kafka | Event consumption | Inventory event processing may lag |
| Notification Service | Kafka | Event consumption | Customer notifications may be delayed |
| Search Service | Kafka | Event consumption | Product index updates may be delayed |

## 2. Failure propagation examples

### PostgreSQL connection pool exhaustion
A service may be unable to acquire a database connection. Requests can queue,
time out, or fail. Retries may increase database pressure if not bounded.

### Redis cache stampede
A popular key expires or is evicted. Many requests may simultaneously query
PostgreSQL, increasing latency and connection-pool usage in Catalog Service.

### Kafka consumer backlog
Events accumulate faster than consumers process them. Notifications, inventory
updates, or search indexing may become stale even when API requests still succeed.

### External payment provider slowdown
Payment requests may time out. Blind retries can create duplicate attempts
unless the integration uses appropriate idempotency controls.

### Bad deployment
An incompatible configuration or application change may increase errors in
one service and propagate failures to synchronous callers.

## 3. Dependency interpretation rules

- A dependency indicates a possible failure path, not proof that an incident occurred.
- Synchronous dependencies can propagate latency and errors to callers.
- Asynchronous dependencies commonly propagate delay and backlog rather than
  immediate request failure.
- Actual impact depends on timeouts, retries, queue capacity, fallback behavior,
  and the affected endpoint.
- PostgreSQL is authoritative for the business data owned by each service.
- Search indexing is eventually consistent; temporary search lag does not
  automatically mean that an order or catalog write failed.

## 4. Known corpus limitations

This is a simplified fictional architecture. It does not specify real network
topology, replication, deployment regions, capacity limits, or production SLAs.
