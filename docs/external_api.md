# Phase 11 External API

Phase 11 exposes a stable `/api/v1` application boundary over the existing GraphHacks services. Legacy/internal routes remain for compatibility; external clients should use `/api/v1`.

## Architecture

```text
External client
  -> request correlation
  -> authentication / tenant principal
  -> Pydantic validation + bounds
  -> permission gate
  -> existing Phase 3-10 service
  -> external response mapping
  -> stable error/status contract
```

Route handlers do not reimplement reasoning, planning, coordination, learning, analytics, ingestion, or retrieval. FalkorDB remains canonical.

## Resource groups

The v1 API exposes versioned resources for Situations, Investigations, Entities/Graph, Claims, Evidence, Plans/Tasks, Agents, Decisions, Actions, Simulations, History, Processes, Risks, Retrieval, Artifacts, and System introspection.

The primary investigation retrieval operation remains graph-first. Vector search is not the public investigation abstraction.

## Safety boundaries

- no arbitrary Cypher route;
- no arbitrary SQL route;
- no arbitrary external URL proxy;
- all organizational data routes are tenant-bound;
- governed action execution delegates to Phase 6 governance/idempotency;
- Claim revalidation and Evidence invalidation delegate to Phase 7;
- simulations are derived/noncanonical;
- response sanitization removes secret-like internal properties.

## OpenAPI

Swagger is available at `/docs`. External endpoints use explicit tags, request models, response models where appropriate, summaries, descriptions, validation bounds, and shared error responses.

## Phase 13 source-management API
The external API now includes `/api/v1/connectors`, CRUD-style `/api/v1/sources`, connection test, dry-run preview, manual sync, enable/disable, ingestion run/record/error browsing, identity review/resolution and `/api/v1/lineage/entities/{entity_id}`. Source credentials are write-only secret material and are never returned. Live DB/API access is server-registered rather than arbitrary SQL/URL input.
