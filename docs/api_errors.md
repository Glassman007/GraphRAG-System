# External API Error Contract

Versioned API failures use a stable envelope:

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Resource was not found.",
    "details": {},
    "request_id": "..."
  }
}
```

Stable codes include `INVALID_REQUEST`, `UNAUTHORIZED`, `FORBIDDEN`, `TENANT_MISMATCH`, `NOT_FOUND`, `CONFLICT`, `INVALID_STATE_TRANSITION`, `VALIDATION_FAILED`, `TEMPORAL_SCOPE_INVALID`, `RATE_LIMITED`, `DEPENDENCY_UNAVAILABLE`, and `INTERNAL_ERROR`.

Pydantic/request validation failures use HTTP 422 with `VALIDATION_FAILED`. Authentication uses 401, authorization/tenant mismatch 403, missing resources 404, state/idempotency conflicts 409, rate limits 429, and dependency failures 503 where applicable.

The v1 handler never intentionally returns stack traces, credentials, Cypher, SQL, or secret configuration to clients.
