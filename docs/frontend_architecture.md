# Phase 12 Frontend Architecture

Phase 12 is a functional browser client for the stable Phase 11 `/api/v1` boundary. The browser never connects to FalkorDB, artifact paths, internal Python services, SQL, or provider URLs directly.

## Stack

- React 18 + TypeScript
- Vite
- React Router
- TanStack Query for server state
- Cytoscape.js for graph views
- Vitest + React Testing Library
- Playwright for live browser acceptance

The design is deliberately plain and operations-console oriented. Styling is last; data correctness and inspectability come first.

## Runtime flow

```text
React route
  -> typed API module
  -> centralized apiRequest()
  -> /api/v1/...
  -> Phase 11 auth / tenant / validation
  -> existing Phase 3-10 services
  -> response mapper
  -> TanStack Query cache
  -> page / graph / provenance panel
```

## State

Server state belongs in TanStack Query. The only cross-page client state is API configuration/authentication in `AuthContext`. Page filters and `as_of` values are URL-driven where practical. Mutations invalidate only related query families.

## Graph rendering

`src/graph/adapters.ts` converts existing backend responses into a common `UiGraphNode` / `UiGraphEdge` representation. `GraphView` is the only Cytoscape rendering wrapper. It does not infer backend business semantics; it only renders relationships the backend returned.

## Local development

Vite proxies `/api` and `/health` to `http://127.0.0.1:8000`, so local browser development does not require direct database access or permissive CORS. A separate API base can be supplied with `VITE_API_BASE_URL`.
