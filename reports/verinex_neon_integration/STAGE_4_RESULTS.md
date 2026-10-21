# Stage 4: Company Brain SQL graph exploration

Date: 2026-10-21 (Asia/Calcutta). Working commit: `a93cfe21cd8dbc0fffa51e58bff487f3ef1fdacd`. No Git changes were reset, committed, or pushed. Pre-existing uncommitted work was preserved.

## Implementation

| Files | Change |
| --- | --- |
| `backend/app/services/company_brain_schema_service.py`, `backend/app/api_v1/router.py` | Added bounded, read-only Company Brain SQL schema and table-detail endpoints. They query the configured FalkorDB graph with the authenticated tenant on every node, return persisted tables/FKs, selected table columns/constraints, repository/file evidence, and source constraint properties. Routes require `READ_GRAPH`; source filtering uses existing source IDs. No graph or tenant is hardcoded in production. |
| `frontend/src/api/companyBrain.ts`, `frontend/src/graph/adapters.ts` | Added typed API calls and a conversion from returned tables/FK edges to the existing `GraphView` format. |
| `frontend/src/pages/CompanyBrainPage.tsx`, `frontend/src/pages/SqlSchemaPanel.tsx` | Added a SQL schema tab using the existing Cytoscape graph component. Selecting a table shows columns, PK/FK constraints, incoming/outgoing FK connections, repository, SQL file, commit, file hash, and immutable GitHub source-line links. Clicking a connected table follows the real edge. The source-management link appears only with `MANAGE_INGESTION`. |
| `frontend/src/pages/sources/SourceDetailPage.tsx` | Added a link from an existing GitHub source detail page to its Company Brain schema view, preserving the current Sources workflow. |
| `backend/tests/test_neon_schema_stage4.py`, `frontend/src/test/sqlSchemaStage4.test.tsx`, `frontend/e2e/neon-schema-stage4.spec.ts` | Focused API/access-control, graph adapter/UI, and real-browser checks. |

GitHub retrieval, SQL extraction, graph ontology, ingestion and agent functionality were not modified. The disposable Stage 3 graph remained intact. No GitHub request or ingestion run occurred in this stage.

## Checks

Commands ran from `G:\graphhacks` unless the row names `frontend` as its working directory.

| Command | Result |
| --- | --- |
| `G:\gitTools\.venv-verinex-stage3\Scripts\python.exe -m pytest -q backend/tests/test_neon_schema_stage4.py --tb=short` | **2 passed** against a unique disposable FalkorDB test graph. Verified persisted table/FK/detail responses, source filtering, tenant isolation, 401 without credentials, and 403 without `READ_GRAPH`. One installed Starlette/httpx deprecation warning. |
| `npm run typecheck` (`frontend`) | **PASS**. |
| `npm test -- src/test/sqlSchemaStage4.test.tsx src/test/graphAdapters.test.ts` (`frontend`) | **13 passed**: graph conversion, table inspection and FK navigation, plus existing graph adapter tests. React Router future-flag warnings only. An initial test assertion matched the same constraint name twice in the intended UI and was corrected; final run passed. |
| `npx playwright test e2e/neon-schema-stage4.spec.ts --reporter=line` (`frontend`) | **1 passed** in a real browser against local API and Vite services, reading the existing Stage 3 FalkorDB graph. Repeated after the final access-control UI change. |
| `git diff --check -- backend/app/api_v1/router.py frontend/src/api/companyBrain.ts frontend/src/graph/adapters.ts frontend/src/pages/CompanyBrainPage.tsx frontend/src/pages/sources/SourceDetailPage.tsx` | **PASS**; Git emitted only line-ending notices. |

## Real API and browser evidence

The authenticated API read the existing graph `verinex_neon_stage3_7bf1ada9` for tenant `neon-stage3` through its configured `FALKORDB_GRAPH` setting. `GET /api/v1/company-brain/sql-schema` returned **15 tables and 18 actual `FOREIGN_KEY_TO` edges**. `GET /api/v1/company-brain/sql-schema/{table_id}` returned the real `public.payment` table with **6 columns, 4 constraints, 3 FK connections**, and `dvdrental.sql` provenance at commit `b54cb67534bf20775803b181b7a1c6f573422161`. The same API check confirmed 401 without authentication.

The Playwright check opened `/company-brain?tab=sql-schema`, selected `public.payment` in the existing graph, inspected the `payment_rental_id_fkey` GitHub source-line link, then used the visible FK connection controls to navigate **payment → rental → inventory → film**. These pages used live backend responses from the persisted FalkorDB graph; no mock graph data was used in that browser run. Local API and Vite processes started for this verification were stopped afterward.

Remaining blockers: **none for Stage 4 scope**. The graph view is bounded to the first 200 tables and clearly marks truncation; selecting a source narrows larger graphs. Comprehensive schema pagination and broader SQL parsing remain outside this stage.
