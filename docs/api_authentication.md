# External API Authentication and Authorization

## Principal

Authentication resolves a `Principal` with:

- `subject`
- `tenant_id`
- `roles`
- `permissions`

Clients may use `Authorization: Bearer <token>` or `X-API-Key`.

## Test credentials

Development/test mode provides deterministic local tokens such as `test-admin-token` and `test-reader-token`. These are automatically disabled when `GRAPH_HACKS_ENV=production`, and can also be disabled with `GRAPH_HACKS_DISABLE_TEST_AUTH=1`.

Production/test-run principals may be configured through `GRAPH_HACKS_API_PRINCIPALS_JSON`. Secrets are environment configuration only and are never stored in FalkorDB.

## Tenant binding

The authenticated principal determines the tenant-scoped `FalkorGraphClient`. An optional `X-Tenant-ID` must match the principal tenant or the request fails with `TENANT_MISMATCH`.

## Permissions

The v1 boundary distinguishes read operations from governed mutations. Current permission vocabulary includes:

- `READ_GRAPH`
- `READ_EVIDENCE`
- `READ_ORG_ANALYTICS`
- `CREATE_INVESTIGATION`
- `CREATE_PLAN`
- `CLAIM_TASK`
- `WRITE_FINDING`
- `PROPOSE_ACTION`
- `EXECUTE_ACTION`
- `MANAGE_INGESTION`
- `ADMIN`

Permission checks supplement rather than replace Phase 6 action governance and Phase 7 validation rules.
