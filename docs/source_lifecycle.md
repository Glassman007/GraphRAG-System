# Source Lifecycle

Product lifecycle values include `DRAFT`, `CONNECTED`, `HEALTHY`, `DEGRADED`, `STALE`, `AUTH_ERROR`, `SYNC_ERROR`, and `DISABLED`. Connection status and ingestion status are intentionally separate.

Connection health: `HEALTHY`, `AUTH_FAILED`, `UNREACHABLE`, `RATE_LIMITED`, `PERMISSION_ERROR` where supported by the adapter.

Ingestion health: `NEVER_RUN`, `RUNNING`, `SUCCESS`, `PARTIAL`, `FAILED`, `STALE`.

Staleness is derived from `expected_sync_interval_minutes` and the latest successful synchronization; lack of data change alone never makes a source stale. Scheduling settings are persisted, but Phase 13 does not fake a scheduler/worker. Manual sync is authoritative.
