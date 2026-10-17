# External API Idempotency

Mutating v1 operations accept `Idempotency-Key` where a repeated client request could otherwise duplicate externally visible work. The external boundary caches the request fingerprint/result for safe replay and rejects incompatible reuse of the same key.

This HTTP-layer idempotency does not replace canonical service-level semantics:

- Action execution still uses Phase 6 `ActionAttempt`/lease/idempotency coordination.
- Plan/task identity remains deterministic in Phase 5/6.
- Retrieval Evidence writeback remains deterministic in Phase 10.
- Ingestion retains Phase 9 source-record/cursor idempotency.

Clients cannot use an idempotency key to bypass governance or an invalid lifecycle transition.
