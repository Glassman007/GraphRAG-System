# Phase 12 Frontend / Backend Mapping

All browser data comes from `/api/v1`.

| UI | Primary backend endpoints |
|---|---|
| Bootstrap | `GET /api/v1/capabilities`, `GET /api/v1/ready`, `GET /api/v1/session` |
| Situations | `GET /api/v1/situations`, `GET /api/v1/situations/{id}`, `/context`, `/timeline`, `/claims`, `/evidence`, `/tasks`, `POST /investigate` |
| Investigation | `GET /api/v1/investigations/{id}`, `/findings`, `/evidence`, `/retrievals`, `POST /retrieve` |
| Plans / Task graph | `GET/POST /api/v1/plans`, `GET /api/v1/plans/{id}`, `/tasks` |
| Task blackboard | `GET /api/v1/tasks/{id}`, `/dependencies`, `/coordination-state`, `/execution`, `POST /claim`, `/start`, `/checkpoint`, `/resume` |
| Agents | `GET /api/v1/agents`, `/{id}`, `/{id}/tasks`, `/{id}/capabilities` |
| Knowledge | `GET /api/v1/claims`, `/claims/{id}`, `/evidence`, `/conflicts`, `/lineage`; Evidence detail/provenance/artifact |
| Authority | `GET /api/v1/conflicts/{entity_id}/resolve` |
| Decision genealogy | `GET /api/v1/decisions/{id}`, `/genealogy`, `/evidence`, `/outcomes` |
| Action governance | `GET /api/v1/actions/{id}`, `/governance`, `/attempts`; `POST /api/v1/actions`, `POST /{id}/execute` |
| Entity | `GET /api/v1/entities/{id}`, `/neighbors`, `/relationships`, `/provenance`, `/history` |
| Blast radius | `GET /api/v1/entities/{id}/blast-radius`, `GET /api/v1/paths` |
| Simulations | `POST /api/v1/simulations/counterfactual`, `/bus-factor` |
| Process | `GET /api/v1/processes/{scope}`, `/timeline`, `/policy-drift` |
| Commitments | `GET /api/v1/risks/commitments` |
| Ownership gaps | `GET /api/v1/risks/ownership-gaps` |
| Expertise | `GET /api/v1/company-brain/expertise` |
| Bus factor | `GET /api/v1/risks/bus-factor` |
| Bottlenecks | `GET /api/v1/risks/bottlenecks` |
| Bridges | `GET /api/v1/risks/bridges` |
| Duplicate initiatives | `GET /api/v1/risks/initiative-collisions` |
| Anomalies | `GET /api/v1/anomalies` |

Phase 12 added only thin API facades for anomalies, authority resolution, company-wide expertise, and authenticated session/permission discovery. No reasoning algorithm was reimplemented in HTTP route handlers or React.

## Phase 13 Sources
`/sources*` → `/api/v1/connectors`, `/api/v1/sources*`, `/api/v1/sources/identity-review*`. Entity “Why?” lineage → `/api/v1/lineage/entities/{entity_id}`. Source wizard test/preview/sync maps directly to backend SourceControlService operations; no ingestion/entity-resolution/provenance logic runs in React.
